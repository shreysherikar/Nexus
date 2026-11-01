"""FastAPI REST API router and application for NEXUS Incident Management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from typing import Any, Mapping, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from nexus.correlation.models import CorrelationGroup
from nexus.detection.models import Alarm, AlarmStatus, DetectionSource, Severity
from nexus.incidents.enums import (
    ActorType,
    IncidentPriority,
    IncidentSeverity,
    IncidentStatus,
)
from nexus.incidents.exceptions import (
    DuplicateIncidentError,
    IncidentNotFoundError,
    InvalidIncidentDataError,
    InvalidStateTransitionError,
)
from nexus.incidents.models import Incident, TimelineEvent
from nexus.incidents.repository import IncidentRepository, create_engine
from nexus.incidents.schemas import (
    AcknowledgeRequest,
    CorrelatedAlarmDTO,
    CreateIncidentRequest,
    ErrorResponse,
    EvidenceItemDTO,
    HypothesisDTO,
    IncidentListResponse,
    IncidentMetricsResponse,
    IncidentResponse,
    ResolveRequest,
    SLABreachStatusResponse,
    TimelineEventResponse,
)
from nexus.incidents.service import IncidentService
from nexus.rca.models import (
    EvidenceItem,
    RCAResult,
    RootCauseHypothesis,
    RootCauseType,
    TargetType,
)
from nexus.detection.api import router as alarm_router
from nexus.detection.service import get_alarm_service
from nexus.events.api import router as websocket_router
from nexus.events.broadcaster import get_broadcaster
from nexus.telemetry.api import router as telemetry_router
from nexus.telemetry.orchestrator import get_telemetry_pipeline
from nexus.telemetry.store import get_telemetry_store
from nexus.topology import NodeStatus, NodeType, Topology
from nexus.topology.api import get_topology_registry, router as topology_router


def get_topology() -> Topology:
    """Retrieve or initialize the trusted reference topology."""
    return get_topology_registry()


def resolve_node_tier(node_id: Optional[str], topo: Topology) -> Optional[NodeType]:
    """Resolve a node's topological tier from trusted topology source."""
    if not node_id:
        return None
    try:
        node = topo.get_node(node_id)
        return node.node_type
    except Exception:
        if node_id.startswith("CORE"):
            return NodeType.CORE
        if node_id.startswith("AGG"):
            return NodeType.AGGREGATION
        if node_id.startswith("SITE"):
            return NodeType.SITE
        if node_id.startswith("CELL"):
            return NodeType.CELL
        return None


def _incident_to_response(
    incident: Incident, evaluation_timestamp: Optional[datetime] = None
) -> IncidentResponse:
    sla = incident.get_sla_status(evaluation_timestamp=evaluation_timestamp)
    sla_resp = SLABreachStatusResponse(
        ack_breached=sla.ack_breached,
        resolve_breached=sla.resolve_breached,
        ack_time_seconds=sla.ack_time_seconds,
        resolve_time_seconds=sla.resolve_time_seconds,
        evaluation_timestamp=sla.evaluation_timestamp,
    )

    return IncidentResponse(
        incident_id=incident.incident_id,
        correlation_group_id=incident.correlation_group_id,
        status=incident.status.value,
        severity=incident.severity.value,
        priority=incident.priority.value,
        title=incident.title,
        description=incident.description,
        alarm_ids=list(incident.alarm_ids),
        affected_node_ids=list(incident.affected_node_ids),
        suspected_cause_type=incident.suspected_cause_type.value
        if incident.suspected_cause_type
        else None,
        suspected_target_id=incident.suspected_target_id,
        suspected_target_type=incident.suspected_target_type.value
        if incident.suspected_target_type
        else None,
        rca_confidence_score=incident.rca_confidence_score,
        rca_hypotheses=[dict(h) for h in incident.rca_hypotheses],
        rca_evidence=[dict(e) for e in incident.rca_evidence],
        created_at=incident.created_at,
        ack_deadline=incident.ack_deadline,
        resolve_deadline=incident.resolve_deadline,
        acknowledged_at=incident.acknowledged_at,
        acknowledged_by=incident.acknowledged_by,
        resolved_at=incident.resolved_at,
        resolved_by=incident.resolved_by,
        sla_status=sla_resp,
    )


# Global / dependency factory
_default_service: Optional[IncidentService] = None


def is_sqlite_dev_mode() -> bool:
    """Return True if explicitly configured for SQLite development mode."""
    env = os.getenv("ENVIRONMENT", "").lower()
    dev_flag = os.getenv("NEXUS_DEV_MODE", "").lower()
    return env in ("development", "dev") or dev_flag in ("true", "1", "yes")


