"""Comprehensive integration and unit tests for NEXUS Prometheus Metrics Engine (Phase 8.1).

Validates:
- Exposition format and HTTP headers at GET /metrics.
- Normalized route templates and bounded cardinality (no dynamic node/alarm/incident IDs in labels).
- Prevention of self-distortion (GET /metrics does not increment HTTP request counters).
- Application info and readiness subsystem health gauges.
- Authoritative telemetry domain metrics aggregated by network tier.
- Alarm domain metrics by severity and status.
- Incident domain metrics and SLA compliance counters.
- Fault injection scenario status and affected node count tracking.
- Strict ground truth isolation: no ground-truth internal metadata leaked to metrics.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Generator
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from nexus.detection.models import (
    Alarm,
    AlarmStatus,
    AnomalyEvent,
    DetectionSource,
    Severity,
)
from nexus.detection.service import AlarmService, get_alarm_service, set_alarm_service
from nexus.fault.service import FaultService, get_fault_service, set_fault_service
from nexus.incidents.api import get_incident_service
import nexus.incidents.api as inc_api
from nexus.incidents.enums import (
    ActorType,
    IncidentPriority,
    IncidentSeverity,
    IncidentStatus,
)
from nexus.incidents.models import Incident
from nexus.incidents.repository import IncidentRepository, create_engine
from nexus.incidents.service import IncidentService
from sqlalchemy.pool import StaticPool
from nexus.main import create_app
from nexus.metrics import (
    NexusMetricsManager,
    VALID_ALARM_SEVERITIES,
    VALID_FAULT_SCENARIOS,
    VALID_INCIDENT_SEVERITIES,
    VALID_NODE_TIERS,
    get_metrics_manager,
    reset_metrics_manager,
    set_metrics_manager,
)
from nexus.telemetry.models import KPISnapshot, PerformanceMetrics, RadioMetrics, ReliabilityMetrics
from nexus.telemetry.store import TelemetryStore, get_telemetry_store, set_telemetry_store
from nexus.topology.api import get_topology_registry
from nexus.topology.enums import NodeType


@pytest.fixture(autouse=True)
def isolated_metrics() -> Generator[NexusMetricsManager, None, None]:
    """Provide an isolated NexusMetricsManager with a clean registry for each test."""
    manager = reset_metrics_manager()
    set_metrics_manager(manager)
    yield manager
    reset_metrics_manager()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Create a TestClient with an isolated in-memory SQLite incident service and clean stores."""
    with patch.dict(
        "os.environ",
        {"ENVIRONMENT": "development", "DATABASE_URL": "sqlite:///:memory:"},
    ):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        from nexus.incidents.repository import Base

        Base.metadata.create_all(engine)
        repo = IncidentRepository.from_engine(engine)
        inc_service = IncidentService(repository=repo)
        inc_api._default_service = inc_service

        test_app = create_app()
        test_app.dependency_overrides[get_incident_service] = lambda: inc_service

        with TestClient(test_app) as tc:
            yield tc

        inc_api._default_service = None


def test_metrics_endpoint_headers_and_status(client: TestClient) -> None:
    """GET /metrics returns HTTP 200 with proper Prometheus content type and cache headers."""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers.get("content-type", "")
    assert "no-cache" in resp.headers.get("cache-control", "")
    assert "nexus_app_info" in resp.text
    assert 'platform="NEXUS"' in resp.text
    assert 'version="1.0.0"' in resp.text


def test_metrics_root_link(client: TestClient) -> None:
    """Root overview endpoint includes metrics_url pointing to /metrics."""
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("metrics_url") == "/metrics"


