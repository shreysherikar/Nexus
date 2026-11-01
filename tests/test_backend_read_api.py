"""Integration tests for NEXUS M7.2 Backend Read APIs (Topology, Telemetry, Alarms)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Generator
import pytest
from fastapi.testclient import TestClient

from nexus.detection.models import (
    AlarmStatus,
    AnomalyEvent,
    DetectionSource,
    Severity,
)
from nexus.detection.service import AlarmService, get_alarm_service, set_alarm_service
from nexus.incidents.api import app
from nexus.telemetry.generator import SyntheticTelemetryGenerator
from nexus.telemetry.models import (
    KPISnapshot,
    PerformanceMetrics,
    RadioMetrics,
    ReliabilityMetrics,
)
from nexus.telemetry.orchestrator import TelemetryPipeline, set_telemetry_pipeline
from nexus.telemetry.store import TelemetryStore, get_telemetry_store, set_telemetry_store
from nexus.topology.builder import build_simulated_network
from nexus.topology.enums import NodeStatus, NodeType
from nexus.topology.topology import Topology
from nexus.topology.api import get_topology_registry, set_topology_registry


@pytest.fixture(autouse=True)
def isolated_stores_and_services() -> Generator[None, None, None]:
    """Provide freshly isolated topology, telemetry, and alarm stores for each test."""
    test_topo = build_simulated_network()
    set_topology_registry(test_topo)

    test_telemetry = TelemetryStore(topology=test_topo)
    set_telemetry_store(test_telemetry)

    test_gen = SyntheticTelemetryGenerator(topology=test_topo)
    test_pipeline = TelemetryPipeline(generator=test_gen, store=test_telemetry)
    set_telemetry_pipeline(test_pipeline)

    test_alarm_service = AlarmService()
    set_alarm_service(test_alarm_service)

    yield

    test_telemetry.clear()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """TestClient wired to isolated registries."""
    with TestClient(app) as test_client:
        yield test_client


class TestTopologyReadAPI:
    """Tests validating the GET /api/v1/topology endpoint."""

    def test_get_topology_reference_27_nodes(self, client: TestClient) -> None:
        """GET /api/v1/topology returns exactly 27 reference nodes with correct tiers."""
        resp = client.get("/api/v1/topology")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_nodes"] == 27
        assert len(data["nodes"]) == 27
        assert data["tiers"] == {
            "CORE": 1,
            "AGGREGATION": 2,
            "SITE": 6,
            "CELL": 18,
        }

    def test_topology_parent_child_relationships(self, client: TestClient) -> None:
        """Children list and parent_id reflect true topology hierarchy."""
        resp = client.get("/api/v1/topology")
        assert resp.status_code == 200
        data = resp.json()

        nodes_by_id = {n["node_id"]: n for n in data["nodes"]}

        # Core node
        core = nodes_by_id["CORE-01"]
        assert core["parent_id"] is None
        assert sorted(core["children"]) == ["AGG-01", "AGG-02"]

        # Aggregation nodes
        agg1 = nodes_by_id["AGG-01"]
        assert agg1["parent_id"] == "CORE-01"
        assert sorted(agg1["children"]) == ["SITE-01", "SITE-02", "SITE-03"]

        # Site nodes
        site1 = nodes_by_id["SITE-01"]
        assert site1["parent_id"] == "AGG-01"
        assert len(site1["children"]) == 3
        assert all(c.startswith("CELL-") for c in site1["children"])

        # Cell nodes
        cell1 = nodes_by_id["CELL-01"]
        assert cell1["parent_id"] == "SITE-01"
        assert cell1["children"] == []

    def test_missing_coordinates_return_null(self, client: TestClient) -> None:
        """Nodes without physical coordinates must return null, never fabricated positions."""
        resp = client.get("/api/v1/topology")
        assert resp.status_code == 200
        data = resp.json()

        for node in data["nodes"]:
            assert node["latitude"] is None
            assert node["longitude"] is None

    def test_genuine_coordinates_returned_when_set(self, client: TestClient) -> None:
        """When genuine coordinates are configured, they are serialized accurately."""
        topo = get_topology_registry()
        topo.update_node_coordinates("SITE-01", latitude=37.7749, longitude=-122.4194)

        resp = client.get("/api/v1/topology")
        assert resp.status_code == 200
        data = resp.json()

        site1 = next(n for n in data["nodes"] if n["node_id"] == "SITE-01")
        assert site1["latitude"] == 37.7749
        assert site1["longitude"] == -122.4194

        # Other nodes remain null
        core = next(n for n in data["nodes"] if n["node_id"] == "CORE-01")
        assert core["latitude"] is None
        assert core["longitude"] is None


class TestTelemetryReadAPI:
    """Tests validating the GET /api/v1/telemetry endpoint."""

    def test_empty_telemetry_returns_empty_envelope(self, client: TestClient) -> None:
        """When buffer is empty, returns empty list without error or synthetic data."""
        resp = client.get("/api/v1/telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["limit"] == 50
        assert data["offset"] == 0

    def test_real_snapshot_serialization_cell_and_core(self, client: TestClient) -> None:
        """Cell snapshots include radio metrics; Core snapshots have null radio metrics."""
        store = get_telemetry_store()
        t1 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 1, 12, 5, 0, tzinfo=timezone.utc)

        # 1. Radio cell snapshot (CELL-01)
        cell_snap = KPISnapshot(
            node_id="CELL-01",
            timestamp=t1,
            performance=PerformanceMetrics(throughput_mbps=85.5, latency_ms=18.2),
            reliability=ReliabilityMetrics(
                connection_drop_rate_pct=0.4,
                availability_pct=99.8,
                handover_success_rate_pct=98.5,
            ),
            radio=RadioMetrics(rsrp_dbm=-88.0, sinr_db=15.5, prb_utilization_pct=62.0),
        )

        # 2. Backbone core snapshot (CORE-01) - no radio metrics, no handover
        core_snap = KPISnapshot(
            node_id="CORE-01",
            timestamp=t2,
            performance=PerformanceMetrics(throughput_mbps=12500.0, latency_ms=1.1),
            reliability=ReliabilityMetrics(
                connection_drop_rate_pct=0.0,
                availability_pct=100.0,
                handover_success_rate_pct=None,
            ),
            radio=None,
        )

        store.record(cell_snap)
        store.record(core_snap)

        resp = client.get("/api/v1/telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

        # Deterministic order: t2 (newest) first, then t1
        core_item = data["items"][0]
        assert core_item["node_id"] == "CORE-01"
        assert core_item["performance"]["throughput_mbps"] == 12500.0
        assert core_item["reliability"]["handover_success_rate_pct"] is None
        assert core_item["radio"] is None  # Missing remains null, not zero!

        cell_item = data["items"][1]
        assert cell_item["node_id"] == "CELL-01"
        assert cell_item["radio"]["rsrp_dbm"] == -88.0
        assert cell_item["reliability"]["handover_success_rate_pct"] == 98.5

    def test_filtering_by_node_id(self, client: TestClient) -> None:
        """Filter by node_id returns only matching snapshots."""
        store = get_telemetry_store()
        t = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(1, 4):
            store.record(
                KPISnapshot(
                    node_id=f"CELL-0{i}",
                    timestamp=t,
                    performance=PerformanceMetrics(throughput_mbps=50.0, latency_ms=20.0),
                    reliability=ReliabilityMetrics(connection_drop_rate_pct=1.0, availability_pct=99.0),
                )
            )

        resp = client.get("/api/v1/telemetry?node_id=CELL-02")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["node_id"] == "CELL-02"

    def test_filtering_by_node_type(self, client: TestClient) -> None:
        """Filter by node_type selects nodes belonging to that tier."""
        store = get_telemetry_store()
        t = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

        store.record(
            KPISnapshot(
                node_id="CORE-01",
                timestamp=t,
                performance=PerformanceMetrics(100.0, 1.0),
                reliability=ReliabilityMetrics(0.0, 100.0),
            )
        )
        store.record(
            KPISnapshot(
                node_id="SITE-01",
                timestamp=t,
                performance=PerformanceMetrics(100.0, 5.0),
                reliability=ReliabilityMetrics(0.0, 100.0),
            )
        )

        resp = client.get("/api/v1/telemetry?node_type=SITE")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["node_id"] == "SITE-01"

    def test_invalid_node_type_returns_422(self, client: TestClient) -> None:
        """Invalid node_type filter parameter returns HTTP 422."""
        resp = client.get("/api/v1/telemetry?node_type=SATELLITE")
        assert resp.status_code == 422

    def test_time_range_filtering_and_validation(self, client: TestClient) -> None:
        """Valid time range bounds snapshots; inverted range returns 422."""
        store = get_telemetry_store()
        t1 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 1, 11, 0, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

        for t, nid in [(t1, "CELL-01"), (t2, "CELL-02"), (t3, "CELL-03")]:
            store.record(
                KPISnapshot(
                    node_id=nid,
                    timestamp=t,
                    performance=PerformanceMetrics(10.0, 10.0),
                    reliability=ReliabilityMetrics(0.0, 100.0),
                )
            )

        resp = client.get(
            "/api/v1/telemetry?start_time=2026-11-01T10:30:00Z&end_time=2026-11-01T11:30:00Z"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["node_id"] == "CELL-02"

        # Inverted range
        bad_resp = client.get(
            "/api/v1/telemetry?start_time=2026-11-01T12:00:00Z&end_time=2026-11-01T10:00:00Z"
        )
        assert bad_resp.status_code == 422

    def test_pagination_limit_and_offset(self, client: TestClient) -> None:
        """Limit and offset paginate snapshots deterministically."""
        store = get_telemetry_store()
        base_t = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(10):
            store.record(
                KPISnapshot(
                    node_id=f"CELL-{i:02d}",
                    timestamp=base_t + timedelta(minutes=i),
                    performance=PerformanceMetrics(10.0, 10.0),
                    reliability=ReliabilityMetrics(0.0, 100.0),
                )
            )

        resp = client.get("/api/v1/telemetry?limit=3&offset=2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        assert data["limit"] == 3
        assert data["offset"] == 2
        assert len(data["items"]) == 3


class TestAlarmReadAPI:
    """Tests validating the GET /api/v1/alarms endpoint."""

    def test_empty_alarms_returns_empty_envelope(self, client: TestClient) -> None:
        """When no alarms are present, returns empty items with total=0."""
        resp = client.get("/api/v1/alarms")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["limit"] == 50
        assert data["offset"] == 0

    def test_real_alarm_serialization(self, client: TestClient) -> None:
        """Real Alarm record fields serialize accurately to response schema."""
        service = get_alarm_service()
        event = AnomalyEvent(
            node_id="CELL-03",
            metric_name="availability_pct",
            timestamp=datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc),
            source=DetectionSource.THRESHOLD,
            rule_id="RULE-AVAIL-CRIT",
            severity=Severity.CRITICAL,
            current_value=84.2,
            threshold=95.0,
            description="Availability below 95.0%",
            evidence={"consecutive_breaches": 2},
        )
        alarm, is_new = service.process_anomaly(event)
        assert is_new is True

        resp = client.get("/api/v1/alarms")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        item = data["items"][0]

        assert item["alarm_id"] == alarm.alarm_id
        assert item["node_id"] == "CELL-03"
        assert item["rule_id"] == "RULE-AVAIL-CRIT"
        assert item["metric_name"] == "availability_pct"
        assert item["source"] == "THRESHOLD"
        assert item["severity"] == "CRITICAL"
        assert item["current_value"] == 84.2
        assert item["threshold"] == 95.0
        assert item["observation_count"] == 1
        assert item["status"] == "ACTIVE"
        assert item["cleared_at"] is None
        assert item["evidence"]["consecutive_breaches"] == 2

    def test_filter_by_severity_and_status(self, client: TestClient) -> None:
        """Filter by severity and active/cleared status."""
        service = get_alarm_service()
        t = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Critical alarm
        service.process_anomaly(
            AnomalyEvent(
                node_id="CELL-01",
                metric_name="availability_pct",
                timestamp=t,
                source=DetectionSource.THRESHOLD,
                rule_id="RULE-AVAIL-CRIT",
                severity=Severity.CRITICAL,
                current_value=80.0,
                threshold=95.0,
            )
        )

        # 2. Major alarm
        alarm2, _ = service.process_anomaly(
            AnomalyEvent(
                node_id="SITE-01",
                metric_name="latency_ms",
                timestamp=t,
                source=DetectionSource.THRESHOLD,
                rule_id="RULE-LAT-MAJOR",
                severity=Severity.MAJOR,
                current_value=95.0,
                threshold=80.0,
            )
        )

        # Clear the major alarm
        key = ("SITE-01", "latency_ms", "RULE-LAT-MAJOR", DetectionSource.THRESHOLD)
        service.clear_alarm(key, t + timedelta(minutes=5))

        # Filter by severity=CRITICAL
        resp_crit = client.get("/api/v1/alarms?severity=CRITICAL")
        assert resp_crit.status_code == 200
        crit_data = resp_crit.json()
        assert crit_data["total"] == 1
        assert crit_data["items"][0]["severity"] == "CRITICAL"

        # Filter by status=ACTIVE
        resp_act = client.get("/api/v1/alarms?status=ACTIVE")
        assert resp_act.status_code == 200
        act_data = resp_act.json()
        assert act_data["total"] == 1
        assert act_data["items"][0]["status"] == "ACTIVE"

        # Filter by status=CLEARED
        resp_clr = client.get("/api/v1/alarms?status=CLEARED")
        assert resp_clr.status_code == 200
        clr_data = resp_clr.json()
        assert clr_data["total"] == 1
        assert clr_data["items"][0]["status"] == "CLEARED"

    def test_invalid_severity_and_status_return_422(self, client: TestClient) -> None:
        """Invalid severity or status queries return HTTP 422."""
        assert client.get("/api/v1/alarms?severity=FATAL").status_code == 422
        assert client.get("/api/v1/alarms?status=PENDING").status_code == 422


class TestTelemetryPipelineIntegration:
    """Validate genuine generator-to-store integration and pipeline deduplication."""

    def test_generator_step_populates_store_and_read_api(self, client: TestClient) -> None:
        """Generator produces snapshots that reach the store and are queryable via REST."""
        from nexus.telemetry.generator import SyntheticTelemetryGenerator
        from nexus.telemetry.orchestrator import TelemetryPipeline

        topo = get_topology_registry()
        store = get_telemetry_store()
        gen = SyntheticTelemetryGenerator(topology=topo, seed=42)
        pipeline = TelemetryPipeline(generator=gen, store=store)

        t0 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        snapshots = pipeline.generate_step(timestamp=t0)
        assert len(snapshots) == 27
        assert store.count == 27

        # REST API returns those exact snapshots without mock fabrication
        resp = client.get("/api/v1/telemetry?limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 27
        assert len(data["items"]) == 27

        # Verify radio is None for core nodes and present for cell nodes
        core_items = [i for i in data["items"] if i["node_id"] == "CORE-01"]
        assert len(core_items) == 1
        assert core_items[0]["radio"] is None

        cell_items = [i for i in data["items"] if i["node_id"].startswith("CELL-")]
        assert len(cell_items) == 18
        for cell in cell_items:
            assert cell["radio"] is not None

    def test_pipeline_duplicate_generation_prevents_duplicate_store_records(self) -> None:
        """Repeated generation with identical timestamps does not create duplicate store entries."""
        from nexus.telemetry.generator import SyntheticTelemetryGenerator
        from nexus.telemetry.orchestrator import TelemetryPipeline

        topo = get_topology_registry()
        store = get_telemetry_store()
        gen = SyntheticTelemetryGenerator(topology=topo, seed=42)
        pipeline = TelemetryPipeline(generator=gen, store=store)

        t0 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        pipeline.generate_step(timestamp=t0)
        assert store.count == 27

        # Re-invoke with identical timestamp
        pipeline.generate_step(timestamp=t0)
        assert store.count == 27  # Exactly 27, no duplicates

        # New step with new timestamp increments properly
        t1 = datetime(2026, 11, 1, 12, 1, 0, tzinfo=timezone.utc)
        pipeline.generate_step(timestamp=t1)
        assert store.count == 54

    def test_pipeline_step_emits_telemetry_snapshot_events(self) -> None:
        """Pipeline stepping emits authentic TELEMETRY_SNAPSHOT events and avoids duplicate emits."""
        from nexus.telemetry.generator import SyntheticTelemetryGenerator
        from nexus.telemetry.orchestrator import TelemetryPipeline

        topo = get_topology_registry()
        store = get_telemetry_store()
        published: list[tuple[str, dict]] = []
        store.set_event_publisher(lambda t, p: published.append((t, p)))

        gen = SyntheticTelemetryGenerator(topology=topo, seed=42)
        pipeline = TelemetryPipeline(generator=gen, store=store)

        t0 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        pipeline.generate_step(timestamp=t0)

        assert len(published) == 27
        assert all(t == "TELEMETRY_SNAPSHOT" for t, _ in published)
        node_ids_emitted = {p["node_id"] for _, p in published}
        assert len(node_ids_emitted) == 27

        # Re-invoke with same timestamp: no duplicate events emitted
        pipeline.generate_step(timestamp=t0)
        assert len(published) == 27


class TestConcurrentTelemetryStore:
    """Stress test TelemetryStore thread safety under concurrent readers and writers."""

    def test_concurrent_reads_and_writes(self) -> None:
        """Multiple threads concurrently writing and querying store execute safely without deadlock."""
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from nexus.telemetry.models import KPISnapshot, PerformanceMetrics, ReliabilityMetrics

        store = TelemetryStore(max_capacity=500)
        errors: list[Exception] = []

        def writer_task(thread_id: int) -> None:
            try:
                base_time = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
                for i in range(50):
                    ts = base_time + timedelta(seconds=thread_id * 100 + i)
                    snap = KPISnapshot(
                        node_id=f"CELL-{thread_id:02d}",
                        timestamp=ts,
                        performance=PerformanceMetrics(throughput_mbps=100.0, latency_ms=10.0),
                        reliability=ReliabilityMetrics(
                            connection_drop_rate_pct=0.1, availability_pct=99.9
                        ),
                    )
                    store.record(snap)
            except Exception as e:
                errors.append(e)

        def reader_task() -> None:
            try:
                for _ in range(50):
                    items, total = store.query(limit=20)
                    _ = store.count
                    _ = store.capacity
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for w in range(5):
                futures.append(executor.submit(writer_task, w))
            for _ in range(5):
                futures.append(executor.submit(reader_task))
            for f in futures:
                f.result()

        assert len(errors) == 0
        assert store.count == 250


class TestBackendReadExtensions:
    """Test newly extended backend endpoints: single node, single alarm, and generate-step."""

    def test_get_topology_single_node(self, client: TestClient) -> None:
        """GET /api/v1/topology/nodes/{node_id} returns single node with children."""
        resp = client.get("/api/v1/topology/nodes/AGG-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] == "AGG-01"
        assert data["node_type"] == "AGGREGATION"
        assert data["parent_id"] == "CORE-01"
        assert "SITE-01" in data["children"]

        resp_404 = client.get("/api/v1/topology/nodes/NON-EXISTENT")
        assert resp_404.status_code == 404

    def test_get_alarm_by_id(self, client: TestClient) -> None:
        """GET /api/v1/alarms/{alarm_id} returns alarm details or 404."""
        service = get_alarm_service()
        anomaly = AnomalyEvent(
            node_id="CELL-01",
            metric_name="latency_ms",
            current_value=125.0,
            threshold=80.0,
            severity=Severity.MAJOR,
            source=DetectionSource.THRESHOLD,
            rule_id="RULE-LAT-01",
            timestamp=datetime.now(timezone.utc),
            description="High latency detected",
        )
        alarm, _ = service.process_anomaly(anomaly)

        resp = client.get(f"/api/v1/alarms/{alarm.alarm_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["alarm_id"] == alarm.alarm_id
        assert data["node_id"] == "CELL-01"
        assert data["metric_name"] == "latency_ms"
        assert data["severity"] == "MAJOR"

        resp_404 = client.get("/api/v1/alarms/NON-EXISTENT-ALARM")
        assert resp_404.status_code == 404

    def test_generate_telemetry_step_endpoint(self, client: TestClient) -> None:
        """POST /api/v1/telemetry/generate-step generates exactly 27 snapshots into store."""
        resp = client.post("/api/v1/telemetry/generate-step")
        assert resp.status_code == 200
        data = resp.json()
        assert data["generated_count"] == 27
        assert "timestamp" in data
        assert "Deterministic simulation step" in data["message"]

        # Verify store now has 27 snapshots
        store_resp = client.get("/api/v1/telemetry?limit=50")
        assert store_resp.status_code == 200
        assert store_resp.json()["total"] == 27


class TestDetectionRulesApi:
    """Tests for GET /api/v1/detection/rules endpoint."""

    def test_get_detection_rules(self, client: TestClient) -> None:
        """GET /api/v1/detection/rules returns authoritative configured threshold rules."""
        resp = client.get("/api/v1/detection/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 8
        items = data["items"]
        assert len(items) == 8

        rules_by_id = {r["rule_id"]: r for r in items}

        # Verify all 8 default rules
        assert "RULE-AVAIL-CRIT" in rules_by_id
        r_avail = rules_by_id["RULE-AVAIL-CRIT"]
        assert r_avail["metric_name"] == "availability_pct"
        assert r_avail["operator"] == "<"
        assert r_avail["threshold"] == 95.0
        assert r_avail["clear_threshold"] == 98.0
        assert r_avail["severity"] == "CRITICAL"
        assert r_avail["node_types"] is None
        assert r_avail["enabled"] is True

        assert "RULE-DROP-CRIT" in rules_by_id
        r_drop = rules_by_id["RULE-DROP-CRIT"]
        assert r_drop["metric_name"] == "connection_drop_rate_pct"
        assert r_drop["operator"] == ">"
        assert r_drop["threshold"] == 5.0
        assert r_drop["clear_threshold"] == 2.0
        assert r_drop["severity"] == "CRITICAL"
        assert r_drop["node_types"] is None
        assert r_drop["enabled"] is True

        assert "RULE-LAT-MAJOR" in rules_by_id
        r_lat = rules_by_id["RULE-LAT-MAJOR"]
        assert r_lat["metric_name"] == "latency_ms"
        assert r_lat["operator"] == ">"
        assert r_lat["threshold"] == 80.0
        assert r_lat["clear_threshold"] == 60.0
        assert r_lat["severity"] == "MAJOR"
        assert r_lat["node_types"] is None
        assert r_lat["enabled"] is True

        assert "RULE-PRB-MAJOR" in rules_by_id
        r_prb = rules_by_id["RULE-PRB-MAJOR"]
        assert r_prb["metric_name"] == "prb_utilization_pct"
        assert r_prb["operator"] == ">"
        assert r_prb["threshold"] == 85.0
        assert r_prb["clear_threshold"] == 75.0
        assert r_prb["severity"] == "MAJOR"
        assert r_prb["node_types"] == ["CELL"]
        assert r_prb["enabled"] is True

        assert "RULE-SINR-MAJOR" in rules_by_id
        r_sinr = rules_by_id["RULE-SINR-MAJOR"]
        assert r_sinr["metric_name"] == "sinr_db"
        assert r_sinr["operator"] == "<"
        assert r_sinr["threshold"] == 5.0
        assert r_sinr["clear_threshold"] == 8.0
        assert r_sinr["severity"] == "MAJOR"
        assert r_sinr["node_types"] == ["CELL"]
        assert r_sinr["enabled"] is True

        assert "RULE-RSRP-WARN" in rules_by_id
        r_rsrp = rules_by_id["RULE-RSRP-WARN"]
        assert r_rsrp["metric_name"] == "rsrp_dbm"
        assert r_rsrp["operator"] == "<"
        assert r_rsrp["threshold"] == -115.0
        assert r_rsrp["clear_threshold"] == -110.0
        assert r_rsrp["severity"] == "WARNING"
        assert r_rsrp["node_types"] == ["CELL"]
        assert r_rsrp["enabled"] is True

        assert "RULE-TP-WARN" in rules_by_id
        r_tp = rules_by_id["RULE-TP-WARN"]
        assert r_tp["metric_name"] == "throughput_mbps"
        assert r_tp["operator"] == "<"
        assert r_tp["threshold"] == 5.0
        assert r_tp["clear_threshold"] == 10.0
        assert r_tp["severity"] == "WARNING"
        assert r_tp["node_types"] == ["CELL"]
        assert r_tp["enabled"] is True

        assert "RULE-HOSR-MAJOR" in rules_by_id
        r_hosr = rules_by_id["RULE-HOSR-MAJOR"]
        assert r_hosr["metric_name"] == "handover_success_rate_pct"
        assert r_hosr["operator"] == "<"
        assert r_hosr["threshold"] == 90.0
        assert r_hosr["clear_threshold"] == 95.0
        assert r_hosr["severity"] == "MAJOR"
        assert r_hosr["node_types"] == ["CELL"]
        assert r_hosr["enabled"] is True

