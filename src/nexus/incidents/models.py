"""Domain models and entity specifications for NEXUS Incident Management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import uuid
from typing import Any, Mapping, Optional, Sequence

from nexus.detection.models import _freeze_evidence, _normalize_utc_timestamp
from nexus.incidents.enums import (
    ActorType,
    IncidentPriority,
    IncidentSeverity,
    IncidentStatus,
    TimelineEventType,
)
from nexus.incidents.exceptions import (
    InvalidIncidentDataError,
    InvalidStateTransitionError,
)
from nexus.incidents.sla import SLABreachStatus, SLACalculator
from nexus.rca.models import RootCauseType, TargetType


def _generate_id(prefix: str) -> str:
    """Generate a clean deterministic-friendly identifier."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class TimelineEvent:
    """An immutable record in the append-only incident timeline."""

    event_id: str
    incident_id: str
    event_type: TimelineEventType
    timestamp: datetime
    actor: str
    actor_type: ActorType = ActorType.SYSTEM
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise InvalidIncidentDataError("event_id must be a non-empty string")
        if not isinstance(self.incident_id, str) or not self.incident_id.strip():
            raise InvalidIncidentDataError("incident_id must be a non-empty string")
        if not isinstance(self.event_type, TimelineEventType):
            try:
                object.__setattr__(self, "event_type", TimelineEventType(self.event_type))
            except ValueError as exc:
                raise InvalidIncidentDataError(f"Invalid event_type: {self.event_type}") from exc

        ts = _normalize_utc_timestamp("timestamp", self.timestamp)
        object.__setattr__(self, "timestamp", ts)

        if not isinstance(self.actor, str) or not self.actor.strip():
            raise InvalidIncidentDataError("actor must be a non-empty string")

        if not isinstance(self.actor_type, ActorType):
            try:
                object.__setattr__(self, "actor_type", ActorType(self.actor_type))
            except ValueError as exc:
                raise InvalidIncidentDataError(f"Invalid actor_type: {self.actor_type}") from exc

        if not isinstance(self.details, Mapping):
            raise InvalidIncidentDataError(f"details must be a mapping, got {type(self.details).__name__}")
        object.__setattr__(self, "details", _freeze_evidence(self.details))