def test_http_requests_normalized_route_and_cardinality(client: TestClient) -> None:
    """Requests are recorded under normalized route templates, never raw dynamic IDs."""
    # 1. Health probe
    client.get("/health")

    # 2. Dynamic ID route: /api/v1/incidents/{incident_id}
    client.get("/api/v1/incidents/INC-99999-NOTFOUND")

    # 3. Dynamic topology route: /api/v1/topology/nodes/{node_id}
    client.get("/api/v1/topology/nodes/CELL-05")

    # 4. Unknown route: unmapped
    client.get("/completely/unknown/endpoint/path")

    resp = client.get("/metrics")
    body = resp.text

    # Verify normalized endpoints exist
    assert 'nexus_http_requests_total{endpoint="/health",method="GET",status="200"}' in body
    assert 'nexus_http_requests_total{endpoint="/api/v1/incidents/{incident_id}",method="GET",status="404"}' in body
    assert 'nexus_http_requests_total{endpoint="/api/v1/topology/nodes/{node_id}",method="GET",status="200"}' in body
    assert 'nexus_http_requests_total{endpoint="unmatched",method="GET",status="404"}' in body

    # Verify raw dynamic IDs are strictly NOT emitted as label values
    assert 'endpoint="/api/v1/incidents/INC-99999-NOTFOUND"' not in body
    assert 'endpoint="/api/v1/topology/nodes/CELL-05"' not in body
    assert "INC-99999-NOTFOUND" not in body


def test_metrics_self_exclusion_prevents_distortion(client: TestClient) -> None:
    """Scraping /metrics does NOT increment nexus_http_requests_total or duration."""
    # Make one authentic API request so HTTP metrics are populated
    resp_health = client.get("/health")
    assert resp_health.status_code == 200

    # Scrape /metrics 5 times
    for _ in range(5):
        resp = client.get("/metrics")
        assert resp.status_code == 200

    metrics_text = client.get("/metrics").text

    # /health request was recorded
    assert 'nexus_http_requests_total{endpoint="/health",method="GET",status="200"} 1.0' in metrics_text
    assert 'nexus_http_request_duration_seconds_count{endpoint="/health",method="GET"} 1.0' in metrics_text

    # /metrics itself should NEVER appear in nexus_http_requests_total
    assert 'endpoint="/metrics"' not in metrics_text
    matches = re.findall(r'nexus_http_requests_total\{[^}]*endpoint="/metrics"[^}]*\}', metrics_text)
    assert len(matches) == 0


def test_application_readiness_gauges(client: TestClient) -> None:
    """Application readiness gauges report 1.0 for all ready components."""
    resp = client.get("/metrics")
    body = resp.text

    assert "nexus_ready_status 1.0" in body
    assert 'nexus_component_ready{component="topology"} 1.0' in body
    assert 'nexus_component_ready{component="broadcaster"} 1.0' in body
    assert 'nexus_component_ready{component="telemetry_store"} 1.0' in body
    assert 'nexus_component_ready{component="alarm_service"} 1.0' in body
    assert 'nexus_component_ready{component="fault_service"} 1.0' in body


def test_telemetry_domain_tier_aggregates(client: TestClient) -> None:
    """Telemetry tier aggregates compute correct mean KPIs across network tiers."""
    store = get_telemetry_store()
    store.clear()

    now = datetime.now(timezone.utc)

    # Insert snapshots for 2 CELL nodes and 1 CORE node
    s1 = KPISnapshot(
        node_id="CELL-01",
        timestamp=now,
        performance=PerformanceMetrics(throughput_mbps=100.0, latency_ms=10.0),
        reliability=ReliabilityMetrics(connection_drop_rate_pct=1.0, availability_pct=99.0),
        radio=RadioMetrics(rsrp_dbm=-80.0, sinr_db=20.0, prb_utilization_pct=40.0),
    )
    s2 = KPISnapshot(
        node_id="CELL-02",
        timestamp=now,
        performance=PerformanceMetrics(throughput_mbps=200.0, latency_ms=20.0),
        reliability=ReliabilityMetrics(connection_drop_rate_pct=3.0, availability_pct=97.0),
        radio=RadioMetrics(rsrp_dbm=-90.0, sinr_db=10.0, prb_utilization_pct=60.0),
    )
    s3 = KPISnapshot(
        node_id="CORE-01",
        timestamp=now,
        performance=PerformanceMetrics(throughput_mbps=1000.0, latency_ms=2.0),
        reliability=ReliabilityMetrics(connection_drop_rate_pct=0.0, availability_pct=100.0),
    )
    store.record(s1)
    store.record(s2)
    store.record(s3)

    resp = client.get("/metrics")
    body = resp.text

    assert "nexus_telemetry_snapshots_total 3.0" in body

    # CELL averages: throughput = (100+200)/2 = 150.0, latency = (10+20)/2 = 15.0
    assert 'nexus_telemetry_throughput_mbps_avg{node_tier="CELL"} 150.0' in body
    assert 'nexus_telemetry_latency_ms_avg{node_tier="CELL"} 15.0' in body
    assert 'nexus_telemetry_drop_rate_pct_avg{node_tier="CELL"} 2.0' in body
    assert 'nexus_telemetry_availability_pct_avg{node_tier="CELL"} 98.0' in body

    # Radio averages: sinr = (20+10)/2 = 15.0, prb = (40+60)/2 = 50.0
    assert "nexus_telemetry_radio_sinr_db_avg 15.0" in body
    assert "nexus_telemetry_radio_prb_utilization_pct_avg 50.0" in body

    # CORE averages: throughput = 1000.0, latency = 2.0
    assert 'nexus_telemetry_throughput_mbps_avg{node_tier="CORE"} 1000.0' in body
    assert 'nexus_telemetry_latency_ms_avg{node_tier="CORE"} 2.0' in body


