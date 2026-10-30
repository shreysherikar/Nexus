"""Domain models and enumerations for anomaly detection and alarm management."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
import types
from typing import Any, Mapping, Optional

from nexus.detection.exceptions import InvalidAlarmStateError


class Severity(str, Enum):
    """Alarm severity classifications."""

    WARNING = "WARNING"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"

    def __str__(self) -> str:
        return self.value


class AlarmStatus(str, Enum):
    """Lifecycle status of a network alarm."""

    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"

    def __str__(self) -> str:
        return self.value


class ComparisonOperator(str, Enum):
    """Relational comparison operators for threshold evaluation."""

    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="

    def __str__(self) -> str:
        return self.value


class DetectionSource(str, Enum):
    """Source detector originating an anomaly or alarm."""

    THRESHOLD = "THRESHOLD"
    STATISTICAL_MEDIAN = "STATISTICAL_MEDIAN"
    STATISTICAL_EWMA = "STATISTICAL_EWMA"

    def __str__(self) -> str:
        return self.value


def _normalize_utc_timestamp(name: str, ts: Any) -> datetime:
    """Validate and normalize a timestamp to UTC."""
    if not isinstance(ts, datetime):
        raise InvalidAlarmStateError(f"{name} must be a datetime, got {type(ts).__name__}")
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _validate_finite_float(name: str, val: Any) -> float:
    """Validate that val is a finite real number (not bool, NaN, or inf)."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise InvalidAlarmStateError(f"{name} must be a numeric value, got {type(val).__name__}")
    f_val = float(val)
    if not math.isfinite(f_val):
        raise InvalidAlarmStateError(f"{name} must be a finite number, got {f_val}")
    return f_val


def _freeze_evidence(val: Any) -> Any:
    """Recursively freeze evidence structures into immutable types."""
    if isinstance(val, Mapping):
        return types.MappingProxyType({k: _freeze_evidence(v) for k, v in val.items()})
    elif isinstance(val, (list, tuple)):
        return tuple(_freeze_evidence(item) for item in val)
    elif isinstance(val, (set, frozenset)):
        return frozenset(_freeze_evidence(item) for item in val)
    return val


@dataclass(frozen=True)
class AnomalyEvent:
    """Represents a point-in-time anomaly detection prior to alarm management.

    Attributes:
        node_id: Identifier of the network element.
        metric_name: Name of the telemetry metric exhibiting anomalous behavior.
        timestamp: UTC timestamp of the observation.
        source: Detection mechanism that flagged the condition.
        rule_id: Unique rule ID or statistical detector ID.
        severity: Assigned severity level.
        current_value: Observed metric value.
        threshold: Configured threshold or statistical baseline, if applicable.
        description: Human-readable explanation.
        evidence: Contextual diagnostic data (e.g. baseline, deviation, z-score).
    """

    node_id: str
    metric_name: str
    timestamp: datetime
    source: DetectionSource
    rule_id: str
    severity: Severity
    current_value: float
    threshold: Optional[float] = None
    description: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise InvalidAlarmStateError("node_id must be a non-empty string")
        if not isinstance(self.metric_name, str) or not self.metric_name.strip():
            raise InvalidAlarmStateError("metric_name must be a non-empty string")
        if not isinstance(self.rule_id, str) or not self.rule_id.strip():
            raise InvalidAlarmStateError("rule_id must be a non-empty string")

        norm_ts = _normalize_utc_timestamp("timestamp", self.timestamp)
        object.__setattr__(self, "timestamp", norm_ts)

        if not isinstance(self.source, DetectionSource):
            try:
                object.__setattr__(self, "source", DetectionSource(self.source))
            except (ValueError, TypeError) as exc:
                raise InvalidAlarmStateError(f"Invalid detection source: {self.source}") from exc

        if not isinstance(self.severity, Severity):
            try:
                object.__setattr__(self, "severity", Severity(self.severity))
            except (ValueError, TypeError) as exc:
                raise InvalidAlarmStateError(f"Invalid severity: {self.severity}") from exc

        val = _validate_finite_float("current_value", self.current_value)
        object.__setattr__(self, "current_value", val)

        if self.threshold is not None:
            t_val = _validate_finite_float("threshold", self.threshold)
            object.__setattr__(self, "threshold", t_val)

        if not isinstance(self.description, str):
            raise InvalidAlarmStateError(f"description must be a string, got {type(self.description).__name__}")

        if not isinstance(self.evidence, Mapping):
            raise InvalidAlarmStateError(f"evidence must be a mapping, got {type(self.evidence).__name__}")
        object.__setattr__(self, "evidence", _freeze_evidence(self.evidence))


