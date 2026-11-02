"""NEXUS Network Intelligence & Incident Management Platform - Main Application Entrypoint.

This module provides the central FastAPI ASGI application instance, lifespan lifecycle
management, subsystem wiring, CORS middleware, health/readiness probes, and router aggregation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Optionally load environment variables from .env file if present
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from nexus.detection.api import router as alarm_router
from nexus.detection.service import get_alarm_service
from nexus.events.api import router as websocket_router
from nexus.events.broadcaster import get_broadcaster
from nexus.fault.api import router as fault_router
from nexus.fault.service import get_fault_service
from nexus.incidents.api import (
    get_incident_service,
    router as incidents_router,
)
from nexus.incidents.exceptions import (
    DuplicateIncidentError,
    IncidentNotFoundError,
    InvalidIncidentDataError,
    InvalidStateTransitionError,
)
from nexus.telemetry.api import router as telemetry_router
from nexus.telemetry.orchestrator import get_telemetry_pipeline
from nexus.telemetry.store import get_telemetry_store
from nexus.topology.api import get_topology_registry, router as topology_router
from nexus.topology.enums import NodeStatus
from nexus.topology.exceptions import NodeNotFoundError

logger = logging.getLogger("nexus.main")


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Central application lifespan managing startup, telemetry, events, and graceful shutdown."""
    broadcaster = get_broadcaster()
    topo = get_topology_registry()

    # Wire telemetry store and alarm service to event broadcaster
    store = get_telemetry_store()
    store.set_event_publisher(broadcaster.publish)
    store.set_topology(topo)

    alarm_service = get_alarm_service()
    alarm_service.set_event_publisher(broadcaster.publish)

    fault_service = get_fault_service()
    fault_service.set_event_publisher(broadcaster.publish)

    # Initialize telemetry pipeline without starting background generation loops
    get_telemetry_pipeline()

    # Register topology status listener to broadcast changes over WebSocket
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
    logger.info("NEXUS application startup complete: topology, telemetry pipeline, and broadcaster initialized.")

    try:
        yield
    finally:
        # Deterministically clean up status listener on shutdown
        topo.remove_status_listener(on_topology_status_change)
        logger.info("NEXUS application shutdown complete: listeners detached.")


