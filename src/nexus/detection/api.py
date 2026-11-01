"""FastAPI REST router for network alarms."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from nexus.detection.models import AlarmStatus, Severity
from nexus.detection.schemas import (
    AlarmListResponse,
    AlarmResponse,
    DetectionRuleListResponse,
    DetectionRuleResponse,
)
from nexus.detection.service import AlarmService, get_alarm_service

router = APIRouter(prefix="/api/v1", tags=["alarms"])


@router.get(
    "/alarms",
    response_model=AlarmListResponse,
    summary="Query active and cleared alarms",
    description="Retrieve actual alarm records from the alarm manager with filtering and pagination.",
)
def get_alarms(
    node_id: Optional[str] = Query(None, description="Filter by node ID"),
    severity: Optional[str] = Query(None, description="Filter by severity (WARNING, MAJOR, CRITICAL)"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (ACTIVE, CLEARED)"),
    limit: int = Query(50, ge=1, le=100, description="Page limit (1-100)"),
    offset: int = Query(0, ge=0, description="Page offset (>=0)"),
    service: AlarmService = Depends(get_alarm_service),
) -> AlarmListResponse:
    """Query authentic alarm records."""
    parsed_severity: Optional[Severity] = None
    if severity is not None:
        try:
            parsed_severity = Severity(severity.upper().strip())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid severity '{severity}'. Expected one of: {[s.value for s in Severity]}",
            )

    parsed_status: Optional[AlarmStatus] = None
    if status_filter is not None:
        try:
            parsed_status = AlarmStatus(status_filter.upper().strip())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status '{status_filter}'. Expected one of: {[s.value for s in AlarmStatus]}",
            )

    alarms, total = service.get_alarms(
        node_id=node_id,
        severity=parsed_severity,
        status=parsed_status,
        limit=limit,
        offset=offset,
    )

    items: list[AlarmResponse] = [
        AlarmResponse(
            alarm_id=a.alarm_id,
            node_id=a.node_id,
            rule_id=a.rule_id,
            metric_name=a.metric_name,
            source=a.source.value,
            severity=a.severity.value,
            current_value=a.current_value,
            threshold=a.threshold,
            first_seen=a.first_seen,
            last_seen=a.last_seen,
            observation_count=a.observation_count,
            status=a.status.value,
            cleared_at=a.cleared_at,
            description=a.description,
            evidence=dict(a.evidence),
        )
        for a in alarms
    ]

    return AlarmListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/alarms/{alarm_id}",
    response_model=AlarmResponse,
    summary="Get alarm by ID",
    description="Retrieve a single authentic alarm record by its unique identifier.",
)
def get_alarm_by_id(
    alarm_id: str,
    service: AlarmService = Depends(get_alarm_service),
) -> AlarmResponse:
    """Retrieve details for a specific alarm record."""
    alarm = service.get_alarm_by_id(alarm_id)
    if alarm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alarm '{alarm_id}' not found",
        )

    return AlarmResponse(
        alarm_id=alarm.alarm_id,
        node_id=alarm.node_id,
        rule_id=alarm.rule_id,
        metric_name=alarm.metric_name,
        source=alarm.source.value,
        severity=alarm.severity.value,
        current_value=alarm.current_value,
        threshold=alarm.threshold,
        first_seen=alarm.first_seen,
        last_seen=alarm.last_seen,
        observation_count=alarm.observation_count,
        status=alarm.status.value,
        cleared_at=alarm.cleared_at,
        description=alarm.description,
        evidence=dict(alarm.evidence),
    )


@router.get(
    "/detection/rules",
    response_model=DetectionRuleListResponse,
    summary="List configured threshold detection rules",
    description="Retrieve authoritative configured threshold rules used for anomaly and alarm detection.",
)
def get_detection_rules(
    service: AlarmService = Depends(get_alarm_service),
) -> DetectionRuleListResponse:
    """Retrieve all authoritative configured threshold detection rules."""
    rules = service.get_rules()
    items = [
        DetectionRuleResponse(
            rule_id=r.rule_id,
            metric_name=r.metric_name,
            operator=r.operator.value,
            threshold=r.threshold,
            clear_threshold=r.clear_threshold,
            severity=r.severity.value,
            node_types=sorted([nt.value for nt in r.node_types]) if r.node_types is not None else None,
            description=r.description,
            enabled=r.enabled,
        )
        for r in rules
    ]
    return DetectionRuleListResponse(items=items, total=len(items))

