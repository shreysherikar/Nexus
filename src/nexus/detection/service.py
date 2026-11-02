"""Service layer and read interface for network alarms and lifecycle management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

from nexus.detection.alarm_manager import AlarmKey, AlarmManager
from nexus.detection.engine import AnomalyDetectionEngine, DetectionBatchResult
from nexus.detection.models import (
    Alarm,
    AlarmStatus,
    AnomalyEvent,
    Severity,
)
from nexus.detection.rules import ThresholdRule
from nexus.detection.threshold_detector import ThresholdDetector
from nexus.telemetry.models import KPISnapshot
from nexus.topology.enums import NodeType

EventPublisher = Callable[[str, dict[str, Any]], None]


class AlarmService:
    """Service layer providing lifecycle operations and read querying over AlarmManager."""

    def __init__(
        self,
        alarm_manager: Optional[AlarmManager] = None,
        event_publisher: Optional[EventPublisher] = None,
        threshold_detector: Optional[ThresholdDetector] = None,
    ) -> None:
        self._manager = alarm_manager if alarm_manager is not None else AlarmManager()
        self._event_publisher = event_publisher
        self._threshold_detector = (
            threshold_detector if threshold_detector is not None else ThresholdDetector()
        )
        self._detection_engine = AnomalyDetectionEngine(
            threshold_detector=self._threshold_detector,
            alarm_manager=self._manager,
            enable_threshold=True,
            enable_statistical=True,
        )

    @property
    def manager(self) -> AlarmManager:
        return self._manager

    @property
    def threshold_detector(self) -> ThresholdDetector:
        return self._threshold_detector

    def get_rules(self) -> tuple[ThresholdRule, ...]:
        """Return the authoritative configured threshold detection rules."""
        return self._threshold_detector.rules

    def set_event_publisher(self, publisher: Optional[EventPublisher]) -> None:
        self._event_publisher = publisher

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_publisher:
            try:
                self._event_publisher(event_type, payload)
            except Exception:
                pass

    def process_anomaly(self, event: AnomalyEvent) -> tuple[Alarm, bool]:
        """Ingest anomaly, update or create alarm, and broadcast live event."""
        alarm, is_new = self._manager.process_anomaly(event)
        if is_new:
            self._publish(
                "ALARM_CREATED",
                {
                    "alarm_id": alarm.alarm_id,
                    "node_id": alarm.node_id,
                    "rule_id": alarm.rule_id,
                    "metric_name": alarm.metric_name,
                    "severity": alarm.severity.value,
                    "current_value": alarm.current_value,
                    "threshold": alarm.threshold,
                    "status": alarm.status.value,
                    "first_seen": alarm.first_seen.isoformat(),
                },
            )
        else:
            self._publish(
                "ALARM_UPDATED",
                {
                    "alarm_id": alarm.alarm_id,
                    "node_id": alarm.node_id,
                    "rule_id": alarm.rule_id,
                    "metric_name": alarm.metric_name,
                    "severity": alarm.severity.value,
                    "current_value": alarm.current_value,
                    "threshold": alarm.threshold,
                    "status": alarm.status.value,
                    "observation_count": alarm.observation_count,
                    "last_seen": alarm.last_seen.isoformat(),
                },
            )
        return alarm, is_new

    def clear_alarm(self, key: AlarmKey, cleared_at: datetime) -> Optional[Alarm]:
        """Clear active alarm, archive to history, and broadcast live event."""
        cleared = self._manager.clear_alarm(key, cleared_at)
        if cleared is not None:
            self._publish(
                "ALARM_CLEARED",
                {
                    "alarm_id": cleared.alarm_id,
                    "node_id": cleared.node_id,
                    "rule_id": cleared.rule_id,
                    "metric_name": cleared.metric_name,
                    "cleared_at": cleared.cleared_at.isoformat() if cleared.cleared_at else None,
                    "status": cleared.status.value,
                },
            )
        return cleared

    def process_snapshots(
        self,
        snapshots: Sequence[KPISnapshot],
        node_types: Optional[Mapping[str, Optional[NodeType]]] = None,
    ) -> DetectionBatchResult:
        """Evaluate a batch of snapshots against threshold and statistical detectors,
        updating AlarmManager and publishing live WebSocket events for new/updated/cleared alarms.
        """
        batch_result = self._detection_engine.process_batch(snapshots, node_types=node_types)
        for alarm in batch_result.new_alarms:
            self._publish(
                "ALARM_CREATED",
                {
                    "alarm_id": alarm.alarm_id,
                    "node_id": alarm.node_id,
                    "rule_id": alarm.rule_id,
                    "metric_name": alarm.metric_name,
                    "severity": alarm.severity.value,
                    "current_value": alarm.current_value,
                    "threshold": alarm.threshold,
                    "status": alarm.status.value,
                    "first_seen": alarm.first_seen.isoformat(),
                },
            )
        for alarm in batch_result.updated_alarms:
            self._publish(
                "ALARM_UPDATED",
                {
                    "alarm_id": alarm.alarm_id,
                    "node_id": alarm.node_id,
                    "rule_id": alarm.rule_id,
                    "metric_name": alarm.metric_name,
                    "severity": alarm.severity.value,
                    "current_value": alarm.current_value,
                    "threshold": alarm.threshold,
                    "status": alarm.status.value,
                    "observation_count": alarm.observation_count,
                    "last_seen": alarm.last_seen.isoformat(),
                },
            )
        for alarm in batch_result.cleared_alarms:
            self._publish(
                "ALARM_CLEARED",
                {
                    "alarm_id": alarm.alarm_id,
                    "node_id": alarm.node_id,
                    "rule_id": alarm.rule_id,
                    "metric_name": alarm.metric_name,
                    "cleared_at": alarm.cleared_at.isoformat() if alarm.cleared_at else None,
                    "status": alarm.status.value,
                },
            )
        return batch_result

    def get_alarms(
        self,
        node_id: Optional[str] = None,
        severity: Optional[Severity] = None,
        status: Optional[AlarmStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Alarm], int]:
        """Query actual alarm records with filtering, deterministic ordering, and pagination.

        Args:
            node_id: Optional node ID exact match.
            severity: Optional Severity filter (WARNING, MAJOR, CRITICAL).
            status: Optional AlarmStatus filter (ACTIVE, CLEARED).
            limit: Maximum alarms to return.
            offset: Number of items to skip.

        Returns:
            Tuple of (paginated list of Alarm, total matching count).
        """
        if status == AlarmStatus.ACTIVE:
            alarms = self._manager.get_active_alarms()
        elif status == AlarmStatus.CLEARED:
            alarms = self._manager.get_cleared_alarms()
        else:
            alarms = self._manager.get_all_alarms()

        filtered: list[Alarm] = []
        for a in alarms:
            if node_id and a.node_id != node_id:
                continue
            if severity is not None and a.severity != severity:
                continue
            filtered.append(a)

        # Deterministic sorting: last_seen descending (newest first), then alarm_id ascending
        filtered.sort(key=lambda a: (-a.last_seen.timestamp(), a.alarm_id))

        total = len(filtered)
        paginated = filtered[offset : offset + limit]
        return paginated, total

    def get_alarm_by_id(self, alarm_id: str) -> Optional[Alarm]:
        """Look up an authentic alarm record by its unique alarm ID across active and history."""
        for a in self._manager.get_all_alarms():
            if a.alarm_id == alarm_id:
                return a
        return None


_default_alarm_service: Optional[AlarmService] = None


def get_alarm_service() -> AlarmService:
    """Retrieve or initialize global AlarmService singleton."""
    global _default_alarm_service
    if _default_alarm_service is None:
        _default_alarm_service = AlarmService()
    return _default_alarm_service


def set_alarm_service(service: AlarmService) -> None:
    """Override global AlarmService instance (useful for tests)."""
    global _default_alarm_service
    _default_alarm_service = service
