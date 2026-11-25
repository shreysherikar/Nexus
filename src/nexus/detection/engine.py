"""Coordinator engine for threshold and statistical anomaly detection and alarm processing."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

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


def _alarm_key(alarm: Alarm) -> AlarmKey:
    """Extract canonical deduplication identity key from an Alarm instance."""
    return (alarm.node_id, alarm.metric_name, alarm.rule_id, alarm.source)


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
            statistical_detector if statistical_detector is not None else StatisticalDetector(
                StatisticalDetectorConfig(
                    directional_mode=True,
                    consecutive_recovery_count=2,
                    recovery_hysteresis_factor=0.8,
                    surge_ratio_threshold=2.0,
                )
            )
        )
        self._alarm_manager = alarm_manager if alarm_manager is not None else AlarmManager()

        self._enable_threshold = enable_threshold
        self._enable_statistical = enable_statistical

        # Tracks last observed UTC timestamp per node_id for strictly monotonic ordering enforcement
        self._last_node_timestamps: dict[str, datetime] = {}
        # Tracks nodes whose baseline has been seeded from trusted architectural profiles
        self._seeded_nodes: set[str] = set()

    @property
    def seeded_nodes(self) -> frozenset[str]:
        """Return the set of node IDs whose baselines have been seeded."""
        return frozenset(self._seeded_nodes)

    def seed_node(
        self,
        node_id: str,
        node_type: Optional[NodeType] = None,
        overwrite: bool = False,
    ) -> bool:
        """Seed a node baseline from its trusted architectural profile exactly once."""
        if not overwrite and node_id in self._seeded_nodes:
            return False
        if node_type is None:
            prefix = node_id.split("-")[0].upper()
            if prefix == "CELL":
                node_type = NodeType.CELL
            elif prefix in ("SITE", "ENB", "GNB"):
                node_type = NodeType.SITE
            elif prefix == "AGG":
                node_type = NodeType.AGGREGATION
            elif prefix == "CORE":
                node_type = NodeType.CORE
        if node_type is not None:
            seeded = self._statistical_detector.seed_baselines(node_id, node_type, overwrite=overwrite)
            if seeded:
                self._seeded_nodes.add(node_id)
                return True
        return False

    def seed_nodes(
        self,
        nodes: Union[Mapping[str, Optional[NodeType]], Iterable[Any]],
        overwrite: bool = False,
    ) -> int:
        """Seed multiple nodes from their trusted architectural profiles."""
        count = 0
        if isinstance(nodes, Mapping):
            for nid, ntype in nodes.items():
                if self.seed_node(nid, ntype, overwrite=overwrite):
                    count += 1
        else:
            for item in nodes:
                nid = getattr(item, "node_id", None) or getattr(item, "id", None) or (str(item) if not isinstance(item, (dict, tuple, list)) else None)
                ntype = getattr(item, "node_type", None) or getattr(item, "type", None)
                if nid and self.seed_node(nid, ntype, overwrite=overwrite):
                    count += 1
        return count

    def reset(self) -> None:
        """Reset internal detector states, timestamps, and seeded registry."""
        self._last_node_timestamps.clear()
        self._seeded_nodes.clear()
        self._statistical_detector.reset()
        self._alarm_manager.reset()

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
        saved_seeded = set(self._seeded_nodes)
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
                    if node_type is not None:
                        try:
                            s_events = self._statistical_detector.evaluate_snapshot(snapshot, node_type=node_type)
                        except TypeError:
                            s_events = self._statistical_detector.evaluate_snapshot(snapshot)
                    else:
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

                    is_recovered: Optional[bool] = None

                    if active.source == DetectionSource.THRESHOLD:
                        if key in flagged_keys:
                            continue
                        is_recovered = self._threshold_detector.check_recovery(snapshot, active.rule_id)
                    elif active.source in (DetectionSource.STATISTICAL_MEDIAN, DetectionSource.STATISTICAL_EWMA):
                        # Decoupled recovery evaluation: evaluates even if statistical detection previously flagged
                        # under a contaminated baseline
                        is_recovered = self._statistical_detector.check_recovery(
                            snapshot, active.source, active.metric_name, node_type=node_type
                        )

                    if is_recovered is True:
                        if key in flagged_keys:
                            flagged_keys.remove(key)
                            snap_events = [e for e in snap_events if not (
                                e.node_id == active.node_id and e.metric_name == active.metric_name and e.source == active.source
                            )]
                            all_events = [e for e in all_events if not (
                                e.node_id == active.node_id and e.metric_name == active.metric_name and e.source == active.source
                            )]
                            new_alarms = [a for a in new_alarms if _alarm_key(a) != key]
                            updated_alarms = [a for a in updated_alarms if _alarm_key(a) != key]

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