def test_alarm_metrics_lifecycle(client: TestClient) -> None:
    """Active and total alarm counts reflect alarm creation and clearance."""
    alarm_svc = AlarmService()
    set_alarm_service(alarm_svc)

    now = datetime.now(timezone.utc)
    ev1 = AnomalyEvent(
        node_id="CELL-05",
        metric_name="sinr_db",
        timestamp=now,
        source=DetectionSource.THRESHOLD,
        rule_id="RULE-SINR",
        severity=Severity.CRITICAL,
        current_value=2.0,
        threshold=5.0,
    )
    ev2 = AnomalyEvent(
        node_id="SITE-01",
        metric_name="connection_drop_rate_pct",
        timestamp=now,
        source=DetectionSource.THRESHOLD,
        rule_id="RULE-DROP",
        severity=Severity.MAJOR,
        current_value=4.5,
        threshold=2.0,
    )
    alarm1, _ = alarm_svc.process_anomaly(ev1)
    alarm2, _ = alarm_svc.process_anomaly(ev2)

    resp = client.get("/metrics")
    body = resp.text

    assert 'nexus_alarms_active{severity="CRITICAL"} 1.0' in body
    assert 'nexus_alarms_active{severity="MAJOR"} 1.0' in body
    assert 'nexus_alarms_active{severity="WARNING"} 0.0' in body
    assert 'nexus_alarms_total{severity="CRITICAL",status="ACTIVE"} 1.0' in body

    # Clear alarm1
    alarm_svc.clear_alarm((ev1.node_id, ev1.metric_name, ev1.rule_id, ev1.source), now)

    resp2 = client.get("/metrics")
    body2 = resp2.text

    assert 'nexus_alarms_active{severity="CRITICAL"} 0.0' in body2
    assert 'nexus_alarms_total{severity="CRITICAL",status="CLEARED"} 1.0' in body2


def test_fault_scenario_metrics_lifecycle(client: TestClient) -> None:
    """Fault scenario activation updates scenario gauge and affected nodes count."""
    fault_svc = get_fault_service()
    fault_svc.deactivate_scenario()

    # Initial state: no fault active
    resp = client.get("/metrics")
    body = resp.text
    for key in VALID_FAULT_SCENARIOS:
        assert f'nexus_fault_scenario_active{{scenario_key="{key}"}} 0.0' in body
    assert "nexus_fault_affected_nodes_count 0.0" in body

    # Activate radio_interference scenario
    act_resp = client.post("/api/v1/faults/scenarios/radio_interference/activate")
    assert act_resp.status_code == 200

    resp_active = client.get("/metrics")
    body_active = resp_active.text
    assert 'nexus_fault_scenario_active{scenario_key="radio_interference"} 1.0' in body_active
    assert 'nexus_fault_scenario_active{scenario_key="cell_outage"} 0.0' in body_active
    assert "nexus_fault_affected_nodes_count 1.0" in body_active

    # Deactivate scenario
    deact_resp = client.post("/api/v1/faults/scenarios/deactivate")
    assert deact_resp.status_code == 200

    resp_deact = client.get("/metrics")
    body_deact = resp_deact.text
    assert 'nexus_fault_scenario_active{scenario_key="radio_interference"} 0.0' in body_deact
    assert "nexus_fault_affected_nodes_count 0.0" in body_deact