def create_app() -> FastAPI:
    """Create and configure the authoritative NEXUS FastAPI application instance."""
    app = FastAPI(
        title="NEXUS Network Intelligence & Incident Management Platform",
        version="1.0.0",
        description=(
            "Central operational intelligence platform providing network topology, "
            "synthetic telemetry monitoring, alarm correlation, explainable root cause analysis, "
            "and real-time incident lifecycle management."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Configure CORS for frontend SPA integration
    cors_origins_env = os.getenv("NEXUS_CORS_ORIGINS", "")
    if cors_origins_env.strip():
        if cors_origins_env.strip() == "*":
            allow_origins = ["*"]
        else:
            allow_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
    else:
        allow_origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_no_cache_headers(request: Request, call_next):
        """Prevent intermediary and browser caching of real-time API responses."""
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    # Domain Exception Handlers
    @app.exception_handler(IncidentNotFoundError)
    async def incident_not_found_handler(request: Any, exc: IncidentNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(exc), "error_code": "INCIDENT_NOT_FOUND"},
        )

    @app.exception_handler(DuplicateIncidentError)
    async def duplicate_incident_handler(request: Any, exc: DuplicateIncidentError) -> JSONResponse:
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

    @app.exception_handler(NodeNotFoundError)
    async def node_not_found_handler(request: Any, exc: NodeNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(exc), "error_code": "NODE_NOT_FOUND"},
        )

    # System endpoints
    @app.get("/", tags=["system"], summary="Platform Overview")
    async def root() -> dict[str, Any]:
        return {
            "platform": "NEXUS Network Intelligence & Incident Management Platform",
            "version": "1.0.0",
            "docs_url": "/docs",
            "health_url": "/health",
            "readiness_url": "/ready",
        }

    @app.get("/health", tags=["system"], summary="Service Liveness Probe")
    async def health_check() -> dict[str, str]:
        """Liveness probe returning healthy when the process is up and responsive."""
        return {"status": "healthy"}

    @app.get("/ready", tags=["system"], summary="Service Readiness Probe")
    async def readiness_check() -> JSONResponse:
        """Readiness probe verifying operational status across database, topology, telemetry, and broadcaster."""
        components: dict[str, str] = {}
        is_ready = True

        # 1. Topology Registry Check
        try:
            topo = get_topology_registry()
            node_count = len(topo) if hasattr(topo, "__len__") else len(topo.all_nodes())
            if node_count > 0:
                components["topology"] = f"ready ({node_count} nodes)"
            else:
                components["topology"] = "not_ready (empty topology)"
                is_ready = False
        except Exception as exc:
            components["topology"] = f"error: {str(exc)}"
            is_ready = False

        # 2. Event Broadcaster Check
        try:
            broadcaster = get_broadcaster()
            components["broadcaster"] = f"ready ({broadcaster.active_connections_count} subscribers)"
        except Exception as exc:
            components["broadcaster"] = f"error: {str(exc)}"
            is_ready = False

        # 3. Telemetry Store Check
        try:
            store = get_telemetry_store()
            components["telemetry_store"] = f"ready ({store.count} snapshots)"
        except Exception as exc:
            components["telemetry_store"] = f"error: {str(exc)}"
            is_ready = False

        # 4. Alarm Service Check
        try:
            alarm_svc = get_alarm_service()
            rule_count = len(alarm_svc.get_rules())
            components["alarm_service"] = f"ready ({rule_count} rules)"
        except Exception as exc:
            components["alarm_service"] = f"error: {str(exc)}"
            is_ready = False

        # 5. Fault Service Check
        try:
            fault_svc = get_fault_service()
            active_sc = fault_svc.get_active_scenario()
            components["fault_service"] = f"ready (active: {active_sc.active})"
        except Exception as exc:
            components["fault_service"] = f"error: {str(exc)}"
            is_ready = False

        # 6. Database & Incident Service Check
        try:
            if get_incident_service in app.dependency_overrides:
                svc = app.dependency_overrides[get_incident_service]()
            else:
                svc = get_incident_service()
            if svc is not None:
                components["database"] = "ready"
            else:
                components["database"] = "not_ready"
                is_ready = False
        except Exception as exc:
            components["database"] = f"unhealthy: {str(exc)}"
            is_ready = False

        status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ready" if is_ready else "not_ready",
                "components": components,
            },
        )

    # Service Worker cleanup:
    # Origin localhost:8000 may have had an active service worker registered by a previous
    # application on this port. NEXUS does not use a service worker. This endpoint provides
    # a safe, self-unregistering migration script to purge stale workers from operator browsers.
    # Lifecycle: Temporary migration route; safe to deprecate/remove once all clients have updated.
    @app.get("/sw.js", include_in_schema=False)
    async def service_worker_unregistration():
        """Temporary migration endpoint: safely unregister stale service worker."""
        content = (
            "self.addEventListener('install', () => self.skipWaiting());\n"
            "self.addEventListener('activate', (event) => {\n"
            "  event.waitUntil(\n"
            "    self.registration.unregister().then(() => self.clients.matchAll())\n"
            "      .then((clients) => { clients.forEach((c) => c.navigate(c.url)); })\n"
            "  );\n"
            "});\n"
        )
        return Response(
            content=content,
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    # Legitimate production static asset serving (if frontend dist assets exist)
    dist_assets = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist", "assets")
    )
    if os.path.isdir(dist_assets):
        from starlette.staticfiles import StaticFiles

        app.mount("/assets", StaticFiles(directory=dist_assets), name="assets")

    # Wire authentic event publishers at creation time
    broadcaster = get_broadcaster()
    topo = get_topology_registry()
    get_telemetry_store().set_event_publisher(broadcaster.publish)
    get_telemetry_store().set_topology(topo)
    get_alarm_service().set_event_publisher(broadcaster.publish)
    get_fault_service().set_event_publisher(broadcaster.publish)
    get_telemetry_pipeline()

    # Include all feature routers
    app.include_router(incidents_router)
    app.include_router(topology_router)
    app.include_router(telemetry_router)
    app.include_router(alarm_router)
    app.include_router(websocket_router)
    app.include_router(fault_router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("ENVIRONMENT", "").lower() in ("development", "dev") or os.getenv("RELOAD", "").lower() in ("true", "1")
    uvicorn.run("nexus.main:app", host=host, port=port, reload=reload)
