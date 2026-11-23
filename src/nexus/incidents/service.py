"""Service layer orchestrating incident lifecycle, SLA calculations, and persistence."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Callable, Mapping, Optional, Sequence

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


EventPublisher = Callable[[str, dict[str, Any]], None]


class IncidentService:
    """Core domain service for creating, managing, and tracking operational incidents."""

    def __init__(
        self,
        repository: IncidentRepository,
        severity_policy: Optional[OperationalSeverityPolicy] = None,
        sla_calculator: Optional[SLACalculator] = None,
        metrics_calculator: Optional[MetricsCalculator] = None,
        event_publisher: Optional[EventPublisher] = None,
    ) -> None:
        self._repo = repository
        self._severity_policy = severity_policy or OperationalSeverityPolicy()
        self._sla_calculator = sla_calculator or SLACalculator()
        self._metrics_calculator = metrics_calculator or MetricsCalculator(self._sla_calculator)
        self._event_publisher = event_publisher

    def set_event_publisher(self, publisher: Optional[EventPublisher]) -> None:
        """Attach or detach an event publisher callback."""
        self._event_publisher = publisher

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_publisher:
            try:
                self._event_publisher(event_type, payload)
            except Exception:
                pass

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

        persisted = self._repo.create(incident)
        self._publish(
            "INCIDENT_CREATED",
            {
                "incident_id": persisted.incident_id,
                "status": persisted.status.value,
                "severity": persisted.severity.value,
                "priority": persisted.priority.value,
                "title": persisted.title,
                "correlation_group_id": persisted.correlation_group_id,
                "affected_node_ids": list(persisted.affected_node_ids),
                "created_at": persisted.created_at.isoformat(),
            },
        )
        return persisted

    def create_or_update_incident(
        self,
        correlation_group: CorrelationGroup,
        rca_result: Optional[RCAResult] = None,
        actor: str = "SYSTEM",
        creation_timestamp: Optional[datetime] = None,
    ) -> tuple[Incident, bool]:
        """Create a new incident or update an existing active incident for this failure cluster.

        Deduplication Guarantees:
        - Never creates duplicate incidents for repeated alarms belonging to the same active failure cluster.
        - First, checks if an incident exists for correlation_group.group_id.
        - If not, queries active incidents (OPEN or ACKNOWLEDGED) and matches against shared alarm IDs
          or identical anchor node and overlapping affected nodes.
        - When an active matching incident exists:
          * Merges new alarm IDs and affected node IDs.
          * Re-evaluates severity and upgrades if operational impact increases.
          * Updates RCA hypotheses, evidence, and suspected cause when new analysis is provided.
          * Appends appropriate timeline events (SEVERITY_CHANGED or NOTE_ADDED).
          * Atomically persists updates and broadcasts INCIDENT_UPDATED.
          * Returns (updated_incident, False).
        - When no active matching incident exists:
          * Calls create_incident() to persist the new incident.
          * Returns (created_incident, True).
        """
        now = (
            _normalize_utc_timestamp("creation_timestamp", creation_timestamp)
            if creation_timestamp
            else datetime.now(timezone.utc)
        )

        # 1. Exact match by correlation group ID
        existing = self._repo.get_by_correlation_group_id(correlation_group.group_id)

        # 2. If no exact group_id match, look for an active incident covering this failure cluster
        if existing is None:
            group_alarm_set = set(correlation_group.alarm_ids)
            group_node_set = set(correlation_group.node_ids)

            open_incidents, _ = self._repo.list_incidents(status=IncidentStatus.OPEN, limit=100)
            ack_incidents, _ = self._repo.list_incidents(status=IncidentStatus.ACKNOWLEDGED, limit=100)
            active_incidents = open_incidents + ack_incidents

            for candidate in active_incidents:
                # Check overlapping alarms with matching target or anchor
                primary_target = (
                    rca_result.primary_hypothesis.target_id
                    if (rca_result and rca_result.primary_hypothesis)
                    else None
                )
                if (
                    group_alarm_set
                    and (group_alarm_set & set(candidate.alarm_ids))
                    and (
                        not candidate.suspected_target_id
                        or candidate.suspected_target_id == correlation_group.anchor_node_id
                        or (primary_target and candidate.suspected_target_id == primary_target)
                    )
                ):
                    existing = candidate
                    break

                # Check shared anchor node / suspected target with overlapping affected nodes
                if (
                    correlation_group.anchor_node_id
                    and candidate.suspected_target_id == correlation_group.anchor_node_id
                    and (group_node_set & set(candidate.affected_node_ids))
                ):
                    existing = candidate
                    break

        # 3. If an active incident is found, update it
        if existing is not None and existing.status in (IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED):
            new_alarm_ids = set(correlation_group.alarm_ids) - set(existing.alarm_ids)
            merged_alarm_ids = tuple(sorted(set(existing.alarm_ids) | set(correlation_group.alarm_ids)))
            merged_node_ids = tuple(sorted(set(existing.affected_node_ids) | set(correlation_group.node_ids)))

            # Evaluate severity
            new_severity = self._severity_policy.evaluate(correlation_group)
            sev_rank = {
                IncidentSeverity.CRITICAL: 4,
                IncidentSeverity.MAJOR: 3,
                IncidentSeverity.WARNING: 2,
                IncidentSeverity.MINOR: 1,
            }
            existing_rank = sev_rank.get(existing.severity, 0)
            new_rank = sev_rank.get(new_severity, 0)

            severity_upgraded = new_rank > existing_rank
            effective_severity = new_severity if severity_upgraded else existing.severity
            effective_priority = self._severity_policy.get_priority(effective_severity)

            # Determine updated RCA details
            effective_cause = existing.suspected_cause_type
            effective_target_id = existing.suspected_target_id
            effective_target_type = existing.suspected_target_type
            effective_confidence = existing.rca_confidence_score
            effective_hypotheses = existing.rca_hypotheses
            effective_evidence = existing.rca_evidence
            effective_title = existing.title
            effective_desc = existing.description

            if rca_result is not None:
                primary = rca_result.primary_hypothesis
                should_update_rca = (
                    existing.suspected_cause_type in (None, RootCauseType.UNKNOWN)
                    or (primary is not None and (primary.confidence_score or 0.0) > (existing.rca_confidence_score or 0.0))
                    or len(existing.rca_hypotheses) == 0
                )
                if should_update_rca:
                    if primary is not None:
                        effective_cause = primary.cause_type
                        effective_target_id = primary.target_id
                        effective_target_type = primary.target_type
                        effective_confidence = (
                            round(float(primary.confidence_score), 4)
                            if primary.confidence_score is not None
                            else None
                        )
                        effective_title = f"[{effective_severity.value}] {effective_cause.value} on {effective_target_id}"
                        effective_desc = primary.explanation
                    effective_hypotheses = tuple(
                        {
                            "hypothesis_id": h.hypothesis_id,
                            "cause_type": h.cause_type.value,
                            "target_id": h.target_id,
                            "target_type": h.target_type.value,
                            "confidence_score": h.confidence_score,
                            "explanation": h.explanation,
                        }
                        for h in rca_result.hypotheses
                    )
                    if primary is not None:
                        effective_evidence = tuple(
                            {
                                "source_node_id": ev.source_node_id,
                                "metric_name": ev.metric_name,
                                "observed_value": ev.observed_value,
                                "threshold_or_baseline": ev.threshold_or_baseline,
                                "reasoning": ev.reasoning,
                                "severity": ev.severity.value if ev.severity else None,
                                "evidence_source": ev.evidence_source,
                            }
                            for ev in primary.evidence_items
                        )

            # Timeline events
            new_events: list[TimelineEvent] = []
            if severity_upgraded:
                new_events.append(
                    TimelineEvent(
                        event_id=_generate_id("EVT"),
                        incident_id=existing.incident_id,
                        event_type=TimelineEventType.SEVERITY_CHANGED,
                        timestamp=now,
                        actor=actor,
                        actor_type=ActorType.SYSTEM,
                        details={
                            "previous_severity": existing.severity.value,
                            "new_severity": effective_severity.value,
                            "reason": f"Merged {len(new_alarm_ids)} new alarm(s) escalated impact.",
                        },
                    )
                )
            elif new_alarm_ids:
                new_events.append(
                    TimelineEvent(
                        event_id=_generate_id("EVT"),
                        incident_id=existing.incident_id,
                        event_type=TimelineEventType.NOTE_ADDED,
                        timestamp=now,
                        actor=actor,
                        actor_type=ActorType.SYSTEM,
                        details={
                            "note": f"Correlated {len(new_alarm_ids)} additional active alarm(s).",
                            "new_alarm_ids": list(new_alarm_ids),
                        },
                    )
                )

            updated = Incident(
                incident_id=existing.incident_id,
                correlation_group_id=existing.correlation_group_id,
                status=existing.status,
                severity=effective_severity,
                priority=effective_priority,
                title=effective_title,
                description=effective_desc,
                alarm_ids=merged_alarm_ids,
                affected_node_ids=merged_node_ids,
                suspected_cause_type=effective_cause,
                suspected_target_id=effective_target_id,
                suspected_target_type=effective_target_type,
                rca_confidence_score=effective_confidence,
                rca_hypotheses=effective_hypotheses,
                rca_evidence=effective_evidence,
                created_at=existing.created_at,
                ack_deadline=existing.ack_deadline,
                resolve_deadline=existing.resolve_deadline,
                acknowledged_at=existing.acknowledged_at,
                acknowledged_by=existing.acknowledged_by,
                resolved_at=existing.resolved_at,
                resolved_by=existing.resolved_by,
                timeline=existing.timeline + tuple(new_events),
            )

            persisted = self._repo.update(updated)
            self._publish(
                "INCIDENT_UPDATED",
                {
                    "incident_id": persisted.incident_id,
                    "status": persisted.status.value,
                    "severity": persisted.severity.value,
                    "priority": persisted.priority.value,
                    "title": persisted.title,
                    "correlation_group_id": persisted.correlation_group_id,
                    "affected_node_ids": list(persisted.affected_node_ids),
                    "alarm_count": len(persisted.alarm_ids),
                },
            )
            return persisted, False

        # 4. Otherwise create a brand new incident
        if rca_result is None:
            rca_result = RCAResult(
                group_id=correlation_group.group_id,
                hypotheses=(),
                primary_hypothesis=None,
                analysis_timestamp=now,
                recommended_action="Perform diagnostic triage.",
            )

        new_incident = self.create_incident(
            correlation_group=correlation_group,
            rca_result=rca_result,
            actor=actor,
            creation_timestamp=now,
        )
        return new_incident, True

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
        persisted = self._repo.update(updated)
        self._publish(
            "INCIDENT_ACKNOWLEDGED",
            {
                "incident_id": persisted.incident_id,
                "status": persisted.status.value,
                "acknowledged_by": actor,
                "acknowledged_at": persisted.acknowledged_at.isoformat() if persisted.acknowledged_at else None,
            },
        )
        return persisted

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
        persisted = self._repo.update(updated)
        self._publish(
            "INCIDENT_RESOLVED",
            {
                "incident_id": persisted.incident_id,
                "status": persisted.status.value,
                "resolved_by": actor,
                "resolved_at": persisted.resolved_at.isoformat() if persisted.resolved_at else None,
                "notes": notes,
            },
        )
        return persisted

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
