"""Service layer orchestrating incident lifecycle, SLA calculations, and persistence."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Mapping, Optional, Sequence

from nexus.correlation.models import CorrelationGroup
from nexus.detection.models import _normalize_utc_timestamp
from nexus.incidents.enums import (
    ActorType,
    IncidentPriority,
    IncidentSeverity,
    IncidentStatus,
    TimelineEventType,
)
from nexus.incidents.exceptions import (
    DuplicateIncidentError,
    IncidentNotFoundError,
    InvalidStateTransitionError,
)
from nexus.incidents.metrics import IncidentMetricsReport, MetricsCalculator
from nexus.incidents.models import Incident, TimelineEvent, _generate_id
from nexus.incidents.repository import IncidentRepository
from nexus.incidents.severity import OperationalSeverityPolicy
from nexus.incidents.sla import SLACalculator
from nexus.rca.models import RCAResult, RootCauseType, TargetType


class IncidentService:
    """Core domain service for creating, managing, and tracking operational incidents."""

    def __init__(
        self,
        repository: IncidentRepository,
        severity_policy: Optional[OperationalSeverityPolicy] = None,
        sla_calculator: Optional[SLACalculator] = None,
        metrics_calculator: Optional[MetricsCalculator] = None,
    ) -> None:
        self._repo = repository
        self._severity_policy = severity_policy or OperationalSeverityPolicy()
        self._sla_calculator = sla_calculator or SLACalculator()
        self._metrics_calculator = metrics_calculator or MetricsCalculator(self._sla_calculator)

    def create_incident(
        self,
        correlation_group: CorrelationGroup,
        rca_result: RCAResult,
        actor: str = "SYSTEM",
        creation_timestamp: Optional[datetime] = None,
    ) -> Incident:
        """Create a new incident from completed correlation and RCA analysis.

        Guarantees:
        - Prevents duplicate incident creation for the same correlation group.
        - Supports UNKNOWN RCA results without rejection.
        - Assigns severity based on explicit operational impact policy (not RCA confidence).
        - Generates initial CREATED timeline event.
        - Persists atomically.
        """
        # Idempotency check at service level
        existing = self._repo.get_by_correlation_group_id(correlation_group.group_id)
        if existing is not None:
            raise DuplicateIncidentError(correlation_group.group_id)

        now = (
            _normalize_utc_timestamp("creation_timestamp", creation_timestamp)
            if creation_timestamp
            else datetime.now(timezone.utc)
        )

        severity = self._severity_policy.evaluate(correlation_group)
        priority = self._severity_policy.get_priority(severity)
        deadlines = self._sla_calculator.calculate_deadlines(now, severity)

        # Extract primary RCA hypothesis details
        primary = rca_result.primary_hypothesis
        if primary is not None:
            cause_type = primary.cause_type
            target_id = primary.target_id
            target_type = primary.target_type
            confidence = primary.confidence_score
            if confidence is not None:
                if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                    raise ValueError(f"rca_confidence_score must be numeric, got {type(confidence).__name__}")
                f_conf = float(confidence)
                if not math.isfinite(f_conf) or f_conf < 0.0 or f_conf > 1.0:
                    raise ValueError(f"rca_confidence_score must be between 0.0 and 1.0, got {f_conf}")
                confidence = round(f_conf, 4)
            title = f"[{severity.value}] {cause_type.value} on {target_id}"
            desc = primary.explanation
        else:
            cause_type = RootCauseType.UNKNOWN
            target_id = None
            target_type = None
            confidence = None
            title = f"[{severity.value}] Unresolved network anomaly in group {correlation_group.group_id}"
            desc = correlation_group.correlation_reason or "Incident created with unverified root cause."

        # Structured serialization of hypotheses and evidence for traceability
        serialized_hypotheses = [
            {
                "hypothesis_id": h.hypothesis_id,
                "cause_type": h.cause_type.value,
                "target_id": h.target_id,
                "target_type": h.target_type.value,
                "confidence_score": h.confidence_score,
                "explanation": h.explanation,
            }
            for h in rca_result.hypotheses
        ]

        serialized_evidence = []
        if primary is not None:
            for ev in primary.evidence_items:
                serialized_evidence.append(
                    {
                        "source_node_id": ev.source_node_id,
                        "metric_name": ev.metric_name,
                        "observed_value": ev.observed_value,
                        "threshold_or_baseline": ev.threshold_or_baseline,
                        "reasoning": ev.reasoning,
                        "severity": ev.severity.value if ev.severity else None,
                        "evidence_source": ev.evidence_source,
                    }
                )

        incident_id = _generate_id("INC")

        created_event = TimelineEvent(
            event_id=_generate_id("EVT"),
            incident_id=incident_id,
            event_type=TimelineEventType.CREATED,
            timestamp=now,
            actor=actor,
            actor_type=ActorType.SYSTEM,
            details={
                "correlation_group_id": correlation_group.group_id,
                "severity": severity.value,
                "priority": priority.value,
                "suspected_cause_type": cause_type.value if cause_type else None,
                "suspected_target_id": target_id,
                "alarm_count": len(correlation_group.alarm_ids),
                "affected_node_count": len(correlation_group.node_ids),
            },
        )

        incident = Incident(
            incident_id=incident_id,
            correlation_group_id=correlation_group.group_id,
            status=IncidentStatus.OPEN,
            severity=severity,
            priority=priority,
            title=title,
            description=desc,
            alarm_ids=correlation_group.alarm_ids,
            affected_node_ids=correlation_group.node_ids,
            suspected_cause_type=cause_type,
            suspected_target_id=target_id,
            suspected_target_type=target_type,
            rca_confidence_score=confidence,
            rca_hypotheses=tuple(serialized_hypotheses),
            rca_evidence=tuple(serialized_evidence),
            created_at=now,
            ack_deadline=deadlines.ack_deadline,
            resolve_deadline=deadlines.resolve_deadline,
            timeline=(created_event,),
        )

        return self._repo.create(incident)

    def acknowledge_incident(
        self,
        incident_id: str,
        actor: str,
        timestamp: Optional[datetime] = None,
        actor_type: ActorType = ActorType.OPERATOR,
    ) -> Incident:
        """Acknowledge an active incident."""
        incident = self._repo.get_by_id(incident_id)
        if incident is None:
            raise IncidentNotFoundError(incident_id)

        updated = incident.acknowledge(actor=actor, timestamp=timestamp, actor_type=actor_type)
        return self._repo.update(updated)

    def resolve_incident(
        self,
        incident_id: str,
        actor: str,
        timestamp: Optional[datetime] = None,
        notes: Optional[str] = None,
        actor_type: ActorType = ActorType.OPERATOR,
    ) -> Incident:
        """Resolve an active or acknowledged incident."""
        incident = self._repo.get_by_id(incident_id)
        if incident is None:
            raise IncidentNotFoundError(incident_id)

        updated = incident.resolve(
            actor=actor, timestamp=timestamp, notes=notes, actor_type=actor_type
        )
        return self._repo.update(updated)

    def get_incident(self, incident_id: str) -> Incident:
        """Retrieve an incident by ID."""
        incident = self._repo.get_by_id(incident_id)
        if incident is None:
            raise IncidentNotFoundError(incident_id)
        return incident

    def list_incidents(
        self,
        status: Optional[IncidentStatus] = None,
        severity: Optional[IncidentSeverity] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Incident], int]:
        """List incidents with filtering and pagination."""
        return self._repo.list_incidents(
            status=status, severity=severity, limit=limit, offset=offset
        )

    def get_timeline(self, incident_id: str) -> list[TimelineEvent]:
        """Retrieve timeline events for an incident."""
        # Ensure incident exists
        self.get_incident(incident_id)
        return self._repo.get_timeline(incident_id)

    def get_metrics(
        self,
        as_of: Optional[datetime] = None,
        mttd_seconds: Optional[float] = None,
    ) -> IncidentMetricsReport:
        """Compute operational metrics across all persisted incidents without size truncation."""
        incidents_iter = self._repo.iter_all_incidents(batch_size=2000)
        return self._metrics_calculator.compute_metrics(
            incidents=incidents_iter,
            as_of=as_of,
            mttd_seconds=mttd_seconds,
        )
