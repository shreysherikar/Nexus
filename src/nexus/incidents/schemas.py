"""Pydantic schemas for API request and response validation."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Mapping, Optional, Sequence
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nexus.detection.models import AlarmStatus, DetectionSource, Severity
from nexus.incidents.enums import IncidentPriority, IncidentSeverity, IncidentStatus
from nexus.rca.models import RootCauseType, TargetType
from nexus.topology.enums import NodeType


def _validate_numeric(v: Any, field_name: str, min_val: Optional[float] = None, max_val: Optional[float] = None) -> Optional[float]:
    """Validate numeric values, strictly rejecting booleans, NaN, and infinity."""
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{field_name} must be numeric, got {type(v).__name__}")
    f = float(v)
    if not math.isfinite(f):
        raise ValueError(f"{field_name} must be finite, got {f}")
    if min_val is not None and f < min_val:
        raise ValueError(f"{field_name} must be >= {min_val}, got {f}")
    if max_val is not None and f > max_val:
        raise ValueError(f"{field_name} must be <= {max_val}, got {f}")
    return f


class CorrelatedAlarmDTO(BaseModel):
    """Validated representation of an actual alarm participating in correlation."""

    model_config = ConfigDict(extra="forbid")

    alarm_id: str = Field(..., min_length=1, description="Unique alarm identifier")
    node_id: str = Field(..., min_length=1, description="Network node identifier")
    rule_id: str = Field(..., min_length=1, description="Rule triggering the alarm")
    metric_name: str = Field(..., min_length=1, description="Metric name violating threshold")
    source: DetectionSource = Field(..., description="Detection source mechanism")
    severity: Severity = Field(..., description="Observed alarm severity (CRITICAL, MAJOR, WARNING)")
    current_value: float = Field(..., description="Observed metric value")
    threshold: Optional[float] = Field(None, description="Violation threshold")
    first_seen: datetime = Field(..., description="Initial detection timestamp")
    last_seen: datetime = Field(..., description="Most recent observation timestamp")
    observation_count: int = Field(..., ge=1, description="Consecutive observation cycle count")
    status: AlarmStatus = Field(..., description="Alarm lifecycle state (ACTIVE or CLEARED)")

    @field_validator("current_value", mode="before")
    @classmethod
    def validate_current_value(cls, v: Any) -> float:
        val = _validate_numeric(v, "current_value")
        assert val is not None
        return val

    @field_validator("threshold", mode="before")
    @classmethod
    def validate_threshold(cls, v: Any) -> Optional[float]:
        return _validate_numeric(v, "threshold")

    @model_validator(mode="after")
    def validate_timestamps(self) -> CorrelatedAlarmDTO:
        if self.first_seen > self.last_seen:
            raise ValueError("first_seen cannot be later than last_seen")
        return self


class EvidenceItemDTO(BaseModel):
    """Validated representation of diagnostic evidence."""

    model_config = ConfigDict(extra="forbid")

    source_node_id: str = Field(..., min_length=1)
    metric_name: str = Field(..., min_length=1)
    observed_value: float
    threshold_or_baseline: Optional[float] = None
    reasoning: str = Field(..., min_length=1)
    severity: Optional[Severity] = None
    evidence_source: str = Field("ALARM", pattern="^(ALARM|SNAPSHOT|TOPOLOGY)$")

    @field_validator("observed_value", mode="before")
    @classmethod
    def validate_observed_val(cls, v: Any) -> float:
        val = _validate_numeric(v, "observed_value")
        assert val is not None
        return val

    @field_validator("threshold_or_baseline", mode="before")
    @classmethod
    def validate_baseline(cls, v: Any) -> Optional[float]:
        return _validate_numeric(v, "threshold_or_baseline")


class HypothesisDTO(BaseModel):
    """Validated diagnostic hypothesis representation."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(..., min_length=1)
    cause_type: RootCauseType
    target_id: str = Field(..., min_length=1)
    target_type: TargetType
    confidence_score: Optional[float] = None
    explanation: str = Field(..., min_length=1)
    evidence_items: list[EvidenceItemDTO] = Field(default_factory=list)

    @field_validator("confidence_score", mode="before")
    @classmethod
    def validate_confidence(cls, v: Any) -> Optional[float]:
        return _validate_numeric(v, "confidence_score", min_val=0.0, max_val=1.0)