def test_strict_bounded_cardinality_and_no_ground_truth_leakage(client: TestClient) -> None:
    """Verify that Prometheus metrics strictly maintain bounded cardinality and zero GT leakage."""
    # Generate some simulation data and activate a fault
    client.post("/api/v1/telemetry/simulate-step")
    client.post("/api/v1/faults/scenarios/cell_outage/activate")

    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text

    # 1. No dynamic node IDs in labels
    forbidden_node_ids = ["CELL-01", "CELL-05", "SITE-01", "AGG-01", "CORE-01"]
    for nid in forbidden_node_ids:
        assert f'node_id="{nid}"' not in body
        assert f'target_id="{nid}"' not in body

    # 2. No dynamic alarm or incident IDs in labels
    assert 'alarm_id="' not in body
    assert 'incident_id="' not in body

    # 3. Ground truth evaluation isolation
    # Ground truth engine concepts must NEVER leak as Prometheus metrics or labels
    assert "nexus_ground_truth" not in body
    assert "nexus_root_cause" not in body
    assert 'root_cause="' not in body
    assert 'failure_mechanism="' not in body

    # 4. Cleanup
    client.post("/api/v1/faults/scenarios/deactivate")


def test_incident_metrics_lifecycle(client: TestClient) -> None:
    """Incident metrics accurately report totals, status, severity, active counts, and SLA metrics."""
    svc = inc_api._default_service
    assert svc is not None

    from datetime import timedelta
    now = datetime.now(timezone.utc)

    inc1 = Incident(
        incident_id="INC-001",
        correlation_group_id="GRP-001",
        status=IncidentStatus.OPEN,
        severity=IncidentSeverity.CRITICAL,
        priority=IncidentPriority.P1,
        title="Critical Core Outage",
        description="Core node degradation",
        alarm_ids=("ALM-01",),
        affected_node_ids=("CORE-01",),
        suspected_cause_type=None,
        suspected_target_id=None,
        suspected_target_type=None,
        rca_confidence_score=None,
        rca_hypotheses=(),
        rca_evidence=(),
        created_at=now,
        ack_deadline=now + timedelta(minutes=15),
        resolve_deadline=now + timedelta(hours=2),
    )
    svc._repo.create(inc1)

    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text

    assert "nexus_incidents_total 1.0" in body
    assert 'nexus_incidents_by_status{status="OPEN"} 1.0' in body
    assert 'nexus_incidents_by_status{status="ACKNOWLEDGED"} 0.0' in body
    assert 'nexus_incidents_by_status{status="RESOLVED"} 0.0' in body
    assert 'nexus_incidents_by_severity{severity="CRITICAL"} 1.0' in body
    assert 'nexus_incidents_active{severity="CRITICAL"} 1.0' in body

    # Acknowledge incident
    svc.acknowledge_incident("INC-001", actor="Operator", timestamp=now + timedelta(minutes=5))

    # Invalidate cache so metrics update immediately
    get_metrics_manager()._incident_cache = None

    resp_ack = client.get("/metrics")
    body_ack = resp_ack.text
    assert 'nexus_incidents_by_status{status="OPEN"} 0.0' in body_ack
    assert 'nexus_incidents_by_status{status="ACKNOWLEDGED"} 1.0' in body_ack
    assert 'nexus_incidents_active{severity="CRITICAL"} 1.0' in body_ack
    assert "nexus_incidents_mtta_seconds 300.0" in body_ack

    # Resolve incident
    svc.resolve_incident("INC-001", actor="Operator", timestamp=now + timedelta(minutes=30))
    get_metrics_manager()._incident_cache = None

    resp_res = client.get("/metrics")
    body_res = resp_res.text
    assert 'nexus_incidents_by_status{status="OPEN"} 0.0' in body_res
    assert 'nexus_incidents_by_status{status="ACKNOWLEDGED"} 0.0' in body_res
    assert 'nexus_incidents_by_status{status="RESOLVED"} 1.0' in body_res
    assert 'nexus_incidents_active{severity="CRITICAL"} 0.0' in body_res
    assert "nexus_incidents_mttr_seconds 1800.0" in body_res
