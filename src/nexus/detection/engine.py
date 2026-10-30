"""Coordinator engine for threshold and statistical anomaly detection and alarm processing."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from nexus.detection.alarm_manager import AlarmKey, AlarmManager
from nexus.detection.exceptions import (
    DetectionError,
    DuplicateObservationError,
    TelemetryOrderError,
)
from nexus.detection.models import (
    Alarm,
    AnomalyEvent,
    DetectionSource,
    _normalize_utc_timestamp,
)
from nexus.detection.statistical_detector import (
    StatisticalDetector,
    StatisticalDetectorConfig,
)
from nexus.detection.threshold_detector import (
    ThresholdDetector,
    extract_snapshot_metrics,
)
from nexus.telemetry.models import KPISnapshot
from nexus.topology.enums import NodeType


@dataclass(frozen=True)
class DetectionBatchResult:
    """Structured result of evaluating a batch of telemetry snapshots.

    Attributes:
        processed_snapshots_count: Number of telemetry snapshots processed.
        anomaly_events: All raw anomaly events flagged during evaluation.
        new_alarms: Newly raised alarms during this batch.
        updated_alarms: Existing active alarms updated with recurring observations.
        cleared_alarms: Active alarms that recovered and cleared during this batch.
        active_alarms: Current complete pool of active alarms after processing.
    """

    processed_snapshots_count: int
    anomaly_events: tuple[AnomalyEvent, ...]
    new_alarms: tuple[Alarm, ...]
    updated_alarms: tuple[Alarm, ...]
    cleared_alarms: tuple[Alarm, ...]
    active_alarms: tuple[Alarm, ...]


def _validate_node_types_mapping(
    node_types: Optional[Mapping[Any, Any]],
) -> Optional[dict[str, Optional[NodeType]]]:
    """Validate and normalize node_types mapping before batch processing."""
    if node_types is None:
        return None
    if not isinstance(node_types, Mapping):
        raise DetectionError(f"node_types must be a mapping, got {type(node_types).__name__}")
    validated: dict[str, Optional[NodeType]] = {}
    for node_id, n_type in node_types.items():
        if not isinstance(node_id, str) or not node_id.strip():
            raise DetectionError(f"node_types key must be a non-empty string, got {node_id!r}")
        if n_type is None:
            validated[node_id] = None
        elif isinstance(n_type, NodeType):
            validated[node_id] = n_type
        elif isinstance(n_type, str):
            try:
                validated[node_id] = NodeType(n_type.upper().strip())
            except ValueError as exc:
                raise DetectionError(
                    f"Invalid NodeType string '{n_type}' for node '{node_id}'"
                ) from exc
        else:
            raise DetectionError(
                f"Invalid NodeType value for node '{node_id}': {type(n_type).__name__}"
            )
    return validated


class AnomalyDetectionEngine:
    """Coordinates threshold and statistical detectors with alarm lifecycle management.

    Invariants and Operational Policies:
    - Independent Detectors: Runs threshold rules and statistical detectors without cross-detector bias.
    - Ground Truth Separation: The detection engine never consumes or inspects fault definitions or ground truth.
    - Timestamp Ordering: Telemetry for each node must arrive in strictly monotonic chronological order.
    - Duplicate Rejection: Duplicate observations for the same node and timestamp are rejected with DuplicateObservationError.
    - Atomic Batch Validation: Batch inputs are fully validated prior to mutating any internal state or baselines.
    - Flapping Protection: Recovery uses hysteresis thresholds; absent metrics never clear an alarm.
    - Determinism: Identical ordered snapshots and configuration produce identical alarms and metrics.
    """

    def __init__(
        self,
        threshold_detector: Optional[ThresholdDetector] = None,
        statistical_detector: Optional[StatisticalDetector] = None,
        alarm_manager: Optional[AlarmManager] = None,
        enable_threshold: bool = True,
        enable_statistical: bool = True,
    ) -> None:
        self._threshold_detector = (
            threshold_detector if threshold_detector is not None else ThresholdDetector()
        )
        self._statistical_detector = (
            statistical_detector if statistical_detector is not None else StatisticalDetector()
        )
        self._alarm_manager = alarm_manager if alarm_manager is not None else AlarmManager()

        self._enable_threshold = enable_threshold
        self._enable_statistical = enable_statistical

        # Tracks last observed UTC timestamp per node_id for strictly monotonic ordering enforcement
        self._last_node_timestamps: dict[str, datetime] = {}

    @property
    def threshold_detector(self) -> ThresholdDetector:
        return self._threshold_detector

    @property
    def statistical_detector(self) -> StatisticalDetector:
        return self._statistical_detector

    @property
    def alarm_manager(self) -> AlarmManager:
        return self._alarm_manager

    @property
    def enable_threshold(self) -> bool:
        return self._enable_threshold

    @property
    def enable_statistical(self) -> bool:
        return self._enable_statistical

    def get_active_alarms(self) -> list[Alarm]:
        """Return all currently active alarms."""
        return self._alarm_manager.get_active_alarms()

    def get_cleared_alarms(self) -> list[Alarm]:
        """Return all historical cleared alarms."""
        return self._alarm_manager.get_cleared_alarms()

    def get_all_alarms(self) -> list[Alarm]:
        """Return all alarms (active and cleared)."""
        return self._alarm_manager.get_all_alarms()

    def _validate_batch_integrity(
        self,
        snapshots: Sequence[KPISnapshot],
    ) -> None:
        """Validate batch types, uniqueness, and chronological monotonicity per node.

        Raises:
            DetectionError: If an item is not a KPISnapshot.
            DuplicateObservationError: If duplicate (node_id, timestamp) pairs exist in the batch.
            TelemetryOrderError: If timestamps for a node are out-of-order or earlier than previous.
        """
        temp_last_ts: dict[str, datetime] = dict(self._last_node_timestamps)
        seen_in_batch: set[tuple[str, datetime]] = set()

        for s in snapshots:
            if not isinstance(s, KPISnapshot):
                raise DetectionError(f"Expected KPISnapshot instance, got {type(s).__name__}")

            norm_ts = _normalize_utc_timestamp("timestamp", s.timestamp)
            pair = (s.node_id, norm_ts)

            if pair in seen_in_batch:
                raise DuplicateObservationError(
                    f"Duplicate observation for node '{s.node_id}' at timestamp {norm_ts.isoformat()}"
                )
            seen_in_batch.add(pair)

            if s.node_id in temp_last_ts:
                prev_ts = temp_last_ts[s.node_id]
                if norm_ts < prev_ts:
                    raise TelemetryOrderError(
                        f"Out-of-order telemetry for node '{s.node_id}': timestamp {norm_ts.isoformat()} "
                        f"is earlier than previous observation at {prev_ts.isoformat()}"
                    )
                elif norm_ts == prev_ts:
                    raise DuplicateObservationError(
                        f"Duplicate observation for node '{s.node_id}' at timestamp {norm_ts.isoformat()}"
                    )

            temp_last_ts[s.node_id] = norm_ts

    def process_snapshot(
        self,
        snapshot: KPISnapshot,
        node_type: Optional[NodeType] = None,
    ) -> DetectionBatchResult:
        """Process a single telemetry snapshot and return detection results."""
        return self.process_batch([snapshot], node_types={snapshot.node_id: node_type} if node_type else None)

    def process_batch(
        self,
        snapshots: Sequence[KPISnapshot],
        node_types: Optional[Mapping[str, Optional[NodeType]]] = None,
    ) -> DetectionBatchResult:
        """Process a batch of telemetry snapshots atomically and deterministically.

        Args:
            snapshots: Sequence of KPISnapshot instances.
            node_types: Optional mapping from node_id to NodeType for rule scoping.

        Returns:
            DetectionBatchResult containing events and alarm updates.
        """
        if not isinstance(snapshots, Sequence):
            raise DetectionError(f"snapshots must be a Sequence, got {type(snapshots).__name__}")

        if not snapshots:
            return DetectionBatchResult(
                processed_snapshots_count=0,
                anomaly_events=(),
                new_alarms=(),
                updated_alarms=(),
                cleared_alarms=(),
                active_alarms=tuple(self._alarm_manager.get_active_alarms()),
            )

        # 1. Atomic pre-validation (validate all inputs before mutating state)
        norm_node_types = _validate_node_types_mapping(node_types)
        self._validate_batch_integrity(snapshots)

        # 2. Snapshot engine state for transactional rollback
        saved_timestamps = dict(self._last_node_timestamps)
        saved_stats = self._statistical_detector.snapshot_state()
        saved_alarms = self._alarm_manager.snapshot_state()

        try:
            all_events: list[AnomalyEvent] = []
            new_alarms: list[Alarm] = []
            updated_alarms: list[Alarm] = []
            cleared_alarms: list[Alarm] = []

            # 3. Sequential processing
            for snapshot in snapshots:
                node_type = norm_node_types.get(snapshot.node_id) if norm_node_types else None
                snap_events: list[AnomalyEvent] = []

                # A. Threshold detection
                if self._enable_threshold:
                    t_events = self._threshold_detector.evaluate_snapshot(snapshot, node_type=node_type)
                    snap_events.extend(t_events)

                # B. Statistical detection
                if self._enable_statistical:
                    s_events = self._statistical_detector.evaluate_snapshot(snapshot)
                    snap_events.extend(s_events)

                all_events.extend(snap_events)

                # Track flagged keys in this observation
                flagged_keys: set[AlarmKey] = set()

                # C. Ingest events into AlarmManager
                for ev in snap_events:
                    key: AlarmKey = (ev.node_id, ev.metric_name, ev.rule_id, ev.source)
                    flagged_keys.add(key)
                    alarm, is_new = self._alarm_manager.process_anomaly(ev)
                    if is_new:
                        new_alarms.append(alarm)
                    else:
                        updated_alarms.append(alarm)

                # D. Evaluate recovery/clearing for active alarms on this node
                active_for_node = [
                    a for a in self._alarm_manager.get_active_alarms() if a.node_id == snapshot.node_id
                ]

                for active in active_for_node:
                    key = (active.node_id, active.metric_name, active.rule_id, active.source)
                    # If this condition was flagged as anomalous in this snapshot, it cannot clear
                    if key in flagged_keys:
                        continue

                    is_recovered: Optional[bool] = None

                    if active.source == DetectionSource.THRESHOLD:
                        is_recovered = self._threshold_detector.check_recovery(snapshot, active.rule_id)
                    elif active.source in (DetectionSource.STATISTICAL_MEDIAN, DetectionSource.STATISTICAL_EWMA):
                        is_recovered = self._statistical_detector.check_recovery(
                            snapshot, active.source, active.metric_name
                        )

                    if is_recovered is True:
                        cleared = self._alarm_manager.clear_alarm(key, snapshot.timestamp)
                        if cleared is not None:
                            cleared_alarms.append(cleared)

                # E. Update last seen timestamp for this node
                norm_ts = _normalize_utc_timestamp("timestamp", snapshot.timestamp)
                self._last_node_timestamps[snapshot.node_id] = norm_ts

            return DetectionBatchResult(
                processed_snapshots_count=len(snapshots),
                anomaly_events=tuple(all_events),
                new_alarms=tuple(new_alarms),
                updated_alarms=tuple(updated_alarms),
                cleared_alarms=tuple(cleared_alarms),
                active_alarms=tuple(self._alarm_manager.get_active_alarms()),
            )
        except Exception:
            # Transactional rollback on any batch failure
            self._last_node_timestamps = saved_timestamps
            self._statistical_detector.restore_state(saved_stats)
            self._alarm_manager.restore_state(saved_alarms)
            raise
