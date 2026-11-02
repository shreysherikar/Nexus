"""End-to-end integration tests for Fault Injection, Telemetry Pipeline, and Anomaly Detection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Generator
import pytest
from fastapi.testclient import TestClient

from nexus.detection.models import Severity
from nexus.detection.service import AlarmService, get_alarm_service, set_alarm_service
from nexus.fault.service import FaultService, get_fault_service, set_fault_service
from nexus.main import create_app
from nexus.telemetry.generator import SyntheticTelemetryGenerator
from nexus.telemetry.orchestrator import TelemetryPipeline, set_telemetry_pipeline
from nexus.telemetry.store import TelemetryStore, set_telemetry_store
from nexus.topology.api import set_topology_registry
from nexus.topology.builder import build_simulated_network
from nexus.transport.builder import build_reference_transport_network


@pytest.fixture
def isolated_env() -> Generator[dict, None, None]:
    """Provide isolated topology, transport, telemetry, fault, and alarm subsystems."""
    topo = build_simulated_network()
    set_topology_registry(topo)

    transport = build_reference_transport_network(topo)

    store = TelemetryStore(topology=topo)
    set_telemetry_store(store)

    fault_svc = FaultService(topology=topo, transport=transport)
    set_fault_service(fault_svc)

    alarm_svc = AlarmService()
    set_alarm_service(alarm_svc)

    gen = SyntheticTelemetryGenerator(topology=topo, seed=42)
    pipeline = TelemetryPipeline(
        generator=gen,
        store=store,
        fault_service=fault_svc,
        alarm_service=alarm_svc,
    )
    set_telemetry_pipeline(pipeline)

    app = create_app()

    with TestClient(app) as tc:
        yield {
            "client": tc,
            "topology": topo,
            "transport": transport,
            "store": store,
            "fault_service": fault_svc,
            "alarm_service": alarm_svc,
            "pipeline": pipeline,
        }

    fault_svc.deactivate_scenario()
    store.clear()


class TestFaultIntegrationEndToEnd:
    """Verify fault scenario activation, telemetry transformation, detection, and ground-truth isolation."""

    def test_fault_scenarios_listing_and_metadata(self, isolated_env: dict) -> None:
        """GET /api/v1/faults/scenarios lists all 5 predefined reference scenarios with accurate metadata."""
        client: TestClient = isolated_env["client"]

        resp = client.get("/api/v1/faults/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        items = {item["id"]: item for item in data["items"]}

        # 1. Cell Outage
        assert "cell_outage" in items
        assert items["cell_outage"]["target_id"] == "CELL-01"
        assert items["cell_outage"]["fault_type"] == "CELL_OUTAGE"
        assert items["cell_outage"]["severity"] == 1.0

        # 2. Backhaul Failure
        assert "backhaul_failure" in items
        assert items["backhaul_failure"]["target_id"] == "LINK-AGG-01-SITE-01"
        assert items["backhaul_failure"]["fault_type"] == "BACKHAUL_FAILURE"

        # 3. Radio Interference
        assert "radio_interference" in items
        assert items["radio_interference"]["target_id"] == "CELL-05"
        assert items["radio_interference"]["fault_type"] == "RADIO_INTERFERENCE"
        assert items["radio_interference"]["severity"] == 0.8
        assert items["radio_interference"]["affected_nodes"] == ["CELL-05"]

        # 4. Cell Congestion
        assert "cell_congestion" in items
        assert items["cell_congestion"]["target_id"] == "CELL-10"
        assert items["cell_congestion"]["fault_type"] == "CELL_CONGESTION"

        # 5. Site Power Failure
        assert "site_power_failure" in items
        assert items["site_power_failure"]["target_id"] == "SITE-04"
        assert items["site_power_failure"]["fault_type"] == "SITE_POWER_FAILURE"

    def test_activate_and_deactivate_scenario_via_api(self, isolated_env: dict) -> None:
        """API endpoints allow safe activation and deactivation of fault scenarios."""
        client: TestClient = isolated_env["client"]

        # Initially no active scenario
        active_resp = client.get("/api/v1/faults/active")
        assert active_resp.status_code == 200
        assert active_resp.json()["active"] is False

        # Activate radio_interference
        act_resp = client.post("/api/v1/faults/scenarios/radio_interference/activate")
        assert act_resp.status_code == 200
        act_data = act_resp.json()
        assert act_data["success"] is True
        assert act_data["active_scenario"]["active"] is True
        assert act_data["active_scenario"]["scenario_key"] == "radio_interference"
        assert act_data["active_scenario"]["faults"][0]["target_id"] == "CELL-05"

        # Verify active state endpoint
        active_resp2 = client.get("/api/v1/faults/active")
        assert active_resp2.status_code == 200
        assert active_resp2.json()["active"] is True
        assert active_resp2.json()["scenario_key"] == "radio_interference"

        # Deactivate
        deact_resp = client.post("/api/v1/faults/scenarios/deactivate")
        assert deact_resp.status_code == 200
        assert deact_resp.json()["active_scenario"]["active"] is False

        # Confirmed inactive
        active_resp3 = client.get("/api/v1/faults/active")
        assert active_resp3.json()["active"] is False

    def test_radio_interference_on_cell05_modulates_metrics_and_spares_unaffected_cells(
        self, isolated_env: dict
    ) -> None:
        """Prove that radio interference on CELL-05 degrades SINR, throughput, and handover/drop,
        while other cells (e.g. CELL-01, CELL-02, CELL-06) remain unaffected at baseline values.
        """
        client: TestClient = isolated_env["client"]
        pipeline: TelemetryPipeline = isolated_env["pipeline"]

        # Step 1: Generate nominal baseline step (no active faults)
        ts_baseline = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        baseline_snaps = pipeline.generate_step(timestamp=ts_baseline)
        baseline_by_node = {s.node_id: s for s in baseline_snaps}

        cell05_base = baseline_by_node["CELL-05"]
        cell01_base = baseline_by_node["CELL-01"]
        cell06_base = baseline_by_node["CELL-06"]

        assert cell05_base.radio is not None
        assert cell05_base.radio.sinr_db >= 15.0  # nominal healthy SINR
        assert cell05_base.performance.throughput_mbps > 20.0
        assert cell05_base.reliability.connection_drop_rate_pct < 1.0

        # Step 2: Activate radio_interference scenario on CELL-05 (severity 0.8)
        act_resp = client.post("/api/v1/faults/scenarios/radio_interference/activate")
        assert act_resp.status_code == 200

        # Step 3: Generate next step under active fault
        ts_faulted = datetime(2026, 11, 2, 10, 1, 0, tzinfo=timezone.utc)
        faulted_snaps = pipeline.generate_step(timestamp=ts_faulted)
        faulted_by_node = {s.node_id: s for s in faulted_snaps}

        cell05_faulted = faulted_by_node["CELL-05"]
        cell01_faulted = faulted_by_node["CELL-01"]
        cell06_faulted = faulted_by_node["CELL-06"]

        # A. Assert CELL-05 metrics experienced expected degradation:
        # 1. SINR degraded by severity * 20 dB = 16 dB penalty
        assert cell05_faulted.radio is not None
        sinr_drop = cell05_base.radio.sinr_db - cell05_faulted.radio.sinr_db
        assert 14.0 <= sinr_drop <= 18.0

        # 2. Throughput degraded by ~52% (severity 0.8 * 0.65 = 0.52 reduction)
        tp_ratio = cell05_faulted.performance.throughput_mbps / cell05_base.performance.throughput_mbps
        assert tp_ratio <= 0.60

        # 3. Connection drop rate increased by severity * 5.0 = +4.0%
        drop_increase = (
            cell05_faulted.reliability.connection_drop_rate_pct
            - cell05_base.reliability.connection_drop_rate_pct
        )
        assert drop_increase >= 3.5

        # 4. Handover success rate decreased by severity * 15.0 = -12.0%
        if cell05_faulted.reliability.handover_success_rate_pct is not None:
            assert cell05_faulted.reliability.handover_success_rate_pct < 90.0

        # B. Assert UNAFFECTED cells (CELL-01, CELL-06) remain unchanged (no fault impact):
        assert cell01_faulted.radio is not None
        assert cell06_faulted.radio is not None
        assert cell01_faulted.radio.sinr_db >= 14.0
        assert cell06_faulted.radio.sinr_db >= 14.0
        assert cell01_faulted.performance.throughput_mbps > 20.0
        assert cell06_faulted.performance.throughput_mbps > 20.0

        # C. Verify detection created alarms on CELL-05 and zero alarms on unaffected cells:
        alarms_resp = client.get("/api/v1/alarms?status=ACTIVE")
        assert alarms_resp.status_code == 200
        active_alarms = alarms_resp.json()["items"]

        # CELL-05 must have active alarm(s) (e.g. RULE-HOSR-MAJOR or RULE-SINR-MAJOR)
        cell05_alarms = [a for a in active_alarms if a["node_id"] == "CELL-05"]
        assert len(cell05_alarms) >= 1
        hosr_alarm = next((a for a in cell05_alarms if a["rule_id"] == "RULE-HOSR-MAJOR"), None)
        assert hosr_alarm is not None
        assert hosr_alarm["severity"] == "MAJOR"
        assert hosr_alarm["current_value"] < 90.0

        # Zero alarms on unaffected CELL-01 and CELL-06
        unaffected_alarms = [a for a in active_alarms if a["node_id"] in ("CELL-01", "CELL-06")]
        assert len(unaffected_alarms) == 0

    def test_cell_outage_fault_creates_critical_alarms(self, isolated_env: dict) -> None:
        """Cell outage on CELL-01 produces zero availability and critical availability/drop alarms."""
        client: TestClient = isolated_env["client"]
        pipeline: TelemetryPipeline = isolated_env["pipeline"]

        # Activate cell_outage
        client.post("/api/v1/faults/scenarios/cell_outage/activate")

        # Generate step
        step_resp = client.post("/api/v1/telemetry/generate-step")
        assert step_resp.status_code == 200

        # Query latest telemetry for CELL-01
        telem_resp = client.get("/api/v1/telemetry?node_id=CELL-01&limit=1")
        assert telem_resp.status_code == 200
        cell01_snap = telem_resp.json()["items"][0]

        assert cell01_snap["reliability"]["availability_pct"] == 0.0
        assert cell01_snap["reliability"]["connection_drop_rate_pct"] == 100.0
        assert cell01_snap["performance"]["throughput_mbps"] == 0.0

        # Check critical alarms triggered
        alarms_resp = client.get("/api/v1/alarms?node_id=CELL-01")
        assert alarms_resp.status_code == 200
        alarms = alarms_resp.json()["items"]
        rule_ids = {a["rule_id"] for a in alarms}
        assert "RULE-AVAIL-CRIT" in rule_ids
        assert "RULE-DROP-CRIT" in rule_ids

    def test_fault_lifecycle_activation_impairment_deactivation_recovery(
        self, isolated_env: dict
    ) -> None:
        """Verify full lifecycle: activation -> impairment -> deactivation -> nominal recovery,
        verifying that subsequent simulation steps restore baseline metrics, clear active alarms,
        and serve non-cached responses with honest observation timestamps.
        """
        client: TestClient = isolated_env["client"]

        # Phase 1: Baseline nominal generation
        base_step_resp = client.post("/api/v1/telemetry/generate-step")
        assert base_step_resp.status_code == 200
        ts_base = base_step_resp.json()["timestamp"]

        telem_base_resp = client.get("/api/v1/telemetry?node_id=CELL-05&limit=1")
        assert telem_base_resp.status_code == 200
        assert "no-store" in telem_base_resp.headers.get("cache-control", "")
        cell05_base = telem_base_resp.json()["items"][0]
        assert cell05_base["timestamp"] == ts_base
        assert cell05_base["radio"]["sinr_db"] >= 15.0
        assert cell05_base["performance"]["throughput_mbps"] >= 150.0
        assert cell05_base["reliability"]["connection_drop_rate_pct"] < 1.0

        # Phase 2: Activate Radio Interference (CELL-05, severity 0.8)
        act_resp = client.post("/api/v1/faults/scenarios/radio_interference/activate")
        assert act_resp.status_code == 200
        assert act_resp.json()["active_scenario"]["active"] is True

        # Generate faulted simulation step
        fault_step_resp = client.post("/api/v1/telemetry/generate-step")
        assert fault_step_resp.status_code == 200
        ts_faulted = fault_step_resp.json()["timestamp"]
        assert ts_faulted != ts_base

        telem_fault_resp = client.get("/api/v1/telemetry?node_id=CELL-05&limit=1")
        assert telem_fault_resp.status_code == 200
        cell05_fault = telem_fault_resp.json()["items"][0]
        assert cell05_fault["timestamp"] == ts_faulted

        # Check impaired metrics
        sinr_drop = cell05_base["radio"]["sinr_db"] - cell05_fault["radio"]["sinr_db"]
        assert 14.0 <= sinr_drop <= 18.0
        assert cell05_fault["performance"]["throughput_mbps"] <= cell05_base["performance"]["throughput_mbps"] * 0.60
        assert cell05_fault["reliability"]["connection_drop_rate_pct"] >= 3.5

        # Check active alarm on CELL-05
        active_alarms_resp = client.get("/api/v1/alarms?node_id=CELL-05&status=ACTIVE")
        assert active_alarms_resp.status_code == 200
        active_rules = {a["rule_id"] for a in active_alarms_resp.json()["items"]}
        assert "RULE-HOSR-MAJOR" in active_rules

        # Phase 3: Deactivate Scenario
        deact_resp = client.post("/api/v1/faults/scenarios/deactivate")
        assert deact_resp.status_code == 200
        assert deact_resp.json()["active_scenario"]["active"] is False

        # Phase 4: Generate Recovery Simulation Step
        recov_step_resp = client.post("/api/v1/telemetry/generate-step")
        assert recov_step_resp.status_code == 200
        ts_recov = recov_step_resp.json()["timestamp"]
        assert ts_recov != ts_faulted

        # Query latest telemetry for CELL-05
        telem_recov_resp = client.get("/api/v1/telemetry?node_id=CELL-05&limit=1")
        assert telem_recov_resp.status_code == 200
        cell05_recov = telem_recov_resp.json()["items"][0]

        # CELL-05 must have the new recovery timestamp
        assert cell05_recov["timestamp"] == ts_recov

        # CELL-05 metrics must be restored to nominal baseline values
        assert cell05_recov["radio"]["sinr_db"] >= 15.0
        assert cell05_recov["performance"]["throughput_mbps"] >= 150.0
        assert cell05_recov["reliability"]["connection_drop_rate_pct"] < 1.0

        # Query total observations for CELL-05
        all_cell05_resp = client.get("/api/v1/telemetry?node_id=CELL-05&limit=10")
        assert all_cell05_resp.status_code == 200
        cell05_all = all_cell05_resp.json()["items"]
        assert len(cell05_all) == 3
        # Chronological timestamps in response (newest first)
        assert cell05_all[0]["timestamp"] == ts_recov
        assert cell05_all[1]["timestamp"] == ts_faulted
        assert cell05_all[2]["timestamp"] == ts_base

        # Active alarms on CELL-05 must be empty (alarm cleared)
        post_active_alarms = client.get("/api/v1/alarms?node_id=CELL-05&status=ACTIVE").json()["items"]
        assert len(post_active_alarms) == 0

        # All alarms list shows the alarm as CLEARED
        all_alarms = client.get("/api/v1/alarms?node_id=CELL-05").json()["items"]
        hosr_alarm = next((a for a in all_alarms if a["rule_id"] == "RULE-HOSR-MAJOR"), None)
        assert hosr_alarm is not None
        assert hosr_alarm["status"] == "CLEARED"