@dataclass(frozen=True)
class Incident:
    """Core domain entity representing an operational incident."""

    incident_id: str
    correlation_group_id: str
    status: IncidentStatus
    severity: IncidentSeverity
    priority: IncidentPriority
    title: str
    description: str
    alarm_ids: tuple[str, ...]
    affected_node_ids: tuple[str, ...]
    suspected_cause_type: Optional[RootCauseType]
    suspected_target_id: Optional[str]
    suspected_target_type: Optional[TargetType]
    rca_confidence_score: Optional[float]
    rca_hypotheses: tuple[Mapping[str, Any], ...]
    rca_evidence: tuple[Mapping[str, Any], ...]
    created_at: datetime
    ack_deadline: datetime
    resolve_deadline: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    timeline: tuple[TimelineEvent, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.incident_id, str) or not self.incident_id.strip():
            raise InvalidIncidentDataError("incident_id must be a non-empty string")
        if not isinstance(self.correlation_group_id, str) or not self.correlation_group_id.strip():
            raise InvalidIncidentDataError("correlation_group_id must be a non-empty string")

        if not isinstance(self.status, IncidentStatus):
            try:
                object.__setattr__(self, "status", IncidentStatus(self.status))
            except ValueError as exc:
                raise InvalidIncidentDataError(f"Invalid status: {self.status}") from exc

        if not isinstance(self.severity, IncidentSeverity):
            try:
                object.__setattr__(self, "severity", IncidentSeverity(self.severity))
            except ValueError as exc:
                raise InvalidIncidentDataError(f"Invalid severity: {self.severity}") from exc

        if not isinstance(self.priority, IncidentPriority):
            try:
                object.__setattr__(self, "priority", IncidentPriority(self.priority))
            except ValueError as exc:
                raise InvalidIncidentDataError(f"Invalid priority: {self.priority}") from exc

        # Timestamps
        ca = _normalize_utc_timestamp("created_at", self.created_at)
        ad = _normalize_utc_timestamp("ack_deadline", self.ack_deadline)
        rd = _normalize_utc_timestamp("resolve_deadline", self.resolve_deadline)
        object.__setattr__(self, "created_at", ca)
        object.__setattr__(self, "ack_deadline", ad)
        object.__setattr__(self, "resolve_deadline", rd)

        if self.acknowledged_at is not None:
            object.__setattr__(
                self,
                "acknowledged_at",
                _normalize_utc_timestamp("acknowledged_at", self.acknowledged_at),
            )
        if self.resolved_at is not None:
            object.__setattr__(
                self,
                "resolved_at",
                _normalize_utc_timestamp("resolved_at", self.resolved_at),
            )

        # RCA confidence validation: when present, must be finite float in [0.0, 1.0] (reject booleans, NaN, inf)
        if self.rca_confidence_score is not None:
            if isinstance(self.rca_confidence_score, bool) or not isinstance(self.rca_confidence_score, (int, float)):
                raise InvalidIncidentDataError(f"rca_confidence_score must be a float, got {type(self.rca_confidence_score).__name__}")
            f_conf = float(self.rca_confidence_score)
            if not math.isfinite(f_conf) or f_conf < 0.0 or f_conf > 1.0:
                raise InvalidIncidentDataError(f"rca_confidence_score must be between 0.0 and 1.0, got {f_conf}")
            object.__setattr__(self, "rca_confidence_score", round(f_conf, 4))

        # Tuples
        if not isinstance(self.alarm_ids, tuple):
            object.__setattr__(self, "alarm_ids", tuple(self.alarm_ids))
        if not isinstance(self.affected_node_ids, tuple):
            object.__setattr__(self, "affected_node_ids", tuple(self.affected_node_ids))
        if not isinstance(self.rca_hypotheses, tuple):
            object.__setattr__(self, "rca_hypotheses", tuple(self.rca_hypotheses))
        if not isinstance(self.rca_evidence, tuple):
            object.__setattr__(self, "rca_evidence", tuple(self.rca_evidence))
        if not isinstance(self.timeline, tuple):
            object.__setattr__(self, "timeline", tuple(self.timeline))

    def acknowledge(
        self,
        actor: str,
        timestamp: Optional[datetime] = None,
        actor_type: ActorType = ActorType.OPERATOR,
    ) -> Incident:
        """Acknowledge the incident.

        Allowed transitions:
        - OPEN -> ACKNOWLEDGED
        Disallowed:
        - Cannot acknowledge an already RESOLVED incident.
        - Cannot re-acknowledge an already ACKNOWLEDGED incident.
        """
        if self.status == IncidentStatus.RESOLVED:
            raise InvalidStateTransitionError(
                current_status=self.status.value,
                attempted_transition="acknowledge",
                reason="Cannot acknowledge an already resolved incident.",
            )
        if self.status == IncidentStatus.ACKNOWLEDGED:
            raise InvalidStateTransitionError(
                current_status=self.status.value,
                attempted_transition="acknowledge",
                reason="Incident is already acknowledged.",
            )

        ack_time = _normalize_utc_timestamp("timestamp", timestamp) if timestamp else datetime.now(timezone.utc)
        if ack_time < self.created_at:
            raise InvalidIncidentDataError(
                f"Acknowledgement timestamp ({ack_time.isoformat()}) cannot be earlier than creation ({self.created_at.isoformat()})."
            )

        event = TimelineEvent(
            event_id=_generate_id("EVT"),
            incident_id=self.incident_id,
            event_type=TimelineEventType.ACKNOWLEDGED,
            timestamp=ack_time,
            actor=actor,
            actor_type=actor_type,
            details={"previous_status": self.status.value, "new_status": IncidentStatus.ACKNOWLEDGED.value},
        )

        return Incident(
            incident_id=self.incident_id,
            correlation_group_id=self.correlation_group_id,
            status=IncidentStatus.ACKNOWLEDGED,
            severity=self.severity,
            priority=self.priority,
            title=self.title,
            description=self.description,
            alarm_ids=self.alarm_ids,
            affected_node_ids=self.affected_node_ids,
            suspected_cause_type=self.suspected_cause_type,
            suspected_target_id=self.suspected_target_id,
            suspected_target_type=self.suspected_target_type,
            rca_confidence_score=self.rca_confidence_score,
            rca_hypotheses=self.rca_hypotheses,
            rca_evidence=self.rca_evidence,
            created_at=self.created_at,
            ack_deadline=self.ack_deadline,
            resolve_deadline=self.resolve_deadline,
            acknowledged_at=ack_time,
            acknowledged_by=actor,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
            timeline=self.timeline + (event,),
        )

    def resolve(
        self,
        actor: str,
        timestamp: Optional[datetime] = None,
        notes: Optional[str] = None,
        actor_type: ActorType = ActorType.OPERATOR,
    ) -> Incident:
        """Resolve the incident.

        Allowed transitions:
        - OPEN -> RESOLVED
        - ACKNOWLEDGED -> RESOLVED
        Disallowed:
        - Cannot resolve an already RESOLVED incident (duplicate resolution).
        """
        if self.status == IncidentStatus.RESOLVED:
            raise InvalidStateTransitionError(
                current_status=self.status.value,
                attempted_transition="resolve",
                reason="Incident is already resolved.",
            )

        res_time = _normalize_utc_timestamp("timestamp", timestamp) if timestamp else datetime.now(timezone.utc)
        if res_time < self.created_at:
            raise InvalidIncidentDataError(
                f"Resolution timestamp ({res_time.isoformat()}) cannot be earlier than creation ({self.created_at.isoformat()})."
            )

        details: dict[str, Any] = {
            "previous_status": self.status.value,
            "new_status": IncidentStatus.RESOLVED.value,
        }
        if notes:
            details["resolution_notes"] = notes

        event = TimelineEvent(
            event_id=_generate_id("EVT"),
            incident_id=self.incident_id,
            event_type=TimelineEventType.RESOLVED,
            timestamp=res_time,
            actor=actor,
            actor_type=actor_type,
            details=details,
        )

        return Incident(
            incident_id=self.incident_id,
            correlation_group_id=self.correlation_group_id,
            status=IncidentStatus.RESOLVED,
            severity=self.severity,
            priority=self.priority,
            title=self.title,
            description=self.description,
            alarm_ids=self.alarm_ids,
            affected_node_ids=self.affected_node_ids,
            suspected_cause_type=self.suspected_cause_type,
            suspected_target_id=self.suspected_target_id,
            suspected_target_type=self.suspected_target_type,
            rca_confidence_score=self.rca_confidence_score,
            rca_hypotheses=self.rca_hypotheses,
            rca_evidence=self.rca_evidence,
            created_at=self.created_at,
            ack_deadline=self.ack_deadline,
            resolve_deadline=self.resolve_deadline,
            acknowledged_at=self.acknowledged_at,
            acknowledged_by=self.acknowledged_by,
            resolved_at=res_time,
            resolved_by=actor,
            timeline=self.timeline + (event,),
        )

    def get_sla_status(
        self,
        calculator: Optional[SLACalculator] = None,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> SLABreachStatus:
        """Compute SLA compliance status deterministically."""
        calc = calculator or SLACalculator()
        return calc.evaluate_sla(
            created_at=self.created_at,
            ack_deadline=self.ack_deadline,
            resolve_deadline=self.resolve_deadline,
            acknowledged_at=self.acknowledged_at,
            resolved_at=self.resolved_at,
            evaluation_timestamp=evaluation_timestamp,
        )
