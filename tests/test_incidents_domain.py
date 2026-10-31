"""Unit tests for NEXUS incident domain model, lifecycle, severity policy, SLA, and metrics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence
import pytest

from nexus.correlation.models import CorrelationGroup
from nexus.detection.models import Alarm, AlarmStatus, DetectionSource, Severity
from nexus.incidents.enums import (
    ActorType,
    IncidentPriority,
    IncidentSeverity,
    IncidentStatus,
    TimelineEventType,
)
from nexus.incidents.exceptions import (
    DuplicateIncidentError,
    InvalidIncidentDataError,
    InvalidStateTransitionError,
    SLABreachCalculationError,
)
from nexus.incidents.metrics import MetricsCalculator
from nexus.incidents.models import Incident, TimelineEvent, _generate_id
from nexus.incidents.severity import OperationalSeverityPolicy
from nexus.incidents.sla import (
    DEFAULT_SLA_TARGETS,
    SLACalculator,
    SLADeadlines,
    SLATarget,
)
from nexus.rca.models import (
    EvidenceItem,
    RCAResult,
    RootCauseHypothesis,
    RootCauseType,
    TargetType,
)
from nexus.topology.enums import NodeType


def make_test_alarm(
    alarm_id: str,
    node_id: str,
    severity: Severity = Severity.MAJOR,
    timestamp: Optional[datetime] = None,
) -> Alarm:
    ts = timestamp or datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return Alarm(
        alarm_id=alarm_id,
        node_id=node_id,
        rule_id="RULE-TEST",
        metric_name="availability_pct",
        source=DetectionSource.THRESHOLD,
        severity=severity,
        current_value=0.0,
        threshold=90.0,
        first_seen=ts,
        last_seen=ts,
        observation_count=1,
        status=AlarmStatus.ACTIVE,
    )


def make_test_group(
    group_id: str = "GRP-001",
    anchor_id: Optional[str] = "SITE-01",
    tier: Optional[NodeType] = NodeType.SITE,
    alarms: Optional[list[Alarm]] = None,
    node_ids: Optional[list[str]] = None,
) -> CorrelationGroup:
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    alms = alarms or [make_test_alarm("alm-1", "CELL-01", Severity.MAJOR, base_time)]
    nids = node_ids or list({a.node_id for a in alms})
    return CorrelationGroup(
        group_id=group_id,
        anchor_node_id=anchor_id,
        root_cause_tier=tier,
        alarms=tuple(alms),
        alarm_ids=tuple(a.alarm_id for a in alms),
        node_ids=tuple(nids),
        time_window_start=base_time,
        time_window_end=base_time + timedelta(seconds=60),
        correlation_reason="Test correlation reason",
    )


def make_test_rca_result(
    group_id: str = "GRP-001",
    cause_type: Optional[RootCauseType] = RootCauseType.CELL_OUTAGE,
    confidence: Optional[float] = 0.85,
) -> RCAResult:
    base_time = datetime(2026, 1, 1, 12, 1, 0, tzinfo=timezone.utc)
    if cause_type is None or cause_type == RootCauseType.UNKNOWN:
        return RCAResult(
            group_id=group_id,
            hypotheses=(),
            primary_hypothesis=None,
            analysis_timestamp=base_time,
        )

    hyp = RootCauseHypothesis(
        hypothesis_id=f"HYP-{group_id}",
        cause_type=cause_type,
        target_id="CELL-01",
        target_type=TargetType.NODE,
        confidence_score=confidence,
        explanation=f"Diagnosed {cause_type.value}",
        evidence_items=(
            EvidenceItem(
                source_node_id="CELL-01",
                metric_name="availability_pct",
                observed_value=0.0,
                threshold_or_baseline=10.0,
                reasoning="Availability collapse",
                severity=Severity.CRITICAL,
                evidence_source="ALARM",
            ),
        ),
        group_id=group_id,
    )
    return RCAResult(
        group_id=group_id,
        hypotheses=(hyp,),
        primary_hypothesis=hyp,
        analysis_timestamp=base_time,
    )


# ===========================================================================
# 1. Domain Model and Lifecycle Tests
# ===========================================================================

class TestIncidentLifecycle:
    """Test incident state transitions, lifecycle constraints, and validation."""

    def test_valid_lifecycle_open_to_acknowledged_to_resolved(self) -> None:
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(minutes=10)
        t2 = t0 + timedelta(minutes=45)

        deadlines = SLADeadlines(
            ack_deadline=t0 + timedelta(minutes=15),
            resolve_deadline=t0 + timedelta(minutes=60),
        )

        incident = Incident(
            incident_id="INC-001",
            correlation_group_id="GRP-001",
            status=IncidentStatus.OPEN,
            severity=IncidentSeverity.CRITICAL,
            priority=IncidentPriority.P1,
            title="Critical Cell Outage",
            description="Outage detected",
            alarm_ids=("alm-1",),
            affected_node_ids=("CELL-01",),
            suspected_cause_type=RootCauseType.CELL_OUTAGE,
            suspected_target_id="CELL-01",
            suspected_target_type=TargetType.NODE,
            rca_confidence_score=0.9,
            rca_hypotheses=(),
            rca_evidence=(),
            created_at=t0,
            ack_deadline=deadlines.ack_deadline,
            resolve_deadline=deadlines.resolve_deadline,
        )

        assert incident.status == IncidentStatus.OPEN
        assert incident.acknowledged_at is None
        assert incident.resolved_at is None

        # Transition: OPEN -> ACKNOWLEDGED
        acked = incident.acknowledge(actor="alice", timestamp=t1)
        assert acked.status == IncidentStatus.ACKNOWLEDGED
        assert acked.acknowledged_at == t1
        assert acked.acknowledged_by == "alice"
        assert len(acked.timeline) == 1
        assert acked.timeline[0].event_type == TimelineEventType.ACKNOWLEDGED

        # Transition: ACKNOWLEDGED -> RESOLVED
        resolved = acked.resolve(actor="bob", timestamp=t2, notes="Reset radio unit")
        assert resolved.status == IncidentStatus.RESOLVED
        assert resolved.resolved_at == t2
        assert resolved.resolved_by == "bob"
        assert len(resolved.timeline) == 2
        assert resolved.timeline[1].event_type == TimelineEventType.RESOLVED
        assert resolved.timeline[1].details.get("resolution_notes") == "Reset radio unit"

    def test_direct_resolution_from_open(self) -> None:
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(minutes=20)

        incident = Incident(
            incident_id="INC-002",
            correlation_group_id="GRP-002",
            status=IncidentStatus.OPEN,
            severity=IncidentSeverity.MAJOR,
            priority=IncidentPriority.P2,
            title="Major Issue",
            description="Details",
            alarm_ids=("alm-2",),
            affected_node_ids=("SITE-01",),
            suspected_cause_type=None,
            suspected_target_id=None,
            suspected_target_type=None,
            rca_confidence_score=None,
            rca_hypotheses=(),
            rca_evidence=(),
            created_at=t0,
            ack_deadline=t0 + timedelta(minutes=30),
            resolve_deadline=t0 + timedelta(hours=4),
        )

        resolved = incident.resolve(actor="operator1", timestamp=t1)
        assert resolved.status == IncidentStatus.RESOLVED
        assert resolved.resolved_at == t1
        assert resolved.acknowledged_at is None

    def test_cannot_acknowledge_resolved_incident(self) -> None:
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        incident = Incident(
            incident_id="INC-003",
            correlation_group_id="GRP-003",
            status=IncidentStatus.RESOLVED,
            severity=IncidentSeverity.WARNING,
            priority=IncidentPriority.P3,
            title="Resolved Issue",
            description="Details",
            alarm_ids=(),
            affected_node_ids=(),
            suspected_cause_type=None,
            suspected_target_id=None,
            suspected_target_type=None,
            rca_confidence_score=None,
            rca_hypotheses=(),
            rca_evidence=(),
            created_at=t0,
            ack_deadline=t0 + timedelta(minutes=60),
            resolve_deadline=t0 + timedelta(hours=12),
            resolved_at=t0 + timedelta(minutes=10),
            resolved_by="operator1",
        )

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            incident.acknowledge(actor="operator2")
        assert "Cannot acknowledge an already resolved incident" in str(exc_info.value)

    def test_cannot_resolve_already_resolved_incident(self) -> None:
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        incident = Incident(
            incident_id="INC-004",
            correlation_group_id="GRP-004",
            status=IncidentStatus.RESOLVED,
            severity=IncidentSeverity.WARNING,
            priority=IncidentPriority.P3,
            title="Resolved Issue",
            description="Details",
            alarm_ids=(),
            affected_node_ids=(),
            suspected_cause_type=None,
            suspected_target_id=None,
            suspected_target_type=None,
            rca_confidence_score=None,
            rca_hypotheses=(),
            rca_evidence=(),
            created_at=t0,
            ack_deadline=t0 + timedelta(minutes=60),
            resolve_deadline=t0 + timedelta(hours=12),
            resolved_at=t0 + timedelta(minutes=10),
            resolved_by="operator1",
        )

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            incident.resolve(actor="operator2")
        assert "Incident is already resolved" in str(exc_info.value)

    def test_cannot_reacknowledge_acknowledged_incident(self) -> None:
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        incident = Incident(
            incident_id="INC-005",
            correlation_group_id="GRP-005",
            status=IncidentStatus.ACKNOWLEDGED,
            severity=IncidentSeverity.MAJOR,
            priority=IncidentPriority.P2,
            title="Acked Issue",
            description="Details",
            alarm_ids=(),
            affected_node_ids=(),
            suspected_cause_type=None,
            suspected_target_id=None,
            suspected_target_type=None,
            rca_confidence_score=None,
            rca_hypotheses=(),
            rca_evidence=(),
            created_at=t0,
            ack_deadline=t0 + timedelta(minutes=30),
            resolve_deadline=t0 + timedelta(hours=4),
            acknowledged_at=t0 + timedelta(minutes=5),
            acknowledged_by="operator1",
        )

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            incident.acknowledge(actor="operator2")
        assert "Incident is already acknowledged" in str(exc_info.value)

    def test_reject_action_earlier_than_creation(self) -> None:
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        incident = Incident(
            incident_id="INC-006",
            correlation_group_id="GRP-006",
            status=IncidentStatus.OPEN,
            severity=IncidentSeverity.MAJOR,
            priority=IncidentPriority.P2,
            title="Issue",
            description="Details",
            alarm_ids=(),
            affected_node_ids=(),
            suspected_cause_type=None,
            suspected_target_id=None,
            suspected_target_type=None,
            rca_confidence_score=None,
            rca_hypotheses=(),
            rca_evidence=(),
            created_at=t0,
            ack_deadline=t0 + timedelta(minutes=30),
            resolve_deadline=t0 + timedelta(hours=4),
        )

        earlier_time = t0 - timedelta(minutes=5)
        with pytest.raises(InvalidIncidentDataError):
            incident.acknowledge(actor="op", timestamp=earlier_time)

        with pytest.raises(InvalidIncidentDataError):
            incident.resolve(actor="op", timestamp=earlier_time)


class TestConfidenceValidation:
    """Test confidence score validation across domain entities and service creation."""

    def test_missing_confidence_preserved_as_none(self) -> None:
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        inc = Incident(
            incident_id="INC-CONF-1",
            correlation_group_id="GRP-CONF-1",
            status=IncidentStatus.OPEN,
            severity=IncidentSeverity.MAJOR,
            priority=IncidentPriority.P2,
            title="Test",
            description="Test",
            alarm_ids=(),
            affected_node_ids=(),
            suspected_cause_type=RootCauseType.CELL_OUTAGE,
            suspected_target_id="CELL-01",
            suspected_target_type=TargetType.NODE,
            rca_confidence_score=None,
            rca_hypotheses=(),
            rca_evidence=(),
            created_at=t0,
            ack_deadline=t0 + timedelta(minutes=30),
            resolve_deadline=t0 + timedelta(hours=4),
        )
        assert inc.rca_confidence_score is None

    def test_valid_confidence_score(self) -> None:
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        inc = Incident(
            incident_id="INC-CONF-2",
            correlation_group_id="GRP-CONF-2",
            status=IncidentStatus.OPEN,
            severity=IncidentSeverity.MAJOR,
            priority=IncidentPriority.P2,
            title="Test",
            description="Test",
            alarm_ids=(),
            affected_node_ids=(),
            suspected_cause_type=RootCauseType.CELL_OUTAGE,
            suspected_target_id="CELL-01",
            suspected_target_type=TargetType.NODE,
            rca_confidence_score=0.925,
            rca_hypotheses=(),
            rca_evidence=(),
            created_at=t0,
            ack_deadline=t0 + timedelta(minutes=30),
            resolve_deadline=t0 + timedelta(hours=4),
        )
        assert inc.rca_confidence_score == 0.925

    @pytest.mark.parametrize("invalid_score", [-0.1, 1.1, float("nan"), float("inf"), -float("inf"), True, False])
    def test_invalid_confidence_scores_rejected(self, invalid_score: Any) -> None:
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(InvalidIncidentDataError):
            Incident(
                incident_id="INC-CONF-BAD",
                correlation_group_id="GRP-CONF-BAD",
                status=IncidentStatus.OPEN,
                severity=IncidentSeverity.MAJOR,
                priority=IncidentPriority.P2,
                title="Test",
                description="Test",
                alarm_ids=(),
                affected_node_ids=(),
                suspected_cause_type=RootCauseType.CELL_OUTAGE,
                suspected_target_id="CELL-01",
                suspected_target_type=TargetType.NODE,
                rca_confidence_score=invalid_score,
                rca_hypotheses=(),
                rca_evidence=(),
                created_at=t0,
                ack_deadline=t0 + timedelta(minutes=30),
                resolve_deadline=t0 + timedelta(hours=4),
            )


# ===========================================================================
# 2. Operational Severity Policy Tests
# ===========================================================================

class TestOperationalSeverityPolicy:
    """Test policy mapping operational impact to incident severity and priority."""

    def test_critical_alarm_on_core_or_aggregation_is_critical(self) -> None:
        policy = OperationalSeverityPolicy()
        alarm = make_test_alarm("alm-c", "AGG-01", Severity.CRITICAL)
        group = make_test_group(anchor_id="AGG-01", tier=NodeType.AGGREGATION, alarms=[alarm])

        severity = policy.evaluate(group)
        assert severity == IncidentSeverity.CRITICAL
        assert policy.get_priority(severity) == IncidentPriority.P1

    def test_critical_alarm_wide_blast_radius_is_critical(self) -> None:
        policy = OperationalSeverityPolicy(critical_node_count_threshold=5)
        # 5 affected cell nodes with a CRITICAL alarm
        alarms = [make_test_alarm(f"alm-{i}", f"CELL-0{i}", Severity.CRITICAL if i == 1 else Severity.WARNING) for i in range(1, 6)]
        group = make_test_group(anchor_id="SITE-01", tier=NodeType.SITE, alarms=alarms, node_ids=[f"CELL-0{i}" for i in range(1, 6)])

        severity = policy.evaluate(group)
        assert severity == IncidentSeverity.CRITICAL

    def test_critical_alarm_on_access_site_is_major(self) -> None:
        policy = OperationalSeverityPolicy()
        alarm = make_test_alarm("alm-c", "CELL-01", Severity.CRITICAL)
        group = make_test_group(anchor_id="SITE-01", tier=NodeType.SITE, alarms=[alarm], node_ids=["CELL-01"])

        severity = policy.evaluate(group)
        assert severity == IncidentSeverity.MAJOR
        assert policy.get_priority(severity) == IncidentPriority.P2

    def test_major_alarm_on_aggregation_is_major(self) -> None:
        policy = OperationalSeverityPolicy()
        alarm = make_test_alarm("alm-m", "AGG-01", Severity.MAJOR)
        group = make_test_group(anchor_id="AGG-01", tier=NodeType.AGGREGATION, alarms=[alarm])

        severity = policy.evaluate(group)
        assert severity == IncidentSeverity.MAJOR

    def test_major_alarm_on_cell_is_warning(self) -> None:
        policy = OperationalSeverityPolicy()
        alarm = make_test_alarm("alm-m", "CELL-01", Severity.MAJOR)
        group = make_test_group(anchor_id="CELL-01", tier=NodeType.CELL, alarms=[alarm], node_ids=["CELL-01"])

        severity = policy.evaluate(group)
        assert severity == IncidentSeverity.WARNING
        assert policy.get_priority(severity) == IncidentPriority.P3

    def test_isolated_warning_alarm_is_minor(self) -> None:
        policy = OperationalSeverityPolicy()
        alarm = make_test_alarm("alm-w", "CELL-01", Severity.WARNING)
        group = make_test_group(anchor_id="CELL-01", tier=NodeType.CELL, alarms=[alarm], node_ids=["CELL-01"])

        severity = policy.evaluate(group)
        assert severity == IncidentSeverity.MINOR
        assert policy.get_priority(severity) == IncidentPriority.P4


# ===========================================================================
# 3. SLA Management and Calculation Tests
# ===========================================================================

class TestSLAManagement:
    """Test SLA calculation, deadlines, boundary conditions, and breach detection."""

    def test_default_deadlines_for_each_severity(self) -> None:
        calc = SLACalculator()
        t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

        # CRITICAL: 15m ack, 60m resolve
        crit = calc.calculate_deadlines(t0, IncidentSeverity.CRITICAL)
        assert crit.ack_deadline == t0 + timedelta(minutes=15)
        assert crit.resolve_deadline == t0 + timedelta(minutes=60)

        # MAJOR: 30m ack, 240m resolve
        major = calc.calculate_deadlines(t0, IncidentSeverity.MAJOR)
        assert major.ack_deadline == t0 + timedelta(minutes=30)
        assert major.resolve_deadline == t0 + timedelta(hours=4)

        # WARNING: 60m ack, 720m resolve
        warn = calc.calculate_deadlines(t0, IncidentSeverity.WARNING)
        assert warn.ack_deadline == t0 + timedelta(minutes=60)
        assert warn.resolve_deadline == t0 + timedelta(hours=12)

        # MINOR: 120m ack, 1440m resolve
        minor = calc.calculate_deadlines(t0, IncidentSeverity.MINOR)
        assert minor.ack_deadline == t0 + timedelta(hours=2)
        assert minor.resolve_deadline == t0 + timedelta(hours=24)

    def test_sla_breach_detection_boundary_and_active(self) -> None:
        calc = SLACalculator()
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        deadlines = calc.calculate_deadlines(t0, IncidentSeverity.CRITICAL)

        # Case 1: Active incident evaluated before ack deadline (14m elapsed) -> not breached
        s1 = calc.evaluate_sla(
            created_at=t0,
            ack_deadline=deadlines.ack_deadline,
            resolve_deadline=deadlines.resolve_deadline,
            acknowledged_at=None,
            resolved_at=None,
            evaluation_timestamp=t0 + timedelta(minutes=14),
        )
        assert not s1.ack_breached
        assert not s1.resolve_breached
        assert s1.ack_time_seconds is None

        # Case 2: Boundary check: Exactly on ack deadline (15m) -> not breached
        s2 = calc.evaluate_sla(
            created_at=t0,
            ack_deadline=deadlines.ack_deadline,
            resolve_deadline=deadlines.resolve_deadline,
            acknowledged_at=None,
            resolved_at=None,
            evaluation_timestamp=deadlines.ack_deadline,
        )
        assert not s2.ack_breached

        # Case 3: Just past ack deadline (15m 1s) without ack -> breached!
        s3 = calc.evaluate_sla(
            created_at=t0,
            ack_deadline=deadlines.ack_deadline,
            resolve_deadline=deadlines.resolve_deadline,
            acknowledged_at=None,
            resolved_at=None,
            evaluation_timestamp=deadlines.ack_deadline + timedelta(seconds=1),
        )
        assert s3.ack_breached
        assert not s3.resolve_breached

    def test_sla_breach_status_freezes_after_resolution(self) -> None:
        calc = SLACalculator()
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        deadlines = calc.calculate_deadlines(t0, IncidentSeverity.CRITICAL)

        # Acknowledged in 10m (healthy), resolved in 50m (healthy, <= 60m)
        t_ack = t0 + timedelta(minutes=10)
        t_res = t0 + timedelta(minutes=50)

        # Evaluated at time of resolution
        s_res = calc.evaluate_sla(
            created_at=t0,
            ack_deadline=deadlines.ack_deadline,
            resolve_deadline=deadlines.resolve_deadline,
            acknowledged_at=t_ack,
            resolved_at=t_res,
            evaluation_timestamp=t_res,
        )
        assert not s_res.ack_breached
        assert not s_res.resolve_breached
        assert s_res.ack_time_seconds == 600.0
        assert s_res.resolve_time_seconds == 3000.0

        # Evaluated 5 days later: does NOT retroactively breach resolution SLA!
        s_future = calc.evaluate_sla(
            created_at=t0,
            ack_deadline=deadlines.ack_deadline,
            resolve_deadline=deadlines.resolve_deadline,
            acknowledged_at=t_ack,
            resolved_at=t_res,
            evaluation_timestamp=t0 + timedelta(days=5),
        )
        assert not s_future.ack_breached
        assert not s_future.resolve_breached

    def test_sla_target_validation(self) -> None:
        # Valid positive finite targets
        target = SLATarget(ack_target_minutes=15, resolve_target_minutes=60.5)
        assert target.ack_target_minutes == 15.0
        assert target.resolve_target_minutes == 60.5

        # Rejection of zero
        with pytest.raises(SLABreachCalculationError):
            SLATarget(ack_target_minutes=0.0, resolve_target_minutes=60.0)
        with pytest.raises(SLABreachCalculationError):
            SLATarget(ack_target_minutes=15.0, resolve_target_minutes=0.0)

        # Rejection of negative values
        with pytest.raises(SLABreachCalculationError):
            SLATarget(ack_target_minutes=-5.0, resolve_target_minutes=60.0)
        with pytest.raises(SLABreachCalculationError):
            SLATarget(ack_target_minutes=15.0, resolve_target_minutes=-10.0)

        # Rejection of booleans
        with pytest.raises(SLABreachCalculationError):
            SLATarget(ack_target_minutes=True, resolve_target_minutes=60.0)
        with pytest.raises(SLABreachCalculationError):
            SLATarget(ack_target_minutes=15.0, resolve_target_minutes=False)

        # Rejection of NaN
        with pytest.raises(SLABreachCalculationError):
            SLATarget(ack_target_minutes=float("nan"), resolve_target_minutes=60.0)
        with pytest.raises(SLABreachCalculationError):
            SLATarget(ack_target_minutes=15.0, resolve_target_minutes=float("nan"))

        # Rejection of positive and negative infinity
        with pytest.raises(SLABreachCalculationError):
            SLATarget(ack_target_minutes=float("inf"), resolve_target_minutes=60.0)
        with pytest.raises(SLABreachCalculationError):
            SLATarget(ack_target_minutes=15.0, resolve_target_minutes=float("inf"))
        with pytest.raises(SLABreachCalculationError):
            SLATarget(ack_target_minutes=float("-inf"), resolve_target_minutes=60.0)

        # Rejection when resolve is less than ack
        with pytest.raises(SLABreachCalculationError):
            SLATarget(ack_target_minutes=120.0, resolve_target_minutes=60.0)


# ===========================================================================
# 4. Operational Metrics Tests
# ===========================================================================

class TestIncidentMetrics:
    """Test operational incident metrics calculation: MTTA, MTTR, MTTD, SLA breach counts."""

    def test_metrics_empty_collection(self) -> None:
        calc = MetricsCalculator()
        report = calc.compute_metrics(incidents=[], as_of=datetime(2026, 1, 1, tzinfo=timezone.utc))

        assert report.total_incidents == 0
        assert report.open_incident_count == 0
        assert report.mtta_seconds is None
        assert report.mttr_seconds is None
        assert report.mttd_seconds is None
        assert report.ack_sla_breached_count == 0
        assert report.resolve_sla_breached_count == 0

    def test_mtta_and_mttr_averaging(self) -> None:
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        calc = MetricsCalculator()

        # Incident 1: Acknowledged in 10m (600s), Resolved in 40m (2400s)
        inc1 = Incident(
            incident_id="INC-1",
            correlation_group_id="GRP-1",
            status=IncidentStatus.RESOLVED,
            severity=IncidentSeverity.MAJOR,
            priority=IncidentPriority.P2,
            title="Inc 1",
            description="",
            alarm_ids=(),
            affected_node_ids=(),
            suspected_cause_type=None,
            suspected_target_id=None,
            suspected_target_type=None,
            rca_confidence_score=None,
            rca_hypotheses=(),
            rca_evidence=(),
            created_at=t0,
            ack_deadline=t0 + timedelta(minutes=30),
            resolve_deadline=t0 + timedelta(hours=4),
            acknowledged_at=t0 + timedelta(minutes=10),
            acknowledged_by="alice",
            resolved_at=t0 + timedelta(minutes=40),
            resolved_by="bob",
        )

        # Incident 2: Acknowledged in 20m (1200s), still OPEN (unresolved)
        inc2 = Incident(
            incident_id="INC-2",
            correlation_group_id="GRP-2",
            status=IncidentStatus.ACKNOWLEDGED,
            severity=IncidentSeverity.MAJOR,
            priority=IncidentPriority.P2,
            title="Inc 2",
            description="",
            alarm_ids=(),
            affected_node_ids=(),
            suspected_cause_type=None,
            suspected_target_id=None,
            suspected_target_type=None,
            rca_confidence_score=None,
            rca_hypotheses=(),
            rca_evidence=(),
            created_at=t0,
            ack_deadline=t0 + timedelta(minutes=30),
            resolve_deadline=t0 + timedelta(hours=4),
            acknowledged_at=t0 + timedelta(minutes=20),
            acknowledged_by="carol",
        )

        # Incident 3: Fresh OPEN incident, not yet acknowledged
        inc3 = Incident(
            incident_id="INC-3",
            correlation_group_id="GRP-3",
            status=IncidentStatus.OPEN,
            severity=IncidentSeverity.CRITICAL,
            priority=IncidentPriority.P1,
            title="Inc 3",
            description="",
            alarm_ids=(),
            affected_node_ids=(),
            suspected_cause_type=None,
            suspected_target_id=None,
            suspected_target_type=None,
            rca_confidence_score=None,
            rca_hypotheses=(),
            rca_evidence=(),
            created_at=t0,
            ack_deadline=t0 + timedelta(minutes=15),
            resolve_deadline=t0 + timedelta(hours=1),
        )

        report = calc.compute_metrics(
            incidents=[inc1, inc2, inc3],
            as_of=t0 + timedelta(minutes=25),
            mttd_seconds=42.5,
        )

        assert report.total_incidents == 3
        # inc2 is ACKNOWLEDGED and inc3 is OPEN -> 2 open incidents
        assert report.open_incident_count == 2

        # MTTA: (600s + 1200s) / 2 = 900.0s
        assert report.mtta_seconds == 900.0

        # MTTR: only inc1 is resolved -> 2400.0s (inc2 and inc3 strictly excluded)
        assert report.mttr_seconds == 2400.0

        # MTTD derived from explicit evaluation input
        assert report.mttd_seconds == 42.5

        # inc3 ack_deadline is 15m, evaluation time is 25m -> ack SLA breached!
        assert report.ack_sla_breached_count == 1
        assert report.resolve_sla_breached_count == 0


# ===========================================================================
# 5. Incident Service & Idempotency Tests
# ===========================================================================

from sqlalchemy import create_engine
from nexus.incidents.repository import Base, IncidentRepository
from nexus.incidents.service import IncidentService


class TestIncidentServiceDomain:
    """Test incident creation, idempotency, timeline tracking, and lifecycle via service."""

    @pytest.fixture
    def service(self) -> IncidentService:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        repo = IncidentRepository.from_engine(engine)
        return IncidentService(repository=repo)

    def test_create_incident_from_analysis(self, service: IncidentService) -> None:
        group = make_test_group("GRP-SRV-1")
        rca = make_test_rca_result("GRP-SRV-1", cause_type=RootCauseType.CELL_OUTAGE, confidence=0.88)

        t_create = datetime(2026, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
        inc = service.create_incident(
            correlation_group=group,
            rca_result=rca,
            actor="SYSTEM_AGENT",
            creation_timestamp=t_create,
        )

        assert inc.correlation_group_id == "GRP-SRV-1"
        assert inc.status == IncidentStatus.OPEN
        assert inc.suspected_cause_type == RootCauseType.CELL_OUTAGE
        assert inc.suspected_target_id == "CELL-01"
        assert inc.rca_confidence_score == 0.88
        assert len(inc.timeline) == 1
        assert inc.timeline[0].event_type == TimelineEventType.CREATED
        assert inc.timeline[0].actor == "SYSTEM_AGENT"
        assert inc.created_at == t_create

    def test_create_incident_with_unknown_rca_succeeds(self, service: IncidentService) -> None:
        group = make_test_group("GRP-UNKNOWN-RCA")
        rca = make_test_rca_result("GRP-UNKNOWN-RCA", cause_type=RootCauseType.UNKNOWN)

        inc = service.create_incident(correlation_group=group, rca_result=rca)
        assert inc.correlation_group_id == "GRP-UNKNOWN-RCA"
        assert inc.status == IncidentStatus.OPEN
        assert inc.suspected_cause_type == RootCauseType.UNKNOWN
        assert inc.rca_confidence_score is None
        assert "Unresolved network anomaly" in inc.title

    def test_duplicate_incident_creation_prevented(self, service: IncidentService) -> None:
        group = make_test_group("GRP-DUP-1")
        rca = make_test_rca_result("GRP-DUP-1")

        service.create_incident(correlation_group=group, rca_result=rca)

        with pytest.raises(DuplicateIncidentError) as exc_info:
            service.create_incident(correlation_group=group, rca_result=rca)
        assert "GRP-DUP-1" in str(exc_info.value)

    def test_inputs_are_not_mutated(self, service: IncidentService) -> None:
        group = make_test_group("GRP-IMMUTABLE-1")
        rca = make_test_rca_result("GRP-IMMUTABLE-1")

        orig_alarms = tuple(group.alarms)
        orig_hypotheses = tuple(rca.hypotheses)

        service.create_incident(correlation_group=group, rca_result=rca)

        assert group.alarms == orig_alarms
        assert rca.hypotheses == orig_hypotheses

    def test_acknowledge_and_resolve_creates_atomic_timeline(self, service: IncidentService) -> None:
        group = make_test_group("GRP-TIMELINE-1")
        rca = make_test_rca_result("GRP-TIMELINE-1")

        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(minutes=5)
        t2 = t0 + timedelta(minutes=25)

        inc = service.create_incident(correlation_group=group, rca_result=rca, creation_timestamp=t0)

        acked = service.acknowledge_incident(inc.incident_id, actor="operator_alice", timestamp=t1)
        assert acked.status == IncidentStatus.ACKNOWLEDGED
        assert acked.acknowledged_by == "operator_alice"
        assert acked.acknowledged_at == t1

        resolved = service.resolve_incident(
            inc.incident_id, actor="operator_bob", timestamp=t2, notes="Fixed power feed"
        )
        assert resolved.status == IncidentStatus.RESOLVED
        assert resolved.resolved_by == "operator_bob"
        assert resolved.resolved_at == t2

        timeline = service.get_timeline(inc.incident_id)
        assert len(timeline) == 3
        assert [e.event_type for e in timeline] == [
            TimelineEventType.CREATED,
            TimelineEventType.ACKNOWLEDGED,
            TimelineEventType.RESOLVED,
        ]
        assert timeline[1].actor == "operator_alice"
        assert timeline[2].actor == "operator_bob"
        assert timeline[2].details.get("resolution_notes") == "Fixed power feed"

    def test_invalid_transition_creates_no_timeline_event(self, service: IncidentService) -> None:
        group = make_test_group("GRP-NO-TIMELINE-POLLUTION")
        rca = make_test_rca_result("GRP-NO-TIMELINE-POLLUTION")

        inc = service.create_incident(correlation_group=group, rca_result=rca)
        service.resolve_incident(inc.incident_id, actor="operator1")

        with pytest.raises(InvalidStateTransitionError):
            service.acknowledge_incident(inc.incident_id, actor="operator2")

        timeline = service.get_timeline(inc.incident_id)
        assert len(timeline) == 2  # Only CREATED and RESOLVED, no failed ACK event
