"""Integration tests for NEXUS Incident Management REST API endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from nexus.incidents.api import app, get_incident_service
from nexus.incidents.enums import (
    IncidentPriority,
    IncidentSeverity,
    IncidentStatus,
)
from nexus.incidents.models import Incident
from nexus.incidents.repository import Base, IncidentRepository
from nexus.incidents.service import IncidentService


def make_api_alarm(
    alarm_id: str = "alm-1",
    node_id: str = "CELL-01",
    severity: str = "MAJOR",
    metric_name: str = "availability_pct",
    current_value: float = 0.0,
    threshold: Optional[float] = 90.0,
    first_seen: str = "2026-01-01T12:00:00Z",
    last_seen: str = "2026-01-01T12:05:00Z",
) -> dict[str, Any]:
    return {
        "alarm_id": alarm_id,
        "node_id": node_id,
        "rule_id": "RULE-TEST",
        "metric_name": metric_name,
        "source": "THRESHOLD",
        "severity": severity,
        "current_value": current_value,
        "threshold": threshold,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "observation_count": 1,
        "status": "ACTIVE",
    }


@pytest.fixture
def test_repo_and_service():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    repo = IncidentRepository.from_engine(engine)
    service = IncidentService(repository=repo)
    return repo, service, engine


@pytest.fixture
def api_client(test_repo_and_service):
    """Create a TestClient wired to an isolated in-memory SQLite database."""
    _, service, engine = test_repo_and_service
    app.dependency_overrides[get_incident_service] = lambda: service

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    engine.dispose()


class TestIncidentAPI:
    """Test REST API endpoints, validations, status codes, and error responses."""

    def test_create_incident_success(self, api_client: TestClient) -> None:
        payload = {
            "correlation_group_id": "GRP-API-1",
            "anchor_node_id": "SITE-01",
            "root_cause_tier": "SITE",
            "alarms": [
                make_api_alarm("alm-1", "CELL-01", "MAJOR"),
                make_api_alarm("alm-2", "CELL-02", "MAJOR"),
            ],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
            "correlation_reason": "Correlated radio failure",
            "suspected_cause_type": "CELL_OUTAGE",
            "suspected_target_id": "CELL-01",
            "suspected_target_type": "NODE",
            "rca_confidence_score": 0.88,
            "created_by": "AUTOMATION_ENGINE",
        }

        resp = api_client.post("/api/v1/incidents", json=payload)
        assert resp.status_code == 201
        data = resp.json()

        assert data["correlation_group_id"] == "GRP-API-1"
        assert data["status"] == "OPEN"
        assert data["suspected_cause_type"] == "CELL_OUTAGE"
        assert data["suspected_target_id"] == "CELL-01"
        assert data["rca_confidence_score"] == 0.88
        assert len(data["alarm_ids"]) == 2
        assert "ack_deadline" in data
        assert "resolve_deadline" in data
        assert "sla_status" in data

    def test_real_critical_alarm_remains_critical(self, api_client: TestClient) -> None:
        payload = {
            "correlation_group_id": "GRP-CRIT-1",
            "anchor_node_id": "AGG-01",
            "root_cause_tier": "AGGREGATION",
            "alarms": [
                make_api_alarm("alm-c", "AGG-01", "CRITICAL"),
            ],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
            "suspected_cause_type": "BACKHAUL_FAILURE",
            "suspected_target_id": "AGG-01",
            "suspected_target_type": "NODE",
        }
        resp = api_client.post("/api/v1/incidents", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["severity"] == "CRITICAL"
        assert data["priority"] == "P1"

    def test_real_major_alarm_remains_major(self, api_client: TestClient) -> None:
        payload = {
            "correlation_group_id": "GRP-MAJ-1",
            "anchor_node_id": "AGG-01",
            "root_cause_tier": "AGGREGATION",
            "alarms": [
                make_api_alarm("alm-m", "AGG-01", "MAJOR"),
            ],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
            "suspected_cause_type": "BACKHAUL_FAILURE",
            "suspected_target_id": "AGG-01",
            "suspected_target_type": "NODE",
        }
        resp = api_client.post("/api/v1/incidents", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["severity"] == "MAJOR"
        assert data["priority"] == "P2"

    def test_multiple_alarms_aggregate_severity_classification(self, api_client: TestClient) -> None:
        """Verify multi-alarm classification per operational policy."""
        # Case A: 1 MAJOR on CELL-01, 1 WARNING on CELL-02, 1 WARNING on CELL-03 (3 affected nodes)
        # Policy Rule 2: Any MAJOR alarm impacting >= 3 nodes -> MAJOR (P2)
        payload_major = {
            "correlation_group_id": "GRP-MULTI-MAJ",
            "anchor_node_id": "SITE-01",
            "root_cause_tier": "SITE",
            "alarms": [
                make_api_alarm("alm-1", "CELL-01", "MAJOR"),
                make_api_alarm("alm-2", "CELL-02", "WARNING"),
                make_api_alarm("alm-3", "CELL-03", "WARNING"),
            ],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
            "suspected_cause_type": "CELL_OUTAGE",
            "suspected_target_id": "CELL-01",
            "suspected_target_type": "NODE",
        }
        resp_major = api_client.post("/api/v1/incidents", json=payload_major)
        assert resp_major.status_code == 201
        data_major = resp_major.json()
        assert data_major["severity"] == "MAJOR"
        assert data_major["priority"] == "P2"

        # Case B: Multi-node WARNING without Major or Critical (2 affected nodes)
        # Policy Rule 3: Multiple affected nodes (>= 2) with WARNING alarms -> WARNING (P3)
        payload_warn = {
            "correlation_group_id": "GRP-MULTI-WARN",
            "anchor_node_id": "SITE-01",
            "root_cause_tier": "SITE",
            "alarms": [
                make_api_alarm("alm-w1", "CELL-01", "WARNING"),
                make_api_alarm("alm-w2", "CELL-02", "WARNING"),
            ],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
        }
        resp_warn = api_client.post("/api/v1/incidents", json=payload_warn)
        assert resp_warn.status_code == 201
        data_warn = resp_warn.json()
        assert data_warn["severity"] == "WARNING"
        assert data_warn["priority"] == "P3"

        # Case C: Isolated single-node WARNING alarm
        # Policy Rule 4: Isolated single-node WARNING alarm -> MINOR (P4)
        payload_minor = {
            "correlation_group_id": "GRP-SINGLE-WARN",
            "anchor_node_id": "SITE-01",
            "root_cause_tier": "SITE",
            "alarms": [
                make_api_alarm("alm-w-iso", "CELL-01", "WARNING"),
            ],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
        }
        resp_minor = api_client.post("/api/v1/incidents", json=payload_minor)
        assert resp_minor.status_code == 201
        data_minor = resp_minor.json()
        assert data_minor["severity"] == "MINOR"
        assert data_minor["priority"] == "P4"

    def test_unknown_rca_with_no_target_succeeds(self, api_client: TestClient) -> None:
        """UNKNOWN diagnosis preserves None target without fabricating placeholders."""
        payload = {
            "correlation_group_id": "GRP-UNKNOWN-NOTARGET",
            "alarms": [make_api_alarm("alm-u", "CELL-01", "WARNING")],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
            "suspected_cause_type": "UNKNOWN",
            "suspected_target_id": None,
            "suspected_target_type": None,
            "rca_confidence_score": None,
        }
        resp = api_client.post("/api/v1/incidents", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["suspected_cause_type"] == "UNKNOWN"
        assert data["suspected_target_id"] is None
        assert data["suspected_target_type"] is None
        assert data["rca_confidence_score"] is None
        assert data["rca_hypotheses"] == []

    def test_known_rca_with_missing_target_fails_with_422(self, api_client: TestClient) -> None:
        """Known diagnosis must fail with 422 if target ID or type is omitted."""
        # Missing suspected_target_id
        payload_no_id = {
            "correlation_group_id": "GRP-KNOWN-NO-ID",
            "alarms": [make_api_alarm("alm-1", "CELL-01")],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
            "suspected_cause_type": "CELL_OUTAGE",
            "suspected_target_type": "NODE",
        }
        resp1 = api_client.post("/api/v1/incidents", json=payload_no_id)
        assert resp1.status_code == 422

        # Missing suspected_target_type
        payload_no_type = {
            "correlation_group_id": "GRP-KNOWN-NO-TYPE",
            "alarms": [make_api_alarm("alm-2", "CELL-01")],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
            "suspected_cause_type": "CELL_OUTAGE",
            "suspected_target_id": "CELL-01",
        }
        resp2 = api_client.post("/api/v1/incidents", json=payload_no_type)
        assert resp2.status_code == 422

    def test_missing_or_empty_alarms_returns_422(self, api_client: TestClient) -> None:
        # No alarms field
        resp1 = api_client.post(
            "/api/v1/incidents",
            json={
                "correlation_group_id": "GRP-NO-ALMS",
                "time_window_start": "2026-01-01T12:00:00Z",
                "time_window_end": "2026-01-01T12:05:00Z",
            },
        )
        assert resp1.status_code == 422

        # Empty alarms list
        resp2 = api_client.post(
            "/api/v1/incidents",
            json={
                "correlation_group_id": "GRP-EMPTY-ALMS",
                "alarms": [],
                "time_window_start": "2026-01-01T12:00:00Z",
                "time_window_end": "2026-01-01T12:05:00Z",
            },
        )
        assert resp2.status_code == 422

    def test_incomplete_alarm_data_returns_422(self, api_client: TestClient) -> None:
        # Alarm missing metric_name
        bad_alarm = make_api_alarm("alm-bad", "CELL-01")
        del bad_alarm["metric_name"]

        resp = api_client.post(
            "/api/v1/incidents",
            json={
                "correlation_group_id": "GRP-BAD-ALM",
                "alarms": [bad_alarm],
                "time_window_start": "2026-01-01T12:00:00Z",
                "time_window_end": "2026-01-01T12:05:00Z",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "omitted_field",
        [
            "alarm_id",
            "node_id",
            "rule_id",
            "metric_name",
            "source",
            "severity",
            "current_value",
            "first_seen",
            "last_seen",
            "observation_count",
            "status",
        ],
    )
    def test_omit_mandatory_alarm_fields_individually_returns_422(
        self, api_client: TestClient, omitted_field: str
    ) -> None:
        """Every mandatory field in CorrelatedAlarmDTO must produce HTTP 422 when omitted."""
        alarm = make_api_alarm(f"alm-omit-{omitted_field}", "CELL-01")
        del alarm[omitted_field]

        resp = api_client.post(
            "/api/v1/incidents",
            json={
                "correlation_group_id": f"GRP-OMIT-{omitted_field}",
                "alarms": [alarm],
                "time_window_start": "2026-01-01T12:00:00Z",
                "time_window_end": "2026-01-01T12:05:00Z",
            },
        )
        assert resp.status_code == 422, f"Omitting {omitted_field} did not produce 422: {resp.text}"

    def test_omit_optional_threshold_succeeds(self, api_client: TestClient) -> None:
        """Threshold remains optional and omitting it succeeds."""
        alarm = make_api_alarm("alm-no-thresh", "CELL-01", threshold=None)
        del alarm["threshold"]

        resp = api_client.post(
            "/api/v1/incidents",
            json={
                "correlation_group_id": "GRP-NO-THRESH",
                "alarms": [alarm],
                "time_window_start": "2026-01-01T12:00:00Z",
                "time_window_end": "2026-01-01T12:05:00Z",
            },
        )
        assert resp.status_code == 201

    def test_critical_backbone_alarm_cannot_lose_tier_information(
        self, api_client: TestClient
    ) -> None:
        """A real CRITICAL backbone alarm with omitted root_cause_tier derives tier from topology and remains CRITICAL."""
        # 1. Alarm on AGG-01 without root_cause_tier in payload
        payload_agg = {
            "correlation_group_id": "GRP-BACKBONE-AGG",
            "anchor_node_id": "AGG-01",
            # root_cause_tier is intentionally omitted
            "alarms": [
                make_api_alarm("alm-bb-1", "AGG-01", "CRITICAL"),
            ],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
            "suspected_cause_type": "BACKHAUL_FAILURE",
            "suspected_target_id": "AGG-01",
            "suspected_target_type": "NODE",
        }
        resp1 = api_client.post("/api/v1/incidents", json=payload_agg)
        assert resp1.status_code == 201
        data1 = resp1.json()
        assert data1["severity"] == "CRITICAL", "Backbone CRITICAL alarm was silently downgraded!"
        assert data1["priority"] == "P1"

        # 2. Alarm on CORE-01 without root_cause_tier in payload
        payload_core = {
            "correlation_group_id": "GRP-BACKBONE-CORE",
            "anchor_node_id": "CORE-01",
            "alarms": [
                make_api_alarm("alm-core-1", "CORE-01", "CRITICAL"),
            ],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
        }
        resp2 = api_client.post("/api/v1/incidents", json=payload_core)
        assert resp2.status_code == 201
        data2 = resp2.json()
        assert data2["severity"] == "CRITICAL"
        assert data2["priority"] == "P1"

        # 3. Critical alarm on unresolvable node without tier raises 422 rather than silently downgrading
        payload_unknown = {
            "correlation_group_id": "GRP-UNKNOWN-NODE-CRIT",
            "anchor_node_id": "CUSTOM-NODE-999",
            "alarms": [
                make_api_alarm("alm-unk", "CUSTOM-NODE-999", "CRITICAL"),
            ],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
        }
        resp3 = api_client.post("/api/v1/incidents", json=payload_unknown)
        assert resp3.status_code == 422

    def test_valid_complete_alarm_payloads_create_incidents_correctly(
        self, api_client: TestClient
    ) -> None:
        """Valid complete alarm payload with all mandatory fields creates incident correctly."""
        complete_alarm = make_api_alarm(
            alarm_id="alm-complete-1",
            node_id="CELL-01",
            severity="MAJOR",
            metric_name="throughput_mbps",
            current_value=12.5,
            threshold=50.0,
        )
        payload = {
            "correlation_group_id": "GRP-COMPLETE-PAYLOAD",
            "anchor_node_id": "SITE-01",
            "root_cause_tier": "SITE",
            "alarms": [complete_alarm],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
            "correlation_reason": "Complete valid payload test",
            "suspected_cause_type": "CELL_OUTAGE",
            "suspected_target_id": "CELL-01",
            "suspected_target_type": "NODE",
            "rca_confidence_score": 0.95,
        }
        resp = api_client.post("/api/v1/incidents", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["correlation_group_id"] == "GRP-COMPLETE-PAYLOAD"
        assert data["status"] == "OPEN"
        assert len(data["alarm_ids"]) == 1
        assert data["alarm_ids"][0] == "alm-complete-1"
        assert data["rca_confidence_score"] == 0.95

    def test_confidence_validation_and_no_invented_default(
        self, api_client: TestClient
    ) -> None:
        base_payload = {
            "correlation_group_id": "GRP-CONF-TEST",
            "alarms": [make_api_alarm("alm-1", "CELL-01")],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
            "suspected_cause_type": "CELL_OUTAGE",
            "suspected_target_id": "CELL-01",
            "suspected_target_type": "NODE",
        }

        # 1. Missing confidence: preserves None without inventing 0.8
        p1 = dict(base_payload)
        p1["correlation_group_id"] = "GRP-CONF-NONE"
        resp1 = api_client.post("/api/v1/incidents", json=p1)
        assert resp1.status_code == 201
        assert resp1.json()["rca_confidence_score"] is None

        # 2. Valid confidence: 0.95
        p2 = dict(base_payload)
        p2["correlation_group_id"] = "GRP-CONF-095"
        p2["rca_confidence_score"] = 0.95
        resp2 = api_client.post("/api/v1/incidents", json=p2)
        assert resp2.status_code == 201
        assert resp2.json()["rca_confidence_score"] == 0.95

        # 3. Invalid confidence: > 1.0 -> 422
        p3 = dict(base_payload)
        p3["correlation_group_id"] = "GRP-CONF-TOO-HIGH"
        p3["rca_confidence_score"] = 1.5
        resp3 = api_client.post("/api/v1/incidents", json=p3)
        assert resp3.status_code == 422

        # 4. Invalid confidence: boolean true -> 422
        p4 = dict(base_payload)
        p4["correlation_group_id"] = "GRP-CONF-BOOL"
        p4["rca_confidence_score"] = True
        resp4 = api_client.post("/api/v1/incidents", json=p4)
        assert resp4.status_code == 422

    def test_malformed_enums_produce_422(self, api_client: TestClient) -> None:
        base_payload = {
            "correlation_group_id": "GRP-ENUM-TEST",
            "alarms": [make_api_alarm("alm-1", "CELL-01")],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
        }

        # Invalid cause enum
        p1 = dict(base_payload)
        p1["suspected_cause_type"] = "INVALID_CAUSE_XYZ"
        assert api_client.post("/api/v1/incidents", json=p1).status_code == 422

        # Invalid target type enum
        p2 = dict(base_payload)
        p2["suspected_cause_type"] = "CELL_OUTAGE"
        p2["suspected_target_id"] = "CELL-01"
        p2["suspected_target_type"] = "INVALID_TARGET_TYPE"
        assert api_client.post("/api/v1/incidents", json=p2).status_code == 422

        # Invalid root cause tier enum
        p3 = dict(base_payload)
        p3["root_cause_tier"] = "INVALID_TIER_ABC"
        assert api_client.post("/api/v1/incidents", json=p3).status_code == 422

    def test_inconsistent_target_information_produces_422(
        self, api_client: TestClient
    ) -> None:
        # Known cause CELL_OUTAGE without suspected_target_id
        payload = {
            "correlation_group_id": "GRP-INCONSISTENT-1",
            "alarms": [make_api_alarm("alm-1", "CELL-01")],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
            "suspected_cause_type": "CELL_OUTAGE",
            "suspected_target_id": None,
        }
        assert api_client.post("/api/v1/incidents", json=payload).status_code == 422

    def test_invalid_timestamps_produce_422(self, api_client: TestClient) -> None:
        # time_window_start after time_window_end
        payload = {
            "correlation_group_id": "GRP-TIME-ERR",
            "alarms": [make_api_alarm("alm-1", "CELL-01")],
            "time_window_start": "2026-01-01T12:10:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
        }
        assert api_client.post("/api/v1/incidents", json=payload).status_code == 422

    def test_malformed_evidence_produces_422(self, api_client: TestClient) -> None:
        payload = {
            "correlation_group_id": "GRP-EV-ERR",
            "alarms": [make_api_alarm("alm-1", "CELL-01")],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
            "suspected_cause_type": "CELL_OUTAGE",
            "suspected_target_id": "CELL-01",
            "suspected_target_type": "NODE",
            "evidence_items": [
                {
                    "source_node_id": "CELL-01",
                    "metric_name": "availability_pct",
                    "observed_value": True,  # Boolean rejected!
                    "reasoning": "bad evidence",
                    "evidence_source": "INVALID_SOURCE",  # Invalid source!
                }
            ],
        }
        assert api_client.post("/api/v1/incidents", json=payload).status_code == 422

    def test_create_duplicate_incident_returns_409(self, api_client: TestClient) -> None:
        payload = {
            "correlation_group_id": "GRP-DUP-API",
            "alarms": [make_api_alarm("alm-dup", "CELL-01")],
            "time_window_start": "2026-01-01T12:00:00Z",
            "time_window_end": "2026-01-01T12:05:00Z",
        }

        resp1 = api_client.post("/api/v1/incidents", json=payload)
        assert resp1.status_code == 201

        resp2 = api_client.post("/api/v1/incidents", json=payload)
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"]

    def test_get_incident_details_and_not_found(self, api_client: TestClient) -> None:
        c_resp = api_client.post(
            "/api/v1/incidents",
            json={
                "correlation_group_id": "GRP-GET-1",
                "alarms": [make_api_alarm("alm-get", "CELL-01")],
                "time_window_start": "2026-01-01T12:00:00Z",
                "time_window_end": "2026-01-01T12:05:00Z",
            },
        )
        inc_id = c_resp.json()["incident_id"]

        get_resp = api_client.get(f"/api/v1/incidents/{inc_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["incident_id"] == inc_id

        nf_resp = api_client.get("/api/v1/incidents/NONEXISTENT-INC-ID")
        assert nf_resp.status_code == 404

    def test_acknowledge_and_resolve_endpoints(self, api_client: TestClient) -> None:
        c_resp = api_client.post(
            "/api/v1/incidents",
            json={
                "correlation_group_id": "GRP-LIFECYCLE-API",
                "alarms": [make_api_alarm("alm-life", "CELL-01")],
                "time_window_start": "2026-01-01T12:00:00Z",
                "time_window_end": "2026-01-01T12:05:00Z",
            },
        )
        inc_id = c_resp.json()["incident_id"]

        # Acknowledge
        ack_resp = api_client.post(
            f"/api/v1/incidents/{inc_id}/acknowledge",
            json={"actor": "noc_operator_1"},
        )
        assert ack_resp.status_code == 200
        assert ack_resp.json()["status"] == "ACKNOWLEDGED"

        # Re-acknowledge -> 400
        assert api_client.post(
            f"/api/v1/incidents/{inc_id}/acknowledge",
            json={"actor": "noc_operator_2"},
        ).status_code == 400

        # Resolve
        res_resp = api_client.post(
            f"/api/v1/incidents/{inc_id}/resolve",
            json={"actor": "field_tech_1", "notes": "Antenna azimuth adjusted"},
        )
        assert res_resp.status_code == 200
        assert res_resp.json()["status"] == "RESOLVED"

        # Resolve already resolved -> 400
        assert api_client.post(
            f"/api/v1/incidents/{inc_id}/resolve",
            json={"actor": "field_tech_2"},
        ).status_code == 400

    def test_timeline_endpoint(self, api_client: TestClient) -> None:
        c_resp = api_client.post(
            "/api/v1/incidents",
            json={
                "correlation_group_id": "GRP-TIMELINE-API",
                "alarms": [make_api_alarm("alm-tl", "CELL-01")],
                "time_window_start": "2026-01-01T12:00:00Z",
                "time_window_end": "2026-01-01T12:05:00Z",
            },
        )
        inc_id = c_resp.json()["incident_id"]

        api_client.post(f"/api/v1/incidents/{inc_id}/acknowledge", json={"actor": "analyst_1"})
        api_client.post(f"/api/v1/incidents/{inc_id}/resolve", json={"actor": "analyst_1"})

        tl_resp = api_client.get(f"/api/v1/incidents/{inc_id}/timeline")
        assert tl_resp.status_code == 200
        events = tl_resp.json()
        assert len(events) == 3
        assert [e["event_type"] for e in events] == ["CREATED", "ACKNOWLEDGED", "RESOLVED"]

    def test_list_incidents_pagination_and_filters(self, api_client: TestClient) -> None:
        for i in range(1, 4):
            api_client.post(
                "/api/v1/incidents",
                json={
                    "correlation_group_id": f"GRP-FILTER-{i}",
                    "alarms": [make_api_alarm(f"alm-f-{i}", f"CELL-0{i}")],
                    "time_window_start": "2026-01-01T12:00:00Z",
                    "time_window_end": "2026-01-01T12:05:00Z",
                },
            )

        resp = api_client.get("/api/v1/incidents?limit=2&offset=0")
        assert resp.status_code == 200
        assert resp.json()["total"] == 3
        assert len(resp.json()["items"]) == 2

    def test_metrics_endpoint(self, api_client: TestClient) -> None:
        api_client.post(
            "/api/v1/incidents",
            json={
                "correlation_group_id": "GRP-METRICS-1",
                "alarms": [make_api_alarm("alm-m1", "CELL-01")],
                "time_window_start": "2026-01-01T12:00:00Z",
                "time_window_end": "2026-01-01T12:05:00Z",
            },
        )

        resp = api_client.get("/api/v1/incidents/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_incidents"] == 1
        assert data["open_incident_count"] == 1


class TestDatabaseInitializationAndMigrationRequirements:
    """Test SQLite development auto-creation vs PostgreSQL migration enforcement."""

    def test_sqlite_development_mode_creates_tables(self) -> None:
        """In SQLite mode with development configuration, get_incident_service initializes tables."""
        with patch.dict("os.environ", {"DATABASE_URL": "sqlite:///:memory:", "ENVIRONMENT": "development"}):
            import nexus.incidents.api as api_mod
            api_mod._default_service = None
            svc = api_mod.get_incident_service()
            assert svc is not None
            api_mod._default_service = None

    def test_sqlite_non_development_mode_requires_migrations(self) -> None:
        """In SQLite mode without development configuration, unmigrated DB raises RuntimeError."""
        mock_engine = MagicMock()
        mock_engine.dialect.name = "sqlite"
        mock_engine.url = "sqlite:///./prod_nexus.db"

        with patch("nexus.incidents.api.create_engine", return_value=mock_engine):
            with patch("sqlalchemy.inspect") as mock_inspect:
                mock_inspector = MagicMock()
                mock_inspector.get_table_names.return_value = []
                mock_inspect.return_value = mock_inspector

                with patch.dict("os.environ", {"DATABASE_URL": "sqlite:///./prod_nexus.db", "ENVIRONMENT": "production"}):
                    import nexus.incidents.api as api_mod
                    api_mod._default_service = None
                    with pytest.raises(RuntimeError) as exc_info:
                        api_mod.get_incident_service()
                    assert "SQLite schema is not migrated and development auto-creation is disabled" in str(exc_info.value)
                    api_mod._default_service = None

    def test_postgresql_requires_alembic_migrations(self) -> None:
        """On PostgreSQL, missing migrations raise clear RuntimeError without creating tables."""
        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"

        with patch("nexus.incidents.api.create_engine", return_value=mock_engine):
            with patch("sqlalchemy.inspect") as mock_inspect:
                # Tables do not exist
                mock_inspector = MagicMock()
                mock_inspector.get_table_names.return_value = []
                mock_inspect.return_value = mock_inspector

                with patch.dict("os.environ", {"DATABASE_URL": "postgresql+psycopg://user:pass@localhost:5432/db", "ENVIRONMENT": "development"}):
                    import nexus.incidents.api as api_mod
                    api_mod._default_service = None
                    with pytest.raises(RuntimeError) as exc_info:
                        api_mod.get_incident_service()
                    assert "Run 'alembic upgrade head'" in str(exc_info.value)
                    api_mod._default_service = None


class TestMetricsScaleBeyond10000:
    """Test metrics calculation with >10,000 incidents proving no truncation."""

    def test_metrics_processes_more_than_10000_incidents(
        self, test_repo_and_service
    ) -> None:
        repo, service, _ = test_repo_and_service
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Generate 10,500 sample incidents in batches of 1,000
        total_to_generate = 10500
        batch_size = 1000
        generated = 0

        while generated < total_to_generate:
            current_batch_size = min(batch_size, total_to_generate - generated)
            batch = [
                Incident(
                    incident_id=f"INC-SCALE-{i}",
                    correlation_group_id=f"GRP-SCALE-{i}",
                    status=IncidentStatus.OPEN if i % 2 == 0 else IncidentStatus.RESOLVED,
                    severity=IncidentSeverity.WARNING,
                    priority=IncidentPriority.P3,
                    title=f"Incident {i}",
                    description="Scale test",
                    alarm_ids=("alm-1",),
                    affected_node_ids=("CELL-01",),
                    suspected_cause_type=None,
                    suspected_target_id=None,
                    suspected_target_type=None,
                    rca_confidence_score=None,
                    rca_hypotheses=(),
                    rca_evidence=(),
                    created_at=t0 + timedelta(seconds=i),
                    ack_deadline=t0 + timedelta(hours=1),
                    resolve_deadline=t0 + timedelta(hours=12),
                    resolved_at=(t0 + timedelta(minutes=30)) if i % 2 != 0 else None,
                    resolved_by="system" if i % 2 != 0 else None,
                )
                for i in range(generated, generated + current_batch_size)
            ]
            repo.bulk_create(batch)
            generated += current_batch_size

        metrics = service.get_metrics()
        assert metrics.total_incidents == 10500
        # 5250 OPEN and 5250 RESOLVED
        assert metrics.open_incident_count == 5250
        assert metrics.incidents_by_status[IncidentStatus.OPEN.value] == 5250
        assert metrics.incidents_by_status[IncidentStatus.RESOLVED.value] == 5250
        assert metrics.mttr_seconds is not None