@dataclass(frozen=True)
class Alarm:
    """Immutable representation of a network alarm with lifecycle state and evidence.

    Attributes:
        alarm_id: Globally unique identifier for this alarm instance.
        node_id: Target network element identifier.
        rule_id: Identifier of the threshold rule or statistical detector.
        metric_name: Name of the monitored KPI metric.
        source: Detection source mechanism.
        severity: Current severity classification.
        current_value: Most recently observed metric value.
        threshold: Threshold or baseline against which violation occurred.
        first_seen: UTC timestamp when the condition was first observed.
        last_seen: UTC timestamp of the most recent observation.
        observation_count: Total consecutive evaluation cycles condition persisted.
        status: Current lifecycle state (ACTIVE or CLEARED).
        cleared_at: UTC timestamp when the alarm cleared, or None if ACTIVE.
        description: Human-readable diagnosis.
        evidence: Contextual diagnostic data explaining the detection.
    """

    alarm_id: str
    node_id: str
    rule_id: str
    metric_name: str
    source: DetectionSource
    severity: Severity
    current_value: float
    threshold: Optional[float]
    first_seen: datetime
    last_seen: datetime
    observation_count: int
    status: AlarmStatus
    cleared_at: Optional[datetime] = None
    description: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.alarm_id, str) or not self.alarm_id.strip():
            raise InvalidAlarmStateError("alarm_id must be a non-empty string")
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise InvalidAlarmStateError("node_id must be a non-empty string")
        if not isinstance(self.rule_id, str) or not self.rule_id.strip():
            raise InvalidAlarmStateError("rule_id must be a non-empty string")
        if not isinstance(self.metric_name, str) or not self.metric_name.strip():
            raise InvalidAlarmStateError("metric_name must be a non-empty string")

        if not isinstance(self.source, DetectionSource):
            try:
                object.__setattr__(self, "source", DetectionSource(self.source))
            except (ValueError, TypeError) as exc:
                raise InvalidAlarmStateError(f"Invalid detection source: {self.source}") from exc

        if not isinstance(self.severity, Severity):
            try:
                object.__setattr__(self, "severity", Severity(self.severity))
            except (ValueError, TypeError) as exc:
                raise InvalidAlarmStateError(f"Invalid severity: {self.severity}") from exc

        if not isinstance(self.status, AlarmStatus):
            try:
                object.__setattr__(self, "status", AlarmStatus(self.status))
            except (ValueError, TypeError) as exc:
                raise InvalidAlarmStateError(f"Invalid status: {self.status}") from exc

        val = _validate_finite_float("current_value", self.current_value)
        object.__setattr__(self, "current_value", val)

        if self.threshold is not None:
            t_val = _validate_finite_float("threshold", self.threshold)
            object.__setattr__(self, "threshold", t_val)

        fs_utc = _normalize_utc_timestamp("first_seen", self.first_seen)
        ls_utc = _normalize_utc_timestamp("last_seen", self.last_seen)
        object.__setattr__(self, "first_seen", fs_utc)
        object.__setattr__(self, "last_seen", ls_utc)

        if fs_utc > ls_utc:
            raise InvalidAlarmStateError(
                f"first_seen ({fs_utc.isoformat()}) cannot be later than last_seen ({ls_utc.isoformat()})"
            )

        if isinstance(self.observation_count, bool) or not isinstance(self.observation_count, int) or self.observation_count < 1:
            raise InvalidAlarmStateError(
                f"observation_count must be an integer >= 1, got {self.observation_count}"
            )

        if self.status == AlarmStatus.CLEARED:
            if self.cleared_at is None:
                raise InvalidAlarmStateError("cleared_at timestamp must be provided when alarm status is CLEARED")
            clr_utc = _normalize_utc_timestamp("cleared_at", self.cleared_at)
            object.__setattr__(self, "cleared_at", clr_utc)
            if clr_utc < ls_utc:
                raise InvalidAlarmStateError(
                    f"cleared_at ({clr_utc.isoformat()}) cannot be earlier than last_seen ({ls_utc.isoformat()})"
                )
        else:
            if self.cleared_at is not None:
                raise InvalidAlarmStateError("cleared_at must be None when alarm status is ACTIVE")

        if not isinstance(self.description, str):
            raise InvalidAlarmStateError(f"description must be a string, got {type(self.description).__name__}")

        if not isinstance(self.evidence, Mapping):
            raise InvalidAlarmStateError(f"evidence must be a mapping, got {type(self.evidence).__name__}")
        object.__setattr__(self, "evidence", _freeze_evidence(self.evidence))