def get_incident_service() -> IncidentService:
    """Dependency provider returning an IncidentService instance."""
    global _default_service
    if _default_service is None:
        db_url = os.getenv("DATABASE_URL") or os.getenv(
            "NEXUS_DATABASE_URL", "sqlite:///./nexus_incidents.db"
        )
        engine = create_engine(db_url)
        if engine.dialect.name == "sqlite":
            # Explicitly restrict SQLite schema auto-creation to development configuration
            if is_sqlite_dev_mode() or str(engine.url).endswith(":memory:"):
                from nexus.incidents.repository import Base

                Base.metadata.create_all(engine)
            else:
                from sqlalchemy import inspect

                inspector = inspect(engine)
                tables = inspector.get_table_names()
                if "incidents" not in tables or "incident_timeline_events" not in tables:
                    raise RuntimeError(
                        "SQLite schema is not migrated and development auto-creation is disabled. "
                        "Set ENVIRONMENT=development or run 'alembic upgrade head'."
                    )
        else:
            # PostgreSQL and other production backends strictly require Alembic migrations
            from sqlalchemy import inspect

            inspector = inspect(engine)
            tables = inspector.get_table_names()
            if "incidents" not in tables or "incident_timeline_events" not in tables:
                raise RuntimeError(
                    f"Database '{engine.dialect.name}' schema is not migrated. "
                    "Run 'alembic upgrade head' before starting the application."
                )

        repo = IncidentRepository.from_engine(engine)
        _default_service = IncidentService(
            repository=repo,
            event_publisher=get_broadcaster().publish,
        )
    return _default_service


def set_incident_service(service: IncidentService) -> None:
    """Explicitly override default service instance (useful for tests)."""
    global _default_service
    _default_service = service


router = APIRouter(prefix="/api/v1", tags=["incidents"])


