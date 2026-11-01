"""Pydantic schemas for Alarm REST API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class AlarmResponse(BaseModel):
    """Schema representing an authentic network alarm record."""

    alarm_id: str = Field(..., description="Unique alarm identifier")
    node_id: str = Field(..., description="Network node emitting the alarm")
    rule_id: str = Field(..., description="Detector rule or model identifier")
    metric_name: str = Field(..., description="Monitored metric name")
    source: str = Field(..., description="Originating detector mechanism (THRESHOLD, STATISTICAL_MEDIAN, STATISTICAL_EWMA)")
    severity: str = Field(..., description="Severity level (WARNING, MAJOR, CRITICAL)")
    current_value: float = Field(..., description="Observed metric value at last evaluation")
    threshold: Optional[float] = Field(None, description="Configured violation threshold or baseline")
    first_seen: datetime = Field(..., description="UTC timestamp of first observation")
    last_seen: datetime = Field(..., description="UTC timestamp of latest observation")
    observation_count: int = Field(..., description="Number of consecutive evaluation cycles persisted")
    status: str = Field(..., description="Lifecycle status (ACTIVE, CLEARED)")
    cleared_at: Optional[datetime] = Field(None, description="UTC timestamp when alarm cleared or null")
    description: str = Field("", description="Human-readable condition description")
    evidence: dict[str, Any] = Field(default_factory=dict, description="Diagnostic evidence map")


class AlarmListResponse(BaseModel):
    """Paginated list envelope for alarm records."""

    items: list[AlarmResponse] = Field(..., description="List of alarms")
    total: int = Field(..., description="Total matching alarms count")
    limit: int = Field(..., description="Pagination limit")
    offset: int = Field(..., description="Pagination offset")


class DetectionRuleResponse(BaseModel):
    """Schema representing an authoritative configured threshold detection rule."""

    rule_id: str = Field(..., description="Unique rule identifier")
    metric_name: str = Field(..., description="Target KPI metric name")
    operator: str = Field(..., description="Comparison operator (GT, GTE, LT, LTE)")
    threshold: float = Field(..., description="Violation boundary threshold")
    clear_threshold: Optional[float] = Field(None, description="Recovery boundary threshold or null")
    severity: str = Field(..., description="Alarm severity level (WARNING, MAJOR, CRITICAL)")
    node_types: Optional[list[str]] = Field(None, description="Applicable node types or null if applies to all")
    description: str = Field("", description="Human-readable rule description")
    enabled: bool = Field(True, description="Whether the rule is actively evaluated")


class DetectionRuleListResponse(BaseModel):
    """List envelope for configured threshold detection rules."""

    items: list[DetectionRuleResponse] = Field(..., description="Configured rules")
    total: int = Field(..., description="Total configured rules count")

