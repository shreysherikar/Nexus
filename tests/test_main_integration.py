"""Integration tests for NEXUS central application entrypoint (nexus.main)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from nexus.main import app, create_app
from nexus.topology.api import get_topology_registry, set_topology_registry
from nexus.topology.builder import build_simulated_network
from nexus.topology.enums import NodeStatus
from nexus.events.broadcaster import get_broadcaster


@pytest.fixture
def client() -> TestClient:
    """Fixture providing TestClient with active lifespan context."""
    with patch.dict("os.environ", {"ENVIRONMENT": "development", "DATABASE_URL": "sqlite:///:memory:"}):
        # Reset incident service so in-memory SQLite is used cleanly
        import nexus.incidents.api as inc_api
        inc_api._default_service = None
        test_app = create_app()
        with TestClient(test_app) as tc:
            yield tc
        inc_api._default_service = None


class TestMainAppIntegration:
    """Verify central app creation, metadata, and router mounting."""

    def test_app_metadata(self) -> None:
        """App has correct title, description, and OpenAPI docs paths."""
        test_app = create_app()
        assert test_app.title == "NEXUS Network Intelligence & Incident Management Platform"
        assert test_app.version == "1.0.0"
        assert test_app.docs_url == "/docs"
        assert test_app.openapi_url == "/openapi.json"

    def test_root_endpoint(self, client: TestClient) -> None:
        """GET / returns platform overview and endpoint navigation."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "NEXUS" in data["platform"]
        assert data["health_url"] == "/health"
        assert data["readiness_url"] == "/ready"
        assert data["docs_url"] == "/docs"

    def test_health_liveness_check(self, client: TestClient) -> None:
        """GET /health returns healthy status for liveness probes."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_readiness_check_healthy(self, client: TestClient) -> None:
        """GET /ready returns 200 OK and detailed status when all subsystems are operational."""
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        components = data["components"]
        assert "topology" in components and "ready" in components["topology"]
        assert "broadcaster" in components and "ready" in components["broadcaster"]
        assert "telemetry_store" in components and "ready" in components["telemetry_store"]
        assert "alarm_service" in components and "ready" in components["alarm_service"]
        assert "fault_service" in components and "ready" in components["fault_service"]
        assert components["database"] == "ready"

    def test_readiness_check_database_unhealthy(self) -> None:
        """GET /ready returns 503 Service Unavailable when database is not migrated or unavailable."""
        with patch("nexus.main.get_incident_service", side_effect=RuntimeError("Database schema is not migrated")):
            test_app = create_app()
            with TestClient(test_app) as tc:
                response = tc.get("/ready")
                assert response.status_code == 503
                data = response.json()
                assert data["status"] == "not_ready"
                assert "unhealthy" in data["components"]["database"]

    def test_cors_middleware_preflight(self, client: TestClient) -> None:
        """Preflight OPTIONS request from frontend origins receives proper CORS headers."""
        response = client.options(
            "/api/v1/topology",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert "GET" in response.headers.get("access-control-allow-methods", "")

    def test_cors_middleware_custom_origin(self) -> None:
        """CORS honors NEXUS_CORS_ORIGINS environment variable."""
        with patch.dict("os.environ", {"NEXUS_CORS_ORIGINS": "https://noc.example.com"}):
            custom_app = create_app()
            with TestClient(custom_app) as tc:
                resp = tc.options(
                    "/api/v1/topology",
                    headers={
                        "Origin": "https://noc.example.com",
                        "Access-Control-Request-Method": "GET",
                    },
                )
                assert resp.status_code == 200
                assert resp.headers.get("access-control-allow-origin") == "https://noc.example.com"

    def test_all_routers_mounted_and_responsive(self, client: TestClient) -> None:
        """Verify all domain routers are properly mounted on nexus.main app."""
        # 1. Topology router
        resp_topo = client.get("/api/v1/topology")
        assert resp_topo.status_code == 200
        topo_data = resp_topo.json()
        assert topo_data["total_nodes"] == 27

        # 2. Telemetry router
        resp_telem = client.get("/api/v1/telemetry")
        assert resp_telem.status_code == 200
        assert "items" in resp_telem.json()

        # 3. Detection & Alarm router
        resp_alarms = client.get("/api/v1/alarms")
        assert resp_alarms.status_code == 200
        assert "items" in resp_alarms.json()

        resp_rules = client.get("/api/v1/detection/rules")
        assert resp_rules.status_code == 200
        rules_data = resp_rules.json()
        assert rules_data["total"] == 8

        # 4. Incidents router
        resp_inc = client.get("/api/v1/incidents")
        assert resp_inc.status_code == 200
        assert "items" in resp_inc.json()

        resp_metrics = client.get("/api/v1/incidents/metrics")
        assert resp_metrics.status_code == 200
        assert "total_incidents" in resp_metrics.json()

        # 5. Faults router
        resp_faults = client.get("/api/v1/faults/scenarios")
        assert resp_faults.status_code == 200
        assert resp_faults.json()["total"] == 5

    def test_websocket_endpoint_operational(self, client: TestClient) -> None:
        """WebSocket /ws/live connects and responds to heartbeat ping."""
        with client.websocket_connect("/ws/live") as ws:
            ws.send_json({"type": "PING", "timestamp": "2026-11-02T06:00:00Z"})
            response = ws.receive_json()
            assert response["type"] == "PONG"
            assert response["timestamp"] == "2026-11-02T06:00:00Z"

    def test_lifespan_topology_listener_lifecycle(self) -> None:
        """Application lifespan attaches status listener and detaches on shutdown."""
        isolated_topo = build_simulated_network()
        set_topology_registry(isolated_topo)
        broadcaster = get_broadcaster()

        events_received = []
        orig_publish = broadcaster.publish

        def capture(event_type: str, payload: dict, timestamp=None):
            if event_type == "TOPOLOGY_STATUS_CHANGED":
                events_received.append(dict(payload))
            return orig_publish(event_type, payload, timestamp)

        broadcaster.publish = capture  # type: ignore

        try:
            assert len(isolated_topo._status_listeners) == 0
            test_app = create_app()

            with TestClient(test_app):
                # Started: listener is attached
                assert len(isolated_topo._status_listeners) == 1
                isolated_topo.update_node_status("SITE-01", NodeStatus.DEGRADED)
                assert len(events_received) == 1
                assert events_received[0]["node_id"] == "SITE-01"
                assert events_received[0]["new_status"] == "DEGRADED"

            # Stopped: listener is cleanly detached
            assert len(isolated_topo._status_listeners) == 0
        finally:
            broadcaster.publish = orig_publish

    def test_backward_compatibility_incidents_api_app(self) -> None:
        """Importing app or create_app from nexus.incidents.api works identically."""
        import nexus.incidents.api as inc_api
        import nexus.main as main_mod

        # Ensure app reference is identical
        assert inc_api.app is main_mod.app

        # create_app returns a valid FastAPI app with all routers
        new_app = inc_api.create_app()
        assert new_app.title == "NEXUS Network Intelligence & Incident Management Platform"

    def test_service_worker_unregistration_migration(self, client: TestClient) -> None:
        """GET /sw.js provides safe self-unregistration script with no-cache headers."""
        resp_sw = client.get("/sw.js")
        assert resp_sw.status_code == 200
        assert "application/javascript" in resp_sw.headers.get("content-type", "")
        assert "self.registration.unregister()" in resp_sw.text
        assert "self.skipWaiting()" in resp_sw.text
        # Must instruct browsers not to cache unregistration script
        cache_control = resp_sw.headers.get("cache-control", "")
        assert "no-cache" in cache_control
        assert "no-store" in cache_control

    def test_missing_assets_return_honest_404(self, client: TestClient) -> None:
        """Missing assets and favicons must return authentic HTTP 404, not fake fallbacks."""
        # 1. Stale PWA logo from prior localhost:8000 project returns 404
        resp_logo = client.get("/assets/brand-logo-CMQh4-UI.png")
        assert resp_logo.status_code == 404

        # 2. Missing favicon returns authentic 404
        resp_fav = client.get("/favicon.ico")
        assert resp_fav.status_code == 404

        # 3. Arbitrary nonexistent assets return 404
        resp_unknown = client.get("/assets/nonexistent-bundle.xyz")
        assert resp_unknown.status_code == 404

    def test_legitimate_production_asset_serving(self, client: TestClient) -> None:
        """Legitimate built frontend assets from frontend/dist/assets are served with proper MIME types."""
        from pathlib import Path
        assets_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "assets"
        css_files = list(assets_dir.glob("*.css"))
        if css_files:
            css_name = css_files[0].name
            resp_css = client.get(f"/assets/{css_name}")
            assert resp_css.status_code == 200
            assert "text/css" in resp_css.headers.get("content-type", "")
            assert len(resp_css.content) > 0

    def test_api_documentation_access(self, client: TestClient) -> None:
        """Interactive OpenAPI documentation endpoints are accessible."""
        resp_docs = client.get("/docs")
        assert resp_docs.status_code == 200
        assert "swagger-ui" in resp_docs.text.lower() or "html" in resp_docs.headers.get("content-type", "")

        resp_openapi = client.get("/openapi.json")
        assert resp_openapi.status_code == 200
        openapi_data = resp_openapi.json()
        assert openapi_data["info"]["title"] == "NEXUS Network Intelligence & Incident Management Platform"
