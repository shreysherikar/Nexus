"""FastAPI router for Telemetry read API."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from nexus.telemetry.orchestrator import TelemetryPipeline, get_telemetry_pipeline
from nexus.telemetry.schemas import (
    KPISnapshotResponse,
    PerformanceMetricsResponse,
    RadioMetricsResponse,
    ReliabilityMetricsResponse,
    TelemetryGenerateStepResponse,
    TelemetryListResponse,
)
from nexus.telemetry.store import TelemetryStore, get_telemetry_store
from nexus.topology.enums import NodeType

router = APIRouter(prefix="/api/v1", tags=["telemetry"])
_step_generation_lock = threading.Lock()


@router.get(
    "/telemetry",
    response_model=TelemetryListResponse,
    summary="Query telemetry snapshots",
    description="Query authentic generated telemetry snapshots from the buffer with filtering and pagination.",
)
def get_telemetry(
    node_id: Optional[str] = Query(None, description="Filter by node ID"),
    node_type: Optional[str] = Query(None, description="Filter by node type (CORE, AGGREGATION, SITE, CELL)"),
    start_time: Optional[datetime] = Query(None, description="Inclusive start time UTC"),
    end_time: Optional[datetime] = Query(None, description="Inclusive end time UTC"),
    limit: int = Query(50, ge=1, le=1000, description="Page limit (1-1000)"),
    offset: int = Query(0, ge=0, description="Page offset (>=0)"),
    store: TelemetryStore = Depends(get_telemetry_store),
) -> TelemetryListResponse:
    """Retrieve filtered, deterministically ordered KPISnapshots from the active telemetry store."""
    if start_time and end_time and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_time must be earlier than or equal to end_time",
        )

    parsed_node_type: Optional[NodeType] = None
    if node_type is not None:
        try:
            parsed_node_type = NodeType(node_type.upper().strip())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid node_type '{node_type}'. Expected one of: {[t.value for t in NodeType]}",
            )

    snapshots, total = store.query(
        node_id=node_id,
        node_type=parsed_node_type,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )

    items: list[KPISnapshotResponse] = []
    for s in snapshots:
        radio_resp = (
            RadioMetricsResponse(
                rsrp_dbm=s.radio.rsrp_dbm,
                sinr_db=s.radio.sinr_db,
                prb_utilization_pct=s.radio.prb_utilization_pct,
            )
            if s.radio is not None
            else None
        )
        perf_resp = PerformanceMetricsResponse(
            throughput_mbps=s.performance.throughput_mbps,
            latency_ms=s.performance.latency_ms,
        )
        rel_resp = ReliabilityMetricsResponse(
            connection_drop_rate_pct=s.reliability.connection_drop_rate_pct,
            availability_pct=s.reliability.availability_pct,
            handover_success_rate_pct=s.reliability.handover_success_rate_pct,
        )
        items.append(
            KPISnapshotResponse(
                node_id=s.node_id,
                timestamp=s.timestamp,
                performance=perf_resp,
                reliability=rel_resp,
                radio=radio_resp,
            )
        )

    return TelemetryListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/telemetry/generate-step",
    response_model=TelemetryGenerateStepResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate one simulated telemetry step",
    description=(
        "Explicit operator action invoking the SyntheticTelemetryGenerator via TelemetryPipeline. "
        "Produces exactly one deterministic simulation step for all topology nodes and records "
        "it into the in-memory TelemetryStore. Data is retained in memory and discarded on restart."
    ),
)
def generate_telemetry_step(
    pipeline: TelemetryPipeline = Depends(get_telemetry_pipeline),
) -> TelemetryGenerateStepResponse:
    """Generate one discrete step of synthetic telemetry and record into buffer."""
    acquired = _step_generation_lock.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Telemetry step generation is already in progress. Please wait for current cycle to complete.",
        )

    try:
        snapshots = pipeline.generate_step()
        ts = snapshots[0].timestamp if snapshots else datetime.now(timezone.utc)
        return TelemetryGenerateStepResponse(
            generated_count=len(snapshots),
            timestamp=ts,
            message="Deterministic simulation step generated and recorded into in-memory store.",
        )
    finally:
        _step_generation_lock.release()