class CreateIncidentRequest(BaseModel):
    """Validated payload for creating an incident from actual correlation and RCA results."""

    model_config = ConfigDict(extra="forbid")

    correlation_group_id: str = Field(..., min_length=1, description="Correlation group identifier")
    anchor_node_id: Optional[str] = Field(None, description="Anchor node identifier")
    root_cause_tier: Optional[NodeType] = Field(None, description="Anchor node tier")
    alarms: list[CorrelatedAlarmDTO] = Field(..., min_length=1, description="Correlated alarms with real attributes")
    time_window_start: datetime = Field(..., description="Start of correlation time window")
    time_window_end: datetime = Field(..., description="End of correlation time window")
    correlation_reason: str = Field("", description="Reason for correlation")

    # RCA Hypothesis fields
    suspected_cause_type: Optional[RootCauseType] = Field(
        None, description="Diagnosed root cause type (or UNKNOWN)"
    )
    suspected_target_id: Optional[str] = Field(None, description="Diagnosed target identifier")
    suspected_target_type: Optional[TargetType] = Field(None, description="Diagnosed target type")
    rca_confidence_score: Optional[float] = Field(None, description="Confidence score in [0.0, 1.0]")
    hypotheses: list[HypothesisDTO] = Field(default_factory=list)
    evidence_items: list[EvidenceItemDTO] = Field(default_factory=list)
    created_by: str = Field("SYSTEM", min_length=1, description="Actor creating the incident")

    @field_validator("rca_confidence_score", mode="before")
    @classmethod
    def validate_rca_confidence(cls, v: Any) -> Optional[float]:
        return _validate_numeric(v, "rca_confidence_score", min_val=0.0, max_val=1.0)

    @model_validator(mode="after")
    def validate_consistency(self) -> CreateIncidentRequest:
        if self.time_window_start > self.time_window_end:
            raise ValueError("time_window_start cannot be later than time_window_end")

        # Cause/Target consistency validation
        if self.suspected_cause_type is not None and self.suspected_cause_type != RootCauseType.UNKNOWN:
            if not self.suspected_target_id:
                raise ValueError("suspected_target_id must be provided when suspected_cause_type is specified")
            if not self.suspected_target_type or self.suspected_target_type == TargetType.UNKNOWN:
                raise ValueError("suspected_target_type (NODE or TRANSPORT_LINK) must be specified for known causes")

        return self


class AcknowledgeRequest(BaseModel):
    """Payload to acknowledge an incident."""

    actor: str = Field(..., min_length=1, max_length=128, description="Operator or service name")


class ResolveRequest(BaseModel):
    """Payload to resolve an incident."""

    actor: str = Field(..., min_length=1, max_length=128, description="Operator or service name")
    notes: Optional[str] = Field(None, max_length=2000, description="Optional resolution summary notes")


class TimelineEventResponse(BaseModel):
    """Timeline event representation in responses."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    incident_id: str
    event_type: str
    timestamp: datetime
    actor: str
    actor_type: str
    details: dict[str, Any]


class SLABreachStatusResponse(BaseModel):
    """SLA compliance and deadline metrics."""

    model_config = ConfigDict(from_attributes=True)

    ack_breached: bool
    resolve_breached: bool
    ack_time_seconds: Optional[float] = None
    resolve_time_seconds: Optional[float] = None
    evaluation_timestamp: datetime


class IncidentResponse(BaseModel):
    """Full incident details representation."""

    model_config = ConfigDict(from_attributes=True)

    incident_id: str
    correlation_group_id: str
    status: str
    severity: str
    priority: str
    title: str
    description: str
    alarm_ids: list[str]
    affected_node_ids: list[str]
    suspected_cause_type: Optional[str] = None
    suspected_target_id: Optional[str] = None
    suspected_target_type: Optional[str] = None
    rca_confidence_score: Optional[float] = None
    rca_hypotheses: list[dict[str, Any]]
    rca_evidence: list[dict[str, Any]]
    created_at: datetime
    ack_deadline: datetime
    resolve_deadline: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    sla_status: Optional[SLABreachStatusResponse] = None


class IncidentListResponse(BaseModel):
    """Paginated collection of incidents."""

    items: list[IncidentResponse]
    total: int
    limit: int
    offset: int


class IncidentMetricsResponse(BaseModel):
    """Operational incident and SLA metrics response."""

    total_incidents: int
    open_incident_count: int
    incidents_by_status: dict[str, int]
    incidents_by_severity: dict[str, int]
    mtta_seconds: Optional[float] = None
    mttr_seconds: Optional[float] = None
    mttd_seconds: Optional[float] = None
    total_incidents_evaluated: int
    compliant_incident_count: int
    breached_incident_count: int
    ack_sla_breached_count: int
    resolve_sla_breached_count: int
    sla_compliance_pct: Optional[float] = None
    as_of: datetime


class ErrorResponse(BaseModel):
    """Standardized error response."""

    detail: str
    error_code: str
