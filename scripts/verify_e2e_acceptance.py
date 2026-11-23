"""NEXUS Comprehensive End-to-End Acceptance Test Suite.

Executes rigorous functional verification against the live Docker stack:
1. Docker Container Health: Inspects container runtime status and asserts State.Health.Status == 'healthy'.
2. Database Isolation Verification: Asserts backend is connected to nexus_test_db and primary nexus_db is untouched (122 records).
3. Backend Liveness & Readiness: HTTP /health and /ready probe verification.
4. Genuine WebSocket Handshake & Mandatory Live Event Streaming: Tests WebSocket connect,
   bidirectional PING/PONG, and mandatory live TELEMETRY_SNAPSHOT event receipt with envelope validation.
5. Topology Architecture: Validates 27-node topology (1 CORE, 2 AGGREGATION, 6 SITE, 18 CELL).
6. Six Reference Fault Scenarios Complete Lifecycle Workflows:
   - cell_outage
   - backhaul_failure
   - radio_interference
   - cell_congestion
   - site_power_failure
   - core_router_failure
   For each scenario:
   - Enforces unique execution ID binding on scenario ownership markers
   - Rejects stale markers and never deactivates unowned/operator scenarios
   - Uses initial_open_incident_ids and strictly asserts newly created incident freshness
   - Fails on ambiguous incident selection
   - Verifies correlation group and creation timeline event
   - Generates telemetry and verifies scenario-specific KPI degradation bounds
   - Verifies detection and newly generated scenario-specific alarm IDs
   - Verifies automated incident creation with non-empty correlation_group_id and RCA hypotheses
   - Asserts incident alarm_ids correspond directly to newly generated scenario alarms
   - Verifies deduplication by incident identity across repeated simulation steps
   - Verifies incident acknowledge transition
   - Deactivates fault scenario
   - Verifies network recovery as a strict PASS/FAIL gate (KPI normalization & alarm clearance)
   - Verifies incident resolve transition and timeline audit trail
7. Observability Verification:
   - Prometheus: asserts scrape target health is 'up' and executes PromQL queries validating vectors
   - Grafana: verifies datasource, requires all 5 expected dashboards, extracts and executes all panel PromQL queries,
     validates result vectors without swallowing failures
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Optional

try:
    import websockets
except ImportError:
    websockets = None

TEST_OWNER_FILE = Path(".nexus_test_owner.json")

EXPECTED_DASHBOARDS = [
    "01 - NEXUS Platform & Network Overview",
    "02 - Network KPI Health",
    "03 - Alarm & Incident Overview",
    "04 - Fault Simulation & Scenario Evaluation",
    "05 - API & Infrastructure Health",
]


def log_header(title: str) -> None:
    print(f"\n======================================================================")
    print(f" {title}")
    print(f"======================================================================")


def http_request(
    url: str,
    method: str = "GET",
    data: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 10.0,
    max_retries: int = 3,
) -> tuple[int, Any]:
    req_headers = {"User-Agent": "NEXUS-Acceptance-Test"}
    if headers:
        req_headers.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    for attempt in range(max_retries):
        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode("utf-8")
                status = resp.status
                try:
                    parsed = json.loads(content)
                except Exception:
                    parsed = content
                return status, parsed
        except urllib.error.HTTPError as e:
            content = e.read().decode("utf-8")
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = content
            return e.code, parsed
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            raise


def verify_docker_health() -> dict[str, Any]:
    """Inspect Docker containers and verify container health."""
    log_header("STEP 1: Docker Container Health Inspection")
    expected_containers = {
        "nexus-backend": True,     # has healthcheck
        "nexus-frontend": True,    # has healthcheck
        "nexus-postgres": True,    # has healthcheck
        "nexus-grafana": True,     # has healthcheck
        "nexus-prometheus": False, # standard prometheus container without healthcheck
    }

    res = subprocess.run(
        ["docker", "inspect", "--format", "{{.Name}}\t{{.State.Status}}\t{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"]
        + list(expected_containers.keys()),
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"docker inspect failed: {res.stderr}")

    health_status: dict[str, dict[str, str]] = {}
    lines = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
    for line in lines:
        parts = line.split("\t")
        if len(parts) >= 2:
            raw_name = parts[0].lstrip("/")
            status = parts[1]
            health = parts[2] if len(parts) > 2 else "none"
            health_status[raw_name] = {"status": status, "health": health}
            print(f"Container '{raw_name}': status={status}, health={health}")

    for cname, req_health in expected_containers.items():
        assert cname in health_status, f"Container '{cname}' not found in inspect output"
        cinfo = health_status[cname]
        assert cinfo["status"] == "running", f"Container '{cname}' is not running (status: {cinfo['status']})"
        if req_health:
            assert cinfo["health"] == "healthy", f"Container '{cname}' health check is not 'healthy' (got: {cinfo['health']})"

    print("All required containers are running and report 'healthy' status.")
    return health_status


def verify_database_isolation() -> dict[str, Any]:
    """Verify backend is connected to isolated nexus_test_db and primary nexus_db is untouched."""
    log_header("STEP 2: Database Isolation & Integrity Verification")

    # 1. Query the actual database name used by backend runtime
    res = subprocess.run(
        [
            "docker", "exec", "nexus-backend",
            "python", "-c",
            "from nexus.incidents.api import get_incident_service; print(get_incident_service()._repo._session_factory.kw['bind'].url.database)"
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Failed to query backend database name: {res.stderr}"
    backend_db = res.stdout.strip()
    print(f"Backend Connected Database: '{backend_db}'")
    assert backend_db == "nexus_test_db", (
        f"Database isolation violation! Expected backend to use 'nexus_test_db', but got '{backend_db}'"
    )

    # 2. Execute SQL query directly against primary nexus_db to verify 122 persistent records are preserved
    res_sql = subprocess.run(
        [
            "docker", "exec", "nexus-postgres",
            "psql", "-U", "nexus_user", "-d", "nexus_db", "-t", "-A",
            "-c", "SELECT count(*) FROM incidents;"
        ],
        capture_output=True,
        text=True,
    )
    assert res_sql.returncode == 0, f"Failed to query primary nexus_db: {res_sql.stderr}"
    primary_count = int(res_sql.stdout.strip())
    print(f"Primary 'nexus_db' Persistent Incident Count: {primary_count} (PRESERVED & UNTOUCHED)")
    assert primary_count == 122, (
        f"Primary database data altered! Expected exactly 122 persistent incidents in nexus_db, found {primary_count}"
    )

    return {
        "status": "PASSED",
        "backend_database": backend_db,
        "primary_database": "nexus_db",
        "primary_database_incident_count": primary_count,
        "isolation_verified": True,
    }


async def verify_websocket_handshake_and_events() -> dict[str, Any]:
    """Perform genuine WebSocket handshake, exchange PING/PONG, and verify mandatory live event stream."""
    log_header("STEP 4: Genuine WebSocket Handshake & Mandatory Live Event Delivery")
    if websockets is None:
        raise RuntimeError("websockets python package not available in environment")

    ws_url = "ws://127.0.0.1:8000/ws/live"
    print(f"Connecting to WebSocket: {ws_url} ...")

    received_frames: list[dict[str, Any]] = []

    async with websockets.connect(ws_url, open_timeout=5.0) as ws:
        print("WebSocket handshake completed successfully (101 Switching Protocols).")

        # 1. Send heartbeat PING frame
        ping_timestamp = "2026-11-23T06:00:00Z"
        ping_frame = {"type": "PING", "timestamp": ping_timestamp}
        await ws.send(json.dumps(ping_frame))
        print(f"Sent outbound frame: {ping_frame}")

        # 2. Await authentic PONG response frame
        pong_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        pong_data = json.loads(pong_raw)
        print(f"Received inbound frame: {pong_data}")
        assert pong_data.get("type") == "PONG", f"Expected PONG frame, got: {pong_data}"
        assert pong_data.get("timestamp") == ping_timestamp, f"Mismatched timestamp in PONG: {pong_data}"
        received_frames.append(pong_data)

        # 3. Trigger telemetry step via REST API and verify event delivery over WebSocket
        print("Triggering baseline telemetry step to verify real-time event broadcast...")
        code, _ = http_request("http://127.0.0.1:8000/api/v1/telemetry/generate-step", method="POST", data={})
        assert code == 200, f"generate-step returned status code {code}"

        # 4. Mandatory Live Event Delivery Assertion: must receive TELEMETRY_SNAPSHOT within timeout
        event_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        event_data = json.loads(event_raw)
        print(f"Received live broadcast event: type={event_data.get('type')}, timestamp={event_data.get('timestamp')}")

        # Strict validation of envelope structure
        assert event_data.get("type") == "TELEMETRY_SNAPSHOT", (
            f"Mandatory event type mismatch: expected 'TELEMETRY_SNAPSHOT', got '{event_data.get('type')}'"
        )
        assert "timestamp" in event_data and isinstance(event_data["timestamp"], str), (
            "Event missing valid ISO-8601 string 'timestamp' envelope field"
        )
        assert "payload" in event_data and isinstance(event_data["payload"], dict), (
            "Event missing dict 'payload' envelope field"
        )
        received_frames.append(event_data)

    print(f"WebSocket handshake and mandatory event delivery verified. Total received frames: {len(received_frames)}.")
    return {
        "status": "PASSED",
        "handshake": "101 Switching Protocols",
        "ping_pong_verified": True,
        "event_type_received": event_data.get("type"),
        "event_timestamp": event_data.get("timestamp"),
        "payload_keys": list(event_data.get("payload", {}).keys()),
    }


def get_active_alarms() -> list[dict[str, Any]]:
    code, data = http_request("http://127.0.0.1:8000/api/v1/alarms?status=ACTIVE")
    if code != 200:
        return []
    return data.get("items", [])


def get_open_incidents() -> list[dict[str, Any]]:
    code, data = http_request("http://127.0.0.1:8000/api/v1/incidents?status=OPEN")
    if code != 200:
        return []
    return data.get("items", [])


def get_all_incidents() -> list[dict[str, Any]]:
    code, data = http_request("http://127.0.0.1:8000/api/v1/incidents?limit=1000")
    if code != 200:
        return []
    return data.get("items", [])


def get_grafana_auth_header() -> dict[str, str]:
    """Retrieve Grafana basic authentication header from environment variables."""
    user = os.environ.get("GRAFANA_ADMIN_USER", "admin")
    password = os.environ.get("GRAFANA_ADMIN_PASSWORD")
    if not password:
        candidates = [Path(".env"), Path(__file__).resolve().parent.parent / ".env"]
        for cand in candidates:
            if cand.exists():
                for line in cand.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("GRAFANA_ADMIN_PASSWORD="):
                        password = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
            if password:
                break
    if not password:
        raise RuntimeError("GRAFANA_ADMIN_PASSWORD environment variable must be set for Grafana authentication")
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def execute_scenario_lifecycle(
    execution_id: str,
    scenario_id: str,
    expected_cause: str,
    expected_target: str,
    impact_check_node: str,
    telemetry_assertions: dict[str, Any],
    recovery_assertions: dict[str, Any],
) -> dict[str, Any]:
    """Execute complete fault-to-recovery acceptance workflow for a given scenario."""
    print(f"\n----------------------------------------------------------------------")
    print(f"Executing Scenario Workflow: {scenario_id} -> {expected_cause} on {expected_target}")
    print(f"----------------------------------------------------------------------")

    # 1. Ownership Marker & Execution ID Binding
    code, act_check = http_request("http://127.0.0.1:8000/api/v1/faults/active")
    assert code == 200, f"Failed to check active scenario: {act_check}"

    if act_check.get("active") is True:
        curr_active_id = act_check.get("scenario_id")
        curr_key = act_check.get("scenario_key")
        is_owned_by_current_execution = False

        if TEST_OWNER_FILE.exists():
            try:
                owner_meta = json.loads(TEST_OWNER_FILE.read_text(encoding="utf-8"))
                if (
                    owner_meta.get("execution_id") == execution_id
                    and owner_meta.get("scenario_key") == curr_key
                ):
                    is_owned_by_current_execution = True
                else:
                    print(f"Found stale ownership marker: execution_id={owner_meta.get('execution_id')} vs current={execution_id}")
            except Exception as e:
                print(f"Failed to parse ownership marker: {e}")

        if is_owned_by_current_execution:
            print(f"Established current execution ownership ({execution_id}) for active scenario '{curr_active_id}'. Deactivating.")
            http_request("http://127.0.0.1:8000/api/v1/faults/scenarios/deactivate", method="POST", data={})
            for _ in range(5):
                http_request("http://127.0.0.1:8000/api/v1/telemetry/generate-step", method="POST", data={})
            try:
                TEST_OWNER_FILE.unlink()
            except Exception:
                pass
        else:
            raise RuntimeError(
                f"Active scenario '{curr_active_id}' is already running without verified ownership for execution '{execution_id}'. "
                f"Acceptance test must never deactivate an operator-owned scenario or stale scenario."
            )

    # 2. Record initial baseline state without destructive data deletion
    scenario_start_time = datetime.now(timezone.utc)
    initial_all_incident_ids = {i["incident_id"] for i in get_all_incidents()}
    initial_active_alarm_ids = {a["alarm_id"] for a in get_active_alarms()}
    print(f"Pre-scenario total incidents: {len(initial_all_incident_ids)}, active alarms: {len(initial_active_alarm_ids)}")

    # 3. Activate Fault Scenario and Bind Ownership Marker
    code, act_res = http_request(
        f"http://127.0.0.1:8000/api/v1/faults/scenarios/{scenario_id}/activate",
        method="POST",
        data={},
    )
    assert code == 200, f"Failed to activate scenario {scenario_id}: {act_res}"
    assert act_res.get("success") is True
    assert act_res["active_scenario"]["active"] is True
    assert act_res["active_scenario"]["scenario_key"] == scenario_id

    # Write execution-bound ownership marker
    TEST_OWNER_FILE.write_text(json.dumps({
        "execution_id": execution_id,
        "scenario_key": scenario_id,
        "scenario_id": act_res["active_scenario"].get("scenario_id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "process_pid": os.getpid(),
    }))
    print(f"Activated scenario '{scenario_id}' bound to execution '{execution_id}'.")

    # 4. Generate Telemetry Step with Active Fault
    code, _ = http_request("http://127.0.0.1:8000/api/v1/telemetry/generate-step", method="POST", data={})
    assert code == 200, "Failed to generate simulation step"
    print(f"Generated telemetry step with active fault '{scenario_id}'.")

    # 5. Enforce Scenario-Specific Telemetry Degradation Assertions
    code, telem_data = http_request(f"http://127.0.0.1:8000/api/v1/telemetry?node_id={impact_check_node}&limit=1")
    assert code == 200 and len(telem_data.get("items", [])) >= 1, f"Failed to fetch telemetry for node {impact_check_node}"
    sample = telem_data["items"][0]
    avail = sample["reliability"]["availability_pct"]
    latency = sample["performance"]["latency_ms"]
    throughput = sample["performance"]["throughput_mbps"]
    print(f"Node {impact_check_node} Telemetry during fault: availability={avail}%, latency={latency}ms, throughput={throughput}Mbps")

    # Evaluate telemetry degradation assertions
    if "max_availability" in telemetry_assertions:
        assert avail <= telemetry_assertions["max_availability"], (
            f"Telemetry degradation check failed! Expected availability <= {telemetry_assertions['max_availability']}%, got {avail}%"
        )
    if "min_availability" in telemetry_assertions:
        assert avail >= telemetry_assertions["min_availability"], (
            f"Telemetry degradation check failed! Expected availability >= {telemetry_assertions['min_availability']}%, got {avail}%"
        )
    if "max_throughput" in telemetry_assertions:
        assert throughput <= telemetry_assertions["max_throughput"], (
            f"Telemetry degradation check failed! Expected throughput <= {telemetry_assertions['max_throughput']}Mbps, got {throughput}Mbps"
        )
    if "min_latency" in telemetry_assertions:
        assert latency >= telemetry_assertions["min_latency"], (
            f"Telemetry degradation check failed! Expected latency >= {telemetry_assertions['min_latency']}ms, got {latency}ms"
        )
    if "max_latency" in telemetry_assertions:
        assert latency <= telemetry_assertions["max_latency"], (
            f"Telemetry degradation check failed! Expected latency <= {telemetry_assertions['max_latency']}ms, got {latency}ms"
        )

    # 6. Downstream Detection & Alarm Generation: Must generate new active alarms
    current_active_alarms = get_active_alarms()
    new_scenario_alarms = [a for a in current_active_alarms if a["alarm_id"] not in initial_active_alarm_ids]
    assert len(new_scenario_alarms) >= 1, (
        f"Scenario {scenario_id} failed detection: zero new active alarms generated!"
    )
    new_scenario_alarm_ids = {a["alarm_id"] for a in new_scenario_alarms}
    print(f"New scenario active alarms generated: {len(new_scenario_alarms)} (IDs: {list(new_scenario_alarm_ids)[:3]}...)")

    # 7. Incident Freshness & Ambiguity Prevention (Comparing against ALL existing incident IDs)
    all_current_incidents = get_all_incidents()
    newly_created_incidents = [i for i in all_current_incidents if i["incident_id"] not in initial_all_incident_ids]

    matching_new_incidents = [
        i for i in newly_created_incidents
        if i.get("suspected_target_id") == expected_target or (
            i.get("correlation_group_id") and expected_target in i["correlation_group_id"]
        )
    ]

    assert len(matching_new_incidents) == 1, (
        f"Incident Freshness Failure for scenario '{scenario_id}': expected exactly 1 newly created incident "
        f"targeting '{expected_target}', but found {len(matching_new_incidents)}! "
        f"Total newly created: {[i['incident_id'] for i in newly_created_incidents]}, "
        f"Pre-existing IDs: {list(initial_all_incident_ids)}"
    )

    inc = matching_new_incidents[0]
    inc_id = inc["incident_id"]
    corr_group_id = inc.get("correlation_group_id")
    hypotheses = inc.get("rca_hypotheses") or inc.get("hypotheses", [])

    print(f"Fresh Scenario Incident ID: {inc_id}")
    print(f"Title: {inc.get('title')}")
    print(f"Suspected Cause: {inc.get('suspected_cause_type')}, Suspected Target: {inc.get('suspected_target_id')}")

    # Verify correlation group belongs to current scenario
    assert corr_group_id is not None and len(corr_group_id.strip()) > 0, "Correlation Group ID is empty!"
    target_tokens = [expected_target, impact_check_node] + [tok for tok in expected_target.replace("LINK-", "").split("-") if tok]
    assert any(tok in corr_group_id for tok in target_tokens) or scenario_id in corr_group_id.lower(), (
        f"Correlation group '{corr_group_id}' does not belong to expected target '{expected_target}' / '{impact_check_node}'"
    )

    # Verify creation timeline event
    code, timeline = http_request(f"http://127.0.0.1:8000/api/v1/incidents/{inc_id}/timeline")
    assert code == 200, f"Failed to retrieve timeline for incident {inc_id}"
    created_event = next((e for e in timeline if e["event_type"] == "CREATED"), None)
    assert created_event is not None, f"Incident {inc_id} missing authoritative CREATED timeline event"

    # Verify authoritative CREATED event timestamp belongs to the current execution
    created_ts_raw = created_event["timestamp"]
    created_dt = datetime.fromisoformat(created_ts_raw.replace("Z", "+00:00"))
    assert created_dt >= scenario_start_time.replace(microsecond=0), (
        f"Authoritative CREATED event timestamp {created_dt} precedes scenario activation time {scenario_start_time}!"
    )

    assert len(hypotheses) >= 1, f"Expected non-empty RCA hypotheses, got: {hypotheses}"
    assert inc.get("suspected_cause_type") == expected_cause, (
        f"RCA Cause mismatch! Expected {expected_cause}, got {inc.get('suspected_cause_type')}"
    )
    assert inc.get("suspected_target_id") == expected_target, (
        f"RCA Target mismatch! Expected {expected_target}, got {inc.get('suspected_target_id')}"
    )

    # Verify incident alarm IDs correspond directly to newly generated scenario alarms
    inc_alarm_ids = set(inc.get("alarm_ids", []))
    assert len(inc_alarm_ids) >= 1, "Incident must reference at least one alarm ID"
    overlapping = inc_alarm_ids.intersection(new_scenario_alarm_ids)
    assert len(overlapping) >= 1, (
        f"Incident alarm IDs {inc_alarm_ids} do not correspond to newly generated scenario alarms {new_scenario_alarm_ids}!"
    )

    # 8. Deduplication by Incident Identity across repeated simulation steps
    code, _ = http_request("http://127.0.0.1:8000/api/v1/telemetry/generate-step", method="POST", data={})
    assert code == 200
    current_open = get_open_incidents()
    matching_identity = [i for i in current_open if i["incident_id"] == inc_id]
    assert len(matching_identity) == 1, f"Expected exactly one incident with id {inc_id}, found {len(matching_identity)}"
    matching_group = [i for i in current_open if i.get("correlation_group_id") == corr_group_id]
    assert len(matching_group) == 1, f"Duplicate incident created for correlation group {corr_group_id}!"
    print(f"Deduplication confirmed: incident {inc_id} maintained for group {corr_group_id} across repeated steps.")

    # 9. Operator Lifecycle Action: Acknowledge
    code, ack_res = http_request(
        f"http://127.0.0.1:8000/api/v1/incidents/{inc_id}/acknowledge",
        method="POST",
        data={"actor": "LEAD_OPERATOR"},
    )
    assert code == 200 and ack_res.get("status") == "ACKNOWLEDGED"
    print(f"Incident {inc_id} ACKNOWLEDGED.")

    # 10. Deactivate Fault Scenario (Network Recovery)
    code, deact_res = http_request("http://127.0.0.1:8000/api/v1/faults/scenarios/deactivate", method="POST", data={})
    assert code == 200 and deact_res["active_scenario"]["active"] is False
    try:
        TEST_OWNER_FILE.unlink()
    except Exception:
        pass
    print(f"Scenario '{scenario_id}' deactivated and ownership marker cleared.")

    # 11. Recovery as a Strict Pass/Fail Condition
    print("Monitoring recovery convergence across recovery window...")
    max_recovery_steps = 15
    recovery_converged = False
    convergence_step = 0
    final_kpis: dict[str, Any] = {}
    remaining_scenario_alarms: list[str] = []

    for rec_step in range(1, max_recovery_steps + 1):
        code, _ = http_request("http://127.0.0.1:8000/api/v1/telemetry/generate-step", method="POST", data={})
        assert code == 200

        # Check telemetry KPI values against explicit recovery thresholds
        code, rec_telem = http_request(f"http://127.0.0.1:8000/api/v1/telemetry?node_id={impact_check_node}&limit=1")
        assert code == 200 and len(rec_telem.get("items", [])) >= 1
        rec_sample = rec_telem["items"][0]
        r_avail = rec_sample["reliability"]["availability_pct"]
        r_latency = rec_sample["performance"]["latency_ms"]
        r_throughput = rec_sample["performance"]["throughput_mbps"]
        final_kpis = {"availability_pct": r_avail, "latency_ms": r_latency, "throughput_mbps": r_throughput}

        # Check alarm clearance for this scenario's generated alarms
        cur_active = {a["alarm_id"] for a in get_active_alarms()}
        remaining_scenario_alarms = list(new_scenario_alarm_ids.intersection(cur_active))

        kpis_ok = (
            r_avail >= recovery_assertions.get("min_availability", 99.0)
            and r_latency <= recovery_assertions.get("max_latency", 25.0)
            and r_throughput >= recovery_assertions.get("min_throughput", 1.0)
        )

        if len(remaining_scenario_alarms) == 0 and kpis_ok:
            recovery_converged = True
            convergence_step = rec_step
            print(f"Recovery converged at step {rec_step}: KPIs={final_kpis}, remaining scenario alarms=0.")
            break

    assert recovery_converged, (
        f"Scenario {scenario_id} RECOVERY FAILED to converge within {max_recovery_steps} steps! "
        f"Remaining scenario alarms: {remaining_scenario_alarms}, Final KPIs: {final_kpis}"
    )

    # 12. Operator Lifecycle Action: Resolve primary incident ONLY after verified recovery
    code, res_res = http_request(
        f"http://127.0.0.1:8000/api/v1/incidents/{inc_id}/resolve",
        method="POST",
        data={
            "actor": "LEAD_OPERATOR",
            "notes": f"Verified network recovery for scenario {scenario_id} at step {convergence_step}. Node KPIs normalized.",
        },
    )
    assert code == 200 and res_res.get("status") == "RESOLVED"
    print(f"Incident {inc_id} RESOLVED.")

    # 13. Timeline Audit Trail Verification
    code, updated_timeline = http_request(f"http://127.0.0.1:8000/api/v1/incidents/{inc_id}/timeline")
    assert code == 200
    event_types = [e["event_type"] for e in updated_timeline]
    assert "CREATED" in event_types
    assert "ACKNOWLEDGED" in event_types
    assert "RESOLVED" in event_types
    print(f"Timeline verified: {event_types}")

    return {
        "scenario_id": scenario_id,
        "expected_cause": expected_cause,
        "expected_target": expected_target,
        "impact_node": impact_check_node,
        "incident_id": inc_id,
        "correlation_group_id": corr_group_id,
        "rca_cause_match": inc.get("suspected_cause_type") == expected_cause,
        "rca_target_match": inc.get("suspected_target_id") == expected_target,
        "hypotheses_count": len(hypotheses),
        "hypotheses": hypotheses,
        "rca_evidence": inc.get("rca_evidence", []),
        "rca_confidence_score": inc.get("rca_confidence_score"),
        "scenario_alarms_generated_count": len(new_scenario_alarms),
        "telemetry_during_fault": {"availability_pct": avail, "latency_ms": latency, "throughput_mbps": throughput},
        "recovery_convergence_steps": convergence_step,
        "telemetry_post_recovery": final_kpis,
        "remaining_scenario_alarms_count": len(remaining_scenario_alarms),
        "timeline_events": event_types,
        "status": "PASSED",
    }


def verify_observability() -> dict[str, Any]:
    """Execute deep observability checks across Prometheus and Grafana."""
    log_header("STEP 7: Observability Verification (Prometheus PromQL & Grafana Dashboards)")

    # 1. Prometheus Scrape Target Health
    print("Waiting 5s for Prometheus scrape cycle to capture latest metrics...")
    time.sleep(5.0)
    print("Checking Prometheus scrape targets...")
    code, data = http_request("http://127.0.0.1:9090/api/v1/targets")
    assert code == 200 and "data" in data
    nexus_target = next(
        (t for t in data["data"].get("activeTargets", []) if "nexus-backend" in t.get("labels", {}).get("job", "")),
        None,
    )
    assert nexus_target is not None, "Prometheus nexus-backend scrape target missing"
    assert nexus_target["health"] == "up", f"Prometheus target health is '{nexus_target['health']}', expected 'up'"
    print(f"Target Scrape URL: {nexus_target['scrapeUrl']}, Health: {nexus_target['health']}")

    # 2. Execute Essential Operational PromQL Queries & Validate Result Vectors
    promql_checks = [
        ("nexus_topology_nodes_total", lambda v: v == 27.0),
        ("sum(nexus_fault_injections_total)", lambda v: v >= 1.0),
        ("sum(nexus_alarms_total)", lambda v: v >= 1.0),
        ("sum(nexus_incidents_total)", lambda v: v >= 1.0),
        ("nexus_websocket_active_connections", lambda v: v >= 0.0),
        ("avg(nexus_kpi_availability_pct)", lambda v: 0.0 <= v <= 100.0),
    ]

    promql_results: list[dict[str, Any]] = []
    for expr, validator in promql_checks:
        val = None
        for attempt in range(6):
            q_url = f"http://127.0.0.1:9090/api/v1/query?query={urllib.parse.quote(expr)}"
            code, q_res = http_request(q_url)
            if code == 200 and q_res.get("status") == "success":
                res_data = q_res.get("data", {}).get("result", [])
                if len(res_data) >= 1:
                    raw_val = res_data[0].get("value", [0, 0])[1]
                    try:
                        parsed_val = float(raw_val)
                        if validator(parsed_val):
                            val = parsed_val
                            break
                    except Exception:
                        pass
            time.sleep(2.0)
        assert val is not None, f"PromQL query '{expr}' did not return expected value after retries"
        print(f"PromQL Query '{expr}': {val} (VALID)")
        promql_results.append({"query": expr, "value": val, "status": "VALID"})

    # 3. Grafana Health and Datasource Provisioning
    print("Checking Grafana health and datasource...")
    code, g_health = http_request("http://127.0.0.1:3001/api/health")
    assert code == 200 and g_health.get("database") == "ok"

    code, ds_list = http_request(
        "http://127.0.0.1:3001/api/datasources",
        headers=get_grafana_auth_header(),
    )
    assert code == 200 and len(ds_list) >= 1
    prom_ds = next((ds for ds in ds_list if ds["type"] == "prometheus"), None)
    assert prom_ds is not None, "Prometheus datasource not provisioned in Grafana"
    print(f"Grafana Datasource: {prom_ds['name']} -> {prom_ds['url']}")

    # 4. Require all 5 Expected Dashboards
    code, search_list = http_request(
        "http://127.0.0.1:3001/api/search?type=dash-db",
        headers=get_grafana_auth_header(),
    )
    assert code == 200 and len(search_list) >= 5, f"Expected at least 5 dashboards, found {len(search_list)}"
    dashboard_titles = [d["title"] for d in search_list]
    print(f"Provisioned Dashboards in Grafana ({len(dashboard_titles)}): {dashboard_titles}")

    for ed in EXPECTED_DASHBOARDS:
        assert ed in dashboard_titles, f"Required dashboard '{ed}' missing from Grafana!"

    # 5. Extract and Execute Every Expected Dashboard Panel PromQL Query (Do Not Swallow Failures)
    dashboards_dir = Path("deploy/grafana/dashboards")
    assert dashboards_dir.exists(), "Dashboards directory deploy/grafana/dashboards missing!"

    dashboard_panel_query_results: list[dict[str, Any]] = []
    total_queries_executed = 0

    for ed in EXPECTED_DASHBOARDS:
        # Match file for expected dashboard
        matching_files = [f for f in dashboards_dir.glob("*.json") if json.loads(f.read_text(encoding="utf-8")).get("title") == ed]
        assert len(matching_files) == 1, f"Expected exactly 1 definition file for dashboard '{ed}', found {len(matching_files)}"
        dash_path = matching_files[0]

        dash_content = json.loads(dash_path.read_text(encoding="utf-8"))
        panels = dash_content.get("panels", [])
        panel_queries: list[str] = []
        for p in panels:
            for target in p.get("targets", []):
                expr = target.get("expr")
                if expr and expr not in panel_queries:
                    panel_queries.append(expr)

        assert len(panel_queries) >= 1, f"Dashboard '{ed}' has zero panel queries!"
        print(f"Testing {len(panel_queries)} PromQL panel queries for dashboard '{ed}'...")

        queries_details: list[dict[str, Any]] = []
        for pq in panel_queries:
            pq_url = f"http://127.0.0.1:9090/api/v1/query?query={urllib.parse.quote(pq)}"
            code, pq_res = http_request(pq_url)
            assert code == 200, f"Dashboard query '{pq}' failed with HTTP {code}"
            assert pq_res.get("status") == "success", f"Prometheus rejected query '{pq}': {pq_res}"
            res_type = pq_res.get("data", {}).get("resultType")
            assert res_type in ("vector", "matrix", "scalar"), f"Query '{pq}' returned invalid resultType: {res_type}"
            result_items = pq_res.get("data", {}).get("result", [])
            total_queries_executed += 1

            queries_details.append({
                "expr": pq,
                "resultType": res_type,
                "result_count": len(result_items),
                "status": "VALID",
            })

        dashboard_panel_query_results.append({
            "dashboard": ed,
            "queries_tested_count": len(panel_queries),
            "queries": queries_details,
            "status": "PASSED",
        })

    print(f"All {total_queries_executed} dashboard panel queries executed successfully against Prometheus.")

    return {
        "prometheus_target": nexus_target["health"],
        "promql_metrics": promql_results,
        "grafana_datasource": prom_ds["name"],
        "dashboards_count": len(dashboard_titles),
        "dashboards_verified": EXPECTED_DASHBOARDS,
        "total_panel_queries_executed": total_queries_executed,
        "dashboard_panel_queries": dashboard_panel_query_results,
        "status": "PASSED",
    }


def run_acceptance_suite() -> dict[str, Any]:
    execution_id = f"ACCEPTANCE-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    start_time = datetime.now(timezone.utc)
    suite_results: dict[str, Any] = {
        "suite_version": "NEXUS-RC-1.0.0-ACCEPTANCE",
        "execution_id": execution_id,
        "start_time": start_time.isoformat(),
    }

    print("\n======================================================================")
    print(" NEXUS RC-1.0.0 HARDENED ACCEPTANCE TEST SUITE")
    print(f" Execution ID: {execution_id}")
    print(f" Execution Started: {start_time.isoformat()}")
    print("======================================================================")

    # Step 1: Docker Containers Health Check
    suite_results["docker_health"] = verify_docker_health()

    # Step 2: Database Isolation & Integrity Verification
    suite_results["database_isolation"] = verify_database_isolation()

    # Step 3: Backend Liveness & Readiness Probes
    log_header("STEP 3: Backend Liveness & Readiness Probes")
    code, live_data = http_request("http://127.0.0.1:8000/health")
    assert code == 200 and live_data.get("status") == "healthy"
    code, ready_data = http_request("http://127.0.0.1:8000/ready")
    assert code == 200 and ready_data.get("status") == "ready"
    assert ready_data["components"]["database"] == "ready"
    print(f"Liveness: {live_data['status']}, Readiness Components: {ready_data['components']}")
    suite_results["backend_probes"] = {
        "status": "PASSED",
        "liveness": live_data,
        "readiness": ready_data,
    }

    # Step 4: Mandatory WebSocket Handshake & Live Event Delivery
    suite_results["websocket"] = asyncio.run(verify_websocket_handshake_and_events())

    # Step 5: Topology Architecture (27 Nodes)
    log_header("STEP 5: Topology Architecture Inspection (27 Reference Nodes)")
    code, topo = http_request("http://127.0.0.1:8000/api/v1/topology")
    assert code == 200 and topo.get("total_nodes") == 27
    nodes_by_type = {}
    for n in topo["nodes"]:
        nodes_by_type[n["node_type"]] = nodes_by_type.get(n["node_type"], 0) + 1
    print(f"Topology composition: {nodes_by_type}")
    assert nodes_by_type == {"CORE": 1, "AGGREGATION": 2, "SITE": 6, "CELL": 18}
    suite_results["topology"] = {"status": "PASSED", "total_nodes": 27, "nodes_by_type": nodes_by_type}

    # Step 6: Reference Scenarios Full Lifecycle Workflows
    log_header("STEP 6: Reference Scenarios Full Lifecycle Workflows (All 6 Scenarios)")
    code, sc_cat = http_request("http://127.0.0.1:8000/api/v1/faults/scenarios")
    assert code == 200 and sc_cat.get("total") == 6
    print(f"Catalog Scenarios: {[s['id'] for s in sc_cat['items']]}")

    scenario_specs = [
        {
            "id": "cell_outage",
            "expected_cause": "CELL_OUTAGE",
            "expected_target": "CELL-01",
            "impact_check_node": "CELL-01",
            "telemetry_assertions": {
                "max_availability": 1.0,
                "max_throughput": 1.0,
                "min_latency": 50.0,
            },
            "recovery_assertions": {
                "min_availability": 99.0,
                "max_latency": 25.0,
                "min_throughput": 10.0,
            },
        },
        {
            "id": "backhaul_failure",
            "expected_cause": "BACKHAUL_FAILURE",
            "expected_target": "LINK-AGG-01-SITE-01",
            "impact_check_node": "SITE-01",
            "telemetry_assertions": {
                "max_availability": 1.0,
                "max_throughput": 1.0,
                "min_latency": 25.0,
            },
            "recovery_assertions": {
                "min_availability": 99.0,
                "max_latency": 15.0,
                "min_throughput": 10.0,
            },
        },
        {
            "id": "radio_interference",
            "expected_cause": "RADIO_INTERFERENCE",
            "expected_target": "CELL-05",
            "impact_check_node": "CELL-05",
            "telemetry_assertions": {
                "min_availability": 99.0,
                "max_throughput": 250.0,
            },
            "recovery_assertions": {
                "min_availability": 99.0,
                "max_latency": 25.0,
                "min_throughput": 300.0,
            },
        },
        {
            "id": "cell_congestion",
            "expected_cause": "CELL_CONGESTION",
            "expected_target": "CELL-10",
            "impact_check_node": "CELL-10",
            "telemetry_assertions": {
                "min_availability": 99.0,
                "min_latency": 30.0,
            },
            "recovery_assertions": {
                "min_availability": 99.0,
                "max_latency": 25.0,
                "min_throughput": 100.0,
            },
        },
        {
            "id": "site_power_failure",
            "expected_cause": "SITE_POWER_FAILURE",
            "expected_target": "SITE-04",
            "impact_check_node": "SITE-04",
            "telemetry_assertions": {
                "max_availability": 1.0,
                "max_throughput": 1.0,
                "max_latency": 20.0,
            },
            "recovery_assertions": {
                "min_availability": 99.0,
                "max_latency": 15.0,
                "min_throughput": 10.0,
            },
        },
        {
            "id": "core_router_failure",
            "expected_cause": "CORE_ROUTER_FAILURE",
            "expected_target": "CORE-01",
            "impact_check_node": "CORE-01",
            "telemetry_assertions": {
                "max_availability": 1.0,
                "max_throughput": 1.0,
                "max_latency": 15.0,
            },
            "recovery_assertions": {
                "min_availability": 99.0,
                "max_latency": 5.0,
                "min_throughput": 10.0,
            },
        },
    ]

    scenario_results: list[dict[str, Any]] = []
    for spec in scenario_specs:
        res = execute_scenario_lifecycle(
            execution_id=execution_id,
            scenario_id=spec["id"],
            expected_cause=spec["expected_cause"],
            expected_target=spec["expected_target"],
            impact_check_node=spec["impact_check_node"],
            telemetry_assertions=spec["telemetry_assertions"],
            recovery_assertions=spec["recovery_assertions"],
        )
        scenario_results.append(res)

    suite_results["scenarios"] = scenario_results

    # Step 7: Observability Verification (Prometheus PromQL & Grafana Dashboards)
    suite_results["observability"] = verify_observability()

    end_time = datetime.now(timezone.utc)
    suite_results["end_time"] = end_time.isoformat()
    suite_results["duration_seconds"] = (end_time - start_time).total_seconds()
    suite_results["overall_status"] = "PASSED"

    log_header("ALL ACCEPTANCE VALIDATION WORKFLOWS COMPLETED SUCCESSFULLY!")
    print(f"Total Scenarios Evaluated: {len(scenario_results)} / 6 (100% Top-1 Cause & Target Accuracy)")
    print(f"Execution Duration: {suite_results['duration_seconds']:.2f} seconds")
    return suite_results


if __name__ == "__main__":
    results = run_acceptance_suite()
    with open("acceptance_test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nSaved acceptance test results to acceptance_test_results.json")
    sys.exit(0)