@router.post(
    "/incidents",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse, "description": "Duplicate incident for correlation group"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
def create_incident(
    payload: CreateIncidentRequest,
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Create an incident from correlation and RCA analysis results."""
    # Convert validated alarm DTOs into real Alarm domain records with actual attributes
    alarms = [
        Alarm(
            alarm_id=a.alarm_id,
            node_id=a.node_id,
            rule_id=a.rule_id,
            metric_name=a.metric_name,
            source=a.source,
            severity=a.severity,
            current_value=a.current_value,
            threshold=a.threshold,
            first_seen=a.first_seen,
            last_seen=a.last_seen,
            observation_count=a.observation_count,
            status=a.status,
        )
        for a in payload.alarms
    ]

    alarm_ids = tuple(a.alarm_id for a in alarms)
    node_ids = tuple(dict.fromkeys(a.node_id for a in alarms))

    # Resolve or derive root_cause_tier from trusted topology source to protect backbone alarms
    tier = payload.root_cause_tier
    topo = get_topology()

    if tier is None:
        if payload.anchor_node_id:
            tier = resolve_node_tier(payload.anchor_node_id, topo)

        # Check alarm nodes so backbone tier is never lost
        if tier not in (NodeType.CORE, NodeType.AGGREGATION):
            for a in alarms:
                a_tier = resolve_node_tier(a.node_id, topo)
                if a_tier == NodeType.CORE:
                    tier = NodeType.CORE
                    break
                elif a_tier == NodeType.AGGREGATION and tier != NodeType.CORE:
                    tier = NodeType.AGGREGATION
                elif tier is None and a_tier is not None:
                    tier = a_tier

    # Ensure missing topology info cannot silently downgrade a critical/major alarm
    if tier is None:
        alarm_sevs = [a.severity for a in alarms]
        if Severity.CRITICAL in alarm_sevs or Severity.MAJOR in alarm_sevs:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="root_cause_tier is required when topology tier cannot be derived from node identifiers",
            )

    corr_group = CorrelationGroup(
        group_id=payload.correlation_group_id,
        anchor_node_id=payload.anchor_node_id,
        root_cause_tier=tier,
        alarms=tuple(alarms),
        alarm_ids=alarm_ids,
        node_ids=node_ids,
        time_window_start=payload.time_window_start,
        time_window_end=payload.time_window_end,
        correlation_reason=payload.correlation_reason,
    )

    # Process RCA hypothesis without inventing confidence defaults or target placeholders
    primary_hyp: Optional[RootCauseHypothesis] = None
    if payload.suspected_cause_type and payload.suspected_cause_type != RootCauseType.UNKNOWN:
        cause = payload.suspected_cause_type
        # Known diagnoses strictly require target information
        if not payload.suspected_target_id or not payload.suspected_target_type:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Known diagnoses require valid suspected_target_id and suspected_target_type",
            )
        tgt_type = payload.suspected_target_type
        target_id = payload.suspected_target_id

        evidence_items = []
        for ev in payload.evidence_items:
            evidence_items.append(
                EvidenceItem(
                    source_node_id=ev.source_node_id,
                    metric_name=ev.metric_name,
                    observed_value=ev.observed_value,
                    threshold_or_baseline=ev.threshold_or_baseline,
                    reasoning=ev.reasoning,
                    severity=ev.severity,
                    evidence_source=ev.evidence_source,
                )
            )

        primary_hyp = RootCauseHypothesis(
            hypothesis_id=f"HYP-{payload.correlation_group_id}",
            cause_type=cause,
            target_id=target_id,
            target_type=tgt_type,
            confidence_score=payload.rca_confidence_score,  # Preserve None when unavailable!
            explanation=payload.correlation_reason or f"Diagnosed {cause.value}",
            evidence_items=tuple(evidence_items),
            group_id=payload.correlation_group_id,
        )

    # Build full ranked hypotheses if supplied
    ranked_hypotheses: list[RootCauseHypothesis] = []
    if payload.hypotheses:
        for h in payload.hypotheses:
            h_evidence = [
                EvidenceItem(
                    source_node_id=ev.source_node_id,
                    metric_name=ev.metric_name,
                    observed_value=ev.observed_value,
                    threshold_or_baseline=ev.threshold_or_baseline,
                    reasoning=ev.reasoning,
                    severity=ev.severity,
                    evidence_source=ev.evidence_source,
                )
                for ev in h.evidence_items
            ]
            ranked_hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=h.hypothesis_id,
                    cause_type=h.cause_type,
                    target_id=h.target_id,
                    target_type=h.target_type,
                    confidence_score=h.confidence_score,
                    explanation=h.explanation,
                    evidence_items=tuple(h_evidence),
                    group_id=payload.correlation_group_id,
                )
            )
    elif primary_hyp is not None:
        ranked_hypotheses.append(primary_hyp)

    rca_res = RCAResult(
        group_id=payload.correlation_group_id,
        hypotheses=tuple(ranked_hypotheses),
        primary_hypothesis=primary_hyp,
        analysis_timestamp=payload.time_window_end,
    )

    try:
        incident = service.create_incident(
            correlation_group=corr_group,
            rca_result=rca_res,
            actor=payload.created_by,
            creation_timestamp=payload.time_window_end,
        )
        return _incident_to_response(incident)
    except DuplicateIncidentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/incidents",
    response_model=IncidentListResponse,
    status_code=status.HTTP_200_OK,
)
def list_incidents(
    status_filter: Optional[IncidentStatus] = Query(None, alias="status", description="Filter by status"),
    severity_filter: Optional[IncidentSeverity] = Query(None, alias="severity", description="Filter by severity"),
    limit: int = Query(50, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    service: IncidentService = Depends(get_incident_service),
) -> IncidentListResponse:
    """List operational incidents with optional filtering and pagination."""
    items, total = service.list_incidents(
        status=status_filter, severity=severity_filter, limit=limit, offset=offset
    )
    return IncidentListResponse(
        items=[_incident_to_response(inc) for inc in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/incidents/metrics",
    response_model=IncidentMetricsResponse,
    status_code=status.HTTP_200_OK,
)
def get_metrics(
    service: IncidentService = Depends(get_incident_service),
) -> IncidentMetricsResponse:
    """Retrieve operational incident and SLA metrics."""
    metrics = service.get_metrics()
    return IncidentMetricsResponse(
        total_incidents=metrics.total_incidents,
        open_incident_count=metrics.open_incident_count,
        incidents_by_status=dict(metrics.incidents_by_status),
        incidents_by_severity=dict(metrics.incidents_by_severity),
        mtta_seconds=metrics.mtta_seconds,
        mttr_seconds=metrics.mttr_seconds,
        mttd_seconds=metrics.mttd_seconds,
        total_incidents_evaluated=metrics.total_incidents_evaluated,
        compliant_incident_count=metrics.compliant_incident_count,
        breached_incident_count=metrics.breached_incident_count,
        ack_sla_breached_count=metrics.ack_sla_breached_count,
        resolve_sla_breached_count=metrics.resolve_sla_breached_count,
        sla_compliance_pct=metrics.sla_compliance_pct,
        as_of=metrics.as_of,
    )


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse, "description": "Incident not found"}},
)
def get_incident(
    incident_id: str,
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Retrieve full incident details."""
    try:
        incident = service.get_incident(incident_id)
        return _incident_to_response(incident)
    except IncidentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/incidents/{incident_id}/acknowledge",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid state transition"},
        404: {"model": ErrorResponse, "description": "Incident not found"},
    },
)
def acknowledge_incident(
    incident_id: str,
    payload: AcknowledgeRequest,
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Acknowledge an incident."""
    try:
        updated = service.acknowledge_incident(
            incident_id=incident_id,
            actor=payload.actor,
            actor_type=ActorType.OPERATOR,
        )
        return _incident_to_response(updated)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/incidents/{incident_id}/resolve",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid state transition"},
        404: {"model": ErrorResponse, "description": "Incident not found"},
    },
)
def resolve_incident(
    incident_id: str,
    payload: ResolveRequest,
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Resolve an incident."""
    try:
        updated = service.resolve_incident(
            incident_id=incident_id,
            actor=payload.actor,
            notes=payload.notes,
            actor_type=ActorType.OPERATOR,
        )
        return _incident_to_response(updated)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/incidents/{incident_id}/timeline",
    response_model=list[TimelineEventResponse],
    status_code=status.HTTP_200_OK,
    responses={404: {"model": ErrorResponse, "description": "Incident not found"}},
)
def get_timeline(
    incident_id: str,
    service: IncidentService = Depends(get_incident_service),
) -> list[TimelineEventResponse]:
    """Retrieve ordered timeline history for an incident."""
    try:
        events = service.get_timeline(incident_id)
        return [
            TimelineEventResponse(
                event_id=e.event_id,
                incident_id=e.incident_id,
                event_type=e.event_type.value,
                timestamp=e.timestamp,
                actor=e.actor,
                actor_type=e.actor_type.value,
                details=dict(e.details),
            )
            for e in events
        ]
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def create_app() -> FastAPI:
    """FastAPI application factory."""

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        # Register exactly one listener for each running application instance
        broadcaster = get_broadcaster()
        topo = get_topology_registry()

        def on_topology_status_change(
            node_id: str, old_status: NodeStatus, new_status: NodeStatus, ts: datetime
        ) -> None:
            broadcaster.publish(
                "TOPOLOGY_STATUS_CHANGED",
                {
                    "node_id": node_id,
                    "previous_status": old_status.value,
                    "new_status": new_status.value,
                    "timestamp": ts.isoformat(),
                },
                timestamp=ts,
            )

        topo.add_status_listener(on_topology_status_change)
        try:
            yield
        finally:
            # Deterministically remove callback on shutdown
            topo.remove_status_listener(on_topology_status_change)

    app = FastAPI(
        title="NEXUS Incident Management API",
        version="1.0.0",
        description="Operational incident management, lifecycle tracking, and SLA reporting API.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    @app.exception_handler(IncidentNotFoundError)
    async def not_found_handler(request: Any, exc: IncidentNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(exc), "error_code": "INCIDENT_NOT_FOUND"},
        )

    @app.exception_handler(DuplicateIncidentError)
    async def duplicate_handler(request: Any, exc: DuplicateIncidentError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc), "error_code": "DUPLICATE_INCIDENT"},
        )

    @app.exception_handler(InvalidStateTransitionError)
    async def invalid_transition_handler(
        request: Any, exc: InvalidStateTransitionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc), "error_code": "INVALID_STATE_TRANSITION"},
        )

    @app.exception_handler(InvalidIncidentDataError)
    async def invalid_data_handler(
        request: Any, exc: InvalidIncidentDataError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": str(exc), "error_code": "INVALID_INCIDENT_DATA"},
        )

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "healthy"}

    # Wire authentic event publishers to live broadcaster
    broadcaster = get_broadcaster()
    topo = get_topology_registry()
    get_telemetry_store().set_event_publisher(broadcaster.publish)
    get_telemetry_store().set_topology(topo)
    get_alarm_service().set_event_publisher(broadcaster.publish)
    get_telemetry_pipeline()  # Initialize pipeline

    app.include_router(router)
    app.include_router(topology_router)
    app.include_router(telemetry_router)
    app.include_router(alarm_router)
    app.include_router(websocket_router)
    return app


app = create_app()
