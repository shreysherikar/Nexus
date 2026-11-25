# NEXUS — Complete API & WebSocket Interface Reference

**Document Identifier**: `NEXUS-API-REF-2026-V1`  
**Classification**: Authoritative System Interface Specification  
**Platform Version**: `1.0.0`  
**Base REST URL**: `http://localhost:8000/api/v1` (or relative `/api/v1` behind reverse proxy)  
**Base WebSocket URL**: `ws://localhost:8000/ws/live` (or relative `/ws/live`)  

---

## 1. Interface Overview & Standards

### 1.1 Content Negotiation & Encodings
- **Request Payloads**: `Content-Type: application/json`
- **Response Payloads**: `Content-Type: application/json; charset=utf-8`
- **Prometheus Metrics**: `Content-Type: text/plain; version=0.0.4; charset=utf-8`
- **Date & Time Standard**: Strict ISO 8601 UTC extended format with explicit timezone offset (e.g. `2026-11-23T12:00:00Z` or `2026-11-23T12:00:00+00:00`).

### 1.2 Anti-Caching Controls
All `/api/*` endpoints emit non-caching HTTP headers:
```http
Cache-Control: no-cache, no-store, must-revalidate, max-age=0
Pragma: no-cache
Expires: 0
```

### 1.3 Uniform Error Schema
Error payloads returned by FastAPI exception handlers adhere to the canonical schema:
```json
{
  "detail": "Descriptive human-readable error explanation",
  "error_code": "MACHINE_READABLE_ENUM_CODE"
}
```

Standard Error Codes:
- `INCIDENT_NOT_FOUND` (HTTP 404)
- `DUPLICATE_INCIDENT` (HTTP 409)
- `INVALID_STATE_TRANSITION` (HTTP 400)
- `INVALID_INCIDENT_DATA` (HTTP 422)
- `NODE_NOT_FOUND` (HTTP 404)

---

## 2. System & Health Endpoints

### 2.1 Platform Overview
- **HTTP Method**: `GET`
- **Route**: `/`
- **Subsystem**: `nexus.main`
- **Purpose**: Returns metadata, version, and navigation links.
- **Request Parameters**: None
- **Response Status**: `200 OK`
- **Response Schema**:
  ```json
  {
    "platform": "NEXUS Network Intelligence & Incident Management Platform",
    "version": "1.0.0",
    "docs_url": "/docs",
    "health_url": "/health",
    "readiness_url": "/ready",
    "metrics_url": "/metrics"
  }
  ```

### 2.2 Liveness Probe
- **HTTP Method**: `GET`
- **Route**: `/health`
- **Subsystem**: `nexus.main`
- **Purpose**: Lightweight process liveness verification for container orchestrators.
- **Request Parameters**: None
- **Response Status**: `200 OK`
- **Response Schema**:
  ```json
  {
    "status": "healthy"
  }
  ```

### 2.3 Readiness Probe
- **HTTP Method**: `GET`
- **Route**: `/ready`
- **Subsystem**: `nexus.main`
- **Purpose**: Deep verification of all 6 operational subsystems (`topology`, `broadcaster`, `telemetry_store`, `alarm_service`, `fault_service`, `database`).
- **Response Status**:
  - `200 OK`: All 6 components report `ready`.
  - `503 SERVICE UNAVAILABLE`: One or more components are `not_ready`, `unhealthy`, or in `error`.
- **Response Example (Healthy)**:
  ```json
  {
    "status": "ready",
    "components": {
      "topology": "ready",
      "broadcaster": "ready",
      "telemetry_store": "ready",
      "alarm_service": "ready",
      "fault_service": "ready",
      "database": "ready"
    }
  }
  ```

### 2.4 Prometheus Metrics Exposition
- **HTTP Method**: `GET`
- **Route**: `/metrics`
- **Subsystem**: `nexus.metrics`
- **Purpose**: Exposes low-cardinality operational telemetry and HTTP metrics for Prometheus scrapers.
- **Response Status**: `200 OK`
- **Response Format**: Plain text (`text/plain; version=0.0.4`)

---

## 3. Network Topology API

### 3.1 Get Network Topology
- **HTTP Method**: `GET`
- **Route**: `/api/v1/topology`
- **Source**: `nexus/topology/api.py`
- **Purpose**: Retrieves the complete 27-node network topology registry, hierarchy tier classifications, and geographic coordinates.
- **Query Parameters**: None
- **Response Status**: `200 OK`
- **Response Schema**:
  ```json
  {
    "nodes": [
      {
        "node_id": "CORE-01",
        "node_type": "CORE",
        "parent_id": null,
        "status": "ONLINE",
        "latitude": null,
        "longitude": null,
        "children": ["AGG-01", "AGG-02"]
      },
      {
        "node_id": "AGG-01",
        "node_type": "AGGREGATION",
        "parent_id": "CORE-01",
        "status": "ONLINE",
        "latitude": null,
        "longitude": null,
        "children": ["SITE-01", "SITE-02", "SITE-03"]
      }
    ],
    "total_nodes": 27,
    "tiers": {
      "CORE": 1,
      "AGGREGATION": 2,
      "SITE": 6,
      "CELL": 18
    }
  }
  ```

### 3.2 Get Topology Node by ID
- **HTTP Method**: `GET`
- **Route**: `/api/v1/topology/nodes/{node_id}`
- **Source**: `nexus/topology/api.py`
- **Path Parameters**:
  - `node_id` (string, required): Node identifier (e.g. `CELL-01`, `SITE-04`, `AGG-01`, `CORE-01`).
- **Response Status**:
  - `200 OK`: Node found.
  - `404 NOT FOUND`: Node ID does not exist in topology registry.
- **Response Example**:
  ```json
  {
    "node_id": "CELL-01",
    "node_type": "CELL",
    "parent_id": "SITE-01",
    "status": "ONLINE",
    "latitude": null,
    "longitude": null,
    "children": []
  }
  ```

---

## 4. Telemetry API

### 4.1 Query Telemetry Snapshots
- **HTTP Method**: `GET`
- **Route**: `/api/v1/telemetry`
- **Source**: `nexus/telemetry/api.py`
- **Purpose**: Paginated retrieval of authentic generated telemetry snapshots from the in-memory sliding buffer.
- **Query Parameters**:
  - `node_id` (string, optional): Filter by node identifier.
  - `node_type` (string, optional): Filter by hierarchy tier (`CORE`, `AGGREGATION`, `SITE`, `CELL`).
  - `start_time` (ISO datetime, optional): Inclusive start timestamp UTC.
  - `end_time` (ISO datetime, optional): Inclusive end timestamp UTC.
  - `limit` (integer, optional, default: 50, min: 1, max: 1000): Page size.
  - `offset` (integer, optional, default: 0, min: 0): Page offset.
- **Validation**: If `start_time > end_time`, returns HTTP 422. If `node_type` is invalid, returns HTTP 422.
- **Response Status**: `200 OK`
- **Response Schema**:
  ```json
  {
    "items": [
      {
        "node_id": "CELL-01",
        "timestamp": "2026-11-23T12:00:00Z",
        "performance": {
          "throughput_mbps": 42.15,
          "latency_ms": 14.28
        },
        "reliability": {
          "connection_drop_rate_pct": 0.42,
          "availability_pct": 99.85,
          "handover_success_rate_pct": 98.6
        },
        "radio": {
          "rsrp_dbm": -88.45,
          "sinr_db": 18.2,
          "prb_utilization_pct": 45.1
        }
      }
    ],
    "total": 1,
    "limit": 50,
    "offset": 0
  }
  ```

### 4.2 Generate Synthetic Telemetry Step
- **HTTP Method**: `POST`
- **Route**: `/api/v1/telemetry/generate-step`
- **Source**: `nexus/telemetry/api.py`
- **Purpose**: Triggers a single discrete simulation step across all 27 nodes, evaluates active fault impairments, runs anomaly detection, executes LCA correlation and RCA, updates PostgreSQL incidents, and publishes live WebSocket events.
- **Concurrency Protection**: Protected by `_step_generation_lock`. Concurrent invocations return HTTP 409 immediately.
- **Response Status**:
  - `200 OK`: Step generated and processed successfully.
  - `409 CONFLICT`: Step generation already in progress.
- **Response Example**:
  ```json
  {
    "generated_count": 27,
    "timestamp": "2026-11-23T12:05:00Z",
    "message": "Deterministic simulation step generated and recorded into in-memory store."
  }
  ```

---

## 5. Alarm & Anomaly Detection API

### 5.1 Query Alarms
- **HTTP Method**: `GET`
- **Route**: `/api/v1/alarms`
- **Source**: `nexus/detection/api.py`
- **Purpose**: Paginated retrieval of active and historical cleared alarms.
- **Query Parameters**:
  - `node_id` (string, optional): Filter by target node.
  - `severity` (string, optional): Filter by severity (`WARNING`, `MAJOR`, `CRITICAL`).
  - `status` (string, optional): Filter by lifecycle state (`ACTIVE`, `CLEARED`).
  - `limit` (integer, optional, default: 50, min: 1, max: 100): Page size.
  - `offset` (integer, optional, default: 0, min: 0): Page offset.
- **Response Status**: `200 OK`
- **Response Schema**:
  ```json
  {
    "items": [
      {
        "alarm_id": "ALARM-CELL-01-RULE-AVAIL-CRIT-00001",
        "node_id": "CELL-01",
        "rule_id": "RULE-AVAIL-CRIT",
        "metric_name": "availability_pct",
        "source": "THRESHOLD",
        "severity": "CRITICAL",
        "current_value": 0.0,
        "threshold": 95.0,
        "first_seen": "2026-11-23T12:05:00Z",
        "last_seen": "2026-11-23T12:05:00Z",
        "observation_count": 1,
        "status": "ACTIVE",
        "cleared_at": null,
        "description": "Service availability dropped below critical threshold (95.0%)",
        "evidence": {
          "rule_id": "RULE-AVAIL-CRIT",
          "metric": "availability_pct",
          "operator": "<",
          "threshold": 95.0,
          "observed_value": 0.0,
          "clear_threshold": 98.0
        }
      }
    ],
    "total": 1,
    "limit": 50,
    "offset": 0
  }
  ```

### 5.2 Get Alarm by ID
- **HTTP Method**: `GET`
- **Route**: `/api/v1/alarms/{alarm_id}`
- **Source**: `nexus/detection/api.py`
- **Path Parameters**:
  - `alarm_id` (string, required): Unique alarm identifier.
- **Response Status**:
  - `200 OK`: Alarm record returned.
  - `404 NOT FOUND`: Alarm not found.

### 5.3 List Detection Rules
- **HTTP Method**: `GET`
- **Route**: `/api/v1/detection/rules`
- **Source**: `nexus/detection/api.py`
- **Purpose**: Returns the configured static threshold rules and hysteresis recovery boundaries.
- **Response Status**: `200 OK`
- **Response Schema**:
  ```json
  {
    "items": [
      {
        "rule_id": "RULE-AVAIL-CRIT",
        "metric_name": "availability_pct",
        "operator": "<",
        "threshold": 95.0,
        "severity": "CRITICAL",
        "clear_threshold": 98.0,
        "enabled": true,
        "description": "Service availability dropped below critical threshold (95.0%)"
      },
      {
        "rule_id": "RULE-DROP-CRIT",
        "metric_name": "connection_drop_rate_pct",
        "operator": ">",
        "threshold": 5.0,
        "severity": "CRITICAL",
        "clear_threshold": 2.0,
        "enabled": true,
        "description": "Call/session drop rate spiked above critical threshold (5.0%)"
      }
    ],
    "total": 8
  }
  ```

---

## 6. Fault Simulation API

### 6.1 List Predefined Reference Scenarios
- **HTTP Method**: `GET`
- **Route**: `/api/v1/faults/scenarios`
- **Source**: `nexus/fault/api.py`
- **Purpose**: Returns catalog of 6 reference failure scenarios and activation status.
- **Response Status**: `200 OK`
- **Response Schema**:
  ```json
  {
    "scenarios": [
      {
        "scenario_key": "cell_outage",
        "scenario_id": "SCENARIO-CELL-OUTAGE-01",
        "name": "Single Cell Outage",
        "fault_type": "CELL_OUTAGE",
        "target_id": "CELL-01",
        "target_tier": "CELL",
        "description": "Single radio sector failure on CELL-01",
        "active": false
      },
      {
        "scenario_key": "backhaul_failure",
        "scenario_id": "SCENARIO-BACKHAUL-FAIL-01",
        "name": "Backhaul Transport Failure",
        "fault_type": "BACKHAUL_FAILURE",
        "target_id": "LINK-AGG-01-SITE-01",
        "target_tier": "SITE",
        "description": "Fiber cut on backhaul transport link from AGG-01 to SITE-01",
        "active": false
      },
      {
        "scenario_key": "radio_interference",
        "scenario_id": "SCENARIO-INTERFERENCE-01",
        "name": "Radio Interference",
        "fault_type": "RADIO_INTERFERENCE",
        "target_id": "CELL-05",
        "target_tier": "CELL",
        "description": "Severe external RF interference on CELL-05",
        "active": false
      },
      {
        "scenario_key": "cell_congestion",
        "scenario_id": "SCENARIO-CONGESTION-01",
        "name": "Cell Congestion",
        "fault_type": "CELL_CONGESTION",
        "target_id": "CELL-10",
        "target_tier": "CELL",
        "description": "Stadium event traffic surge causing cell saturation on CELL-10",
        "active": false
      },
      {
        "scenario_key": "site_power_failure",
        "scenario_id": "SCENARIO-POWER-FAIL-01",
        "name": "Site Power Failure",
        "fault_type": "SITE_POWER_FAILURE",
        "target_id": "SITE-04",
        "target_tier": "SITE",
        "description": "Mains grid outage with failed generator backup at SITE-04",
        "active": false
      },
      {
        "scenario_key": "core_router_failure",
        "scenario_id": "SCENARIO-CORE-FAIL-01",
        "name": "Core Router Failure",
        "fault_type": "CORE_ROUTER_FAILURE",
        "target_id": "CORE-01",
        "target_tier": "CORE",
        "description": "Central core router failure on CORE-01 collapsing connectivity across entire topology",
        "active": false
      }
    ],
    "total": 6
  }
  ```

### 6.2 Get Active Fault Status
- **HTTP Method**: `GET`
- **Route**: `/api/v1/faults/active`
- **Source**: `nexus/fault/api.py`
- **Purpose**: Returns current active scenario and affected node list.
- **Response Status**: `200 OK`

### 6.3 Activate Scenario
- **HTTP Method**: `POST`
- **Route**: `/api/v1/faults/scenarios/{scenario_id}/activate`
- **Source**: `nexus/fault/api.py`
- **Path Parameters**:
  - `scenario_id` (string, required): One of `cell_outage`, `backhaul_failure`, `radio_interference`, `cell_congestion`, `site_power_failure`, `core_router_failure`.
- **Request Body (Optional)**:
  ```json
  {
    "immediate": true,
    "base_time": null
  }
  ```
- **Response Status**:
  - `200 OK`: Scenario activated.
  - `400 BAD REQUEST`: Invalid parameters or fault conflict.
  - `404 NOT FOUND`: Scenario ID not recognized.

### 6.4 Deactivate Scenarios
- **HTTP Method**: `POST`
- **Route**: `/api/v1/faults/scenarios/deactivate`
- **Source**: `nexus/fault/api.py`
- **Purpose**: Restores network simulation to nominal baseline.
- **Response Status**: `200 OK`

---

## 7. Incident Management API

### 7.1 List Incidents
- **HTTP Method**: `GET`
- **Route**: `/api/v1/incidents`
- **Source**: `nexus/incidents/api.py`
- **Query Parameters**:
  - `status` (string, optional): Filter by `OPEN`, `ACKNOWLEDGED`, `RESOLVED`.
  - `severity` (string, optional): Filter by `CRITICAL`, `MAJOR`, `WARNING`, `MINOR`.
  - `limit` (integer, optional, default: 50, min: 1, max: 100): Page limit.
  - `offset` (integer, optional, default: 0, min: 0): Page offset.
- **Response Status**: `200 OK`
- **Response Schema**:
  ```json
  {
    "items": [
      {
        "incident_id": "INC-0da172cac7f0",
        "correlation_group_id": "CORR-SITE-01-20261123120500-001",
        "status": "OPEN",
        "severity": "CRITICAL",
        "priority": "P1",
        "title": "[CRITICAL] BACKHAUL_FAILURE on LINK-AGG-01-SITE-01",
        "description": "Fiber cut on backhaul transport link from AGG-01 to SITE-01 isolating downstream branch",
        "alarm_ids": [
          "ALARM-SITE-01-RULE-AVAIL-CRIT-00001",
          "ALARM-CELL-01-RULE-AVAIL-CRIT-00002"
        ],
        "affected_node_ids": ["SITE-01", "CELL-01", "CELL-02", "CELL-03"],
        "suspected_cause_type": "BACKHAUL_FAILURE",
        "suspected_target_id": "LINK-AGG-01-SITE-01",
        "suspected_target_type": "TRANSPORT_LINK",
        "rca_confidence_score": 0.85,
        "rca_hypotheses": [
          {
            "hypothesis_id": "HYP-BACKHAUL-01",
            "cause_type": "BACKHAUL_FAILURE",
            "target_id": "LINK-AGG-01-SITE-01",
            "target_type": "TRANSPORT_LINK",
            "confidence_score": 0.85,
            "explanation": "Elevated latency and availability loss across subordinate nodes align with backhaul severance."
          }
        ],
        "rca_evidence": [
          {
            "source_node_id": "SITE-01",
            "metric_name": "availability_pct",
            "observed_value": 0.0,
            "threshold_or_baseline": 95.0,
            "reasoning": "Availability collapse",
            "severity": "CRITICAL",
            "evidence_source": "ALARM"
          }
        ],
        "created_at": "2026-11-23T12:05:00Z",
        "ack_deadline": "2026-11-23T12:20:00Z",
        "resolve_deadline": "2026-11-23T13:05:00Z",
        "acknowledged_at": null,
        "acknowledged_by": null,
        "resolved_at": null,
        "resolved_by": null,
        "sla_status": {
          "ack_breached": false,
          "resolve_breached": false,
          "ack_time_seconds": null,
          "resolve_time_seconds": null,
          "evaluation_timestamp": "2026-11-23T12:10:00Z"
        }
      }
    ],
    "total": 1,
    "limit": 50,
    "offset": 0
  }
  ```

### 7.2 Create Incident
- **HTTP Method**: `POST`
- **Route**: `/api/v1/incidents`
- **Source**: `nexus/incidents/api.py`
- **Purpose**: Persist a new operational incident from correlation and RCA diagnostic outputs.
- **Request Body**:
  ```json
  {
    "correlation_group_id": "CORR-MANUAL-001",
    "anchor_node_id": "SITE-01",
    "root_cause_tier": "SITE",
    "alarms": [
      {
        "alarm_id": "ALARM-SITE-01-RULE-AVAIL-CRIT-00001",
        "node_id": "SITE-01",
        "rule_id": "RULE-AVAIL-CRIT",
        "metric_name": "availability_pct",
        "source": "THRESHOLD",
        "severity": "CRITICAL",
        "current_value": 0.0,
        "threshold": 95.0,
        "first_seen": "2026-11-23T12:05:00Z",
        "last_seen": "2026-11-23T12:05:00Z",
        "observation_count": 1,
        "status": "ACTIVE"
      }
    ],
    "time_window_start": "2026-11-23T12:05:00Z",
    "time_window_end": "2026-11-23T12:05:00Z",
    "correlation_reason": "Manual operator triage",
    "suspected_cause_type": "BACKHAUL_FAILURE",
    "suspected_target_id": "LINK-AGG-01-SITE-01",
    "suspected_target_type": "TRANSPORT_LINK",
    "rca_confidence_score": 0.9,
    "hypotheses": [],
    "evidence_items": [],
    "created_by": "OPERATOR_ADMIN"
  }
  ```
- **Response Status**:
  - `201 CREATED`: Incident created.
  - `409 CONFLICT`: Duplicate `correlation_group_id`.
  - `422 UNPROCESSABLE ENTITY`: Schema or validation failure.

### 7.3 Get Incident Metrics & SLA Report
- **HTTP Method**: `GET`
- **Route**: `/api/v1/incidents/metrics`
- **Source**: `nexus/incidents/api.py`
- **Purpose**: Calculates system-wide operational metrics (MTTA, MTTR, MTTD, SLA compliance).
- **Response Status**: `200 OK`
- **Response Schema**:
  ```json
  {
    "total_incidents": 10,
    "open_incident_count": 2,
    "incidents_by_status": {
      "OPEN": 1,
      "ACKNOWLEDGED": 1,
      "RESOLVED": 8
    },
    "incidents_by_severity": {
      "CRITICAL": 3,
      "MAJOR": 4,
      "WARNING": 2,
      "MINOR": 1
    },
    "mtta_seconds": 184.2,
    "mttr_seconds": 1250.6,
    "mttd_seconds": 12.4,
    "total_incidents_evaluated": 10,
    "compliant_incident_count": 9,
    "breached_incident_count": 1,
    "ack_sla_breached_count": 0,
    "resolve_sla_breached_count": 1,
    "sla_compliance_pct": 90.0,
    "as_of": "2026-11-23T12:15:00Z"
  }
  ```

### 7.4 Get Incident by ID
- **HTTP Method**: `GET`
- **Route**: `/api/v1/incidents/{incident_id}`
- **Source**: `nexus/incidents/api.py`
- **Response Status**:
  - `200 OK`: Incident returned.
  - `404 NOT FOUND`: Incident not found.

### 7.5 Acknowledge Incident
- **HTTP Method**: `POST`
- **Route**: `/api/v1/incidents/{incident_id}/acknowledge`
- **Source**: `nexus/incidents/api.py`
- **Request Body**:
  ```json
  {
    "actor": "noc_operator_john"
  }
  ```
- **State Transition**: Valid only from `OPEN` to `ACKNOWLEDGED`.
- **Response Status**:
  - `200 OK`: Transition successful; `acknowledged_at` and `acknowledged_by` recorded; SLA ack status frozen.
  - `400 BAD REQUEST`: Invalid transition (e.g. incident is already `RESOLVED` or `ACKNOWLEDGED`).
  - `404 NOT FOUND`: Incident ID does not exist.

### 7.6 Resolve Incident
- **HTTP Method**: `POST`
- **Route**: `/api/v1/incidents/{incident_id}/resolve`
- **Source**: `nexus/incidents/api.py`
- **Request Body**:
  ```json
  {
    "actor": "noc_operator_john",
    "notes": "Replaced faulty SFP transceiver on upstream aggregation port."
  }
  ```
- **State Transition**: Valid from `OPEN` or `ACKNOWLEDGED` to `RESOLVED`.
- **Response Status**:
  - `200 OK`: Transition successful; `resolved_at`, `resolved_by`, and timeline event persisted; all SLA evaluations permanently frozen.
  - `400 BAD REQUEST`: Incident is already `RESOLVED`.
  - `404 NOT FOUND`: Incident ID does not exist.

### 7.7 Get Incident Timeline History
- **HTTP Method**: `GET`
- **Route**: `/api/v1/incidents/{incident_id}/timeline`
- **Source**: `nexus/incidents/api.py`
- **Purpose**: Returns chronologically ordered immutable audit records for an incident.
- **Response Status**: `200 OK`
- **Response Schema**:
  ```json
  [
    {
      "event_id": "EVT-01a2b3c4d5e6",
      "incident_id": "INC-0da172cac7f0",
      "event_type": "CREATED",
      "timestamp": "2026-11-23T12:05:00Z",
      "actor": "SYSTEM",
      "actor_type": "SYSTEM",
      "details": {
        "correlation_group_id": "CORR-SITE-01-20261123120500-001",
        "severity": "CRITICAL"
      }
    },
    {
      "event_id": "EVT-11a2b3c4d5e7",
      "incident_id": "INC-0da172cac7f0",
      "event_type": "ACKNOWLEDGED",
      "timestamp": "2026-11-23T12:08:14Z",
      "actor": "noc_operator_john",
      "actor_type": "OPERATOR",
      "details": {
        "previous_status": "OPEN",
        "new_status": "ACKNOWLEDGED"
      }
    },
    {
      "event_id": "EVT-21a2b3c4d5e8",
      "incident_id": "INC-0da172cac7f0",
      "event_type": "RESOLVED",
      "timestamp": "2026-11-23T12:22:30Z",
      "actor": "noc_operator_john",
      "actor_type": "OPERATOR",
      "details": {
        "notes": "Replaced faulty SFP transceiver on upstream aggregation port.",
        "previous_status": "ACKNOWLEDGED",
        "new_status": "RESOLVED"
      }
    }
  ]
  ```

---

## 8. Real-Time WebSocket Streaming Interface

### 8.1 Connection Specification
- **URL**: `ws://<host>:<port>/ws/live`
- **Protocol**: Standard WebSocket (RFC 6455)
- **Handshake**: HTTP `101 Switching Protocols`
- **Serialization**: Text frames containing stringified JSON

### 8.2 Client-to-Server Inbound Frames
- **Heartbeat Ping**:
  Clients may send plain text `"PING"` or `{"action": "ping"}`.
  The server responds with `"PONG"`.

### 8.3 Server-to-Client Canonical Envelope
All outbound broadcast events share the immutable 3-field envelope:
```json
{
  "type": "<EVENT_TYPE_STRING>",
  "timestamp": "2026-11-23T12:05:00.000000Z",
  "payload": { ... }
}
```

### 8.4 Event Catalog & Payloads

#### `TELEMETRY_SNAPSHOT`
Emitted whenever a new telemetry observation is recorded:
```json
{
  "type": "TELEMETRY_SNAPSHOT",
  "timestamp": "2026-11-23T12:05:00Z",
  "payload": {
    "node_id": "CELL-01",
    "timestamp": "2026-11-23T12:05:00Z",
    "performance": { "throughput_mbps": 45.2, "latency_ms": 12.1 },
    "reliability": { "connection_drop_rate_pct": 0.2, "availability_pct": 99.9, "handover_success_rate_pct": 99.1 },
    "radio": { "rsrp_dbm": -85.2, "sinr_db": 19.4, "prb_utilization_pct": 38.0 }
  }
}
```

#### `ALARM_CREATED`
Emitted on initial transition from inactive to active:
```json
{
  "type": "ALARM_CREATED",
  "timestamp": "2026-11-23T12:05:00Z",
  "payload": {
    "alarm_id": "ALARM-CELL-01-RULE-AVAIL-CRIT-00001",
    "node_id": "CELL-01",
    "rule_id": "RULE-AVAIL-CRIT",
    "severity": "CRITICAL",
    "current_value": 0.0,
    "threshold": 95.0,
    "status": "ACTIVE"
  }
}
```

#### `ALARM_UPDATED`
Emitted when an active alarm receives repeated breach observations:
```json
{
  "type": "ALARM_UPDATED",
  "timestamp": "2026-11-23T12:06:00Z",
  "payload": {
    "alarm_id": "ALARM-CELL-01-RULE-AVAIL-CRIT-00001",
    "observation_count": 2,
    "current_value": 0.0,
    "last_seen": "2026-11-23T12:06:00Z"
  }
}
```

#### `ALARM_CLEARED`
Emitted when metric values satisfy hysteresis recovery conditions:
```json
{
  "type": "ALARM_CLEARED",
  "timestamp": "2026-11-23T12:20:00Z",
  "payload": {
    "alarm_id": "ALARM-CELL-01-RULE-AVAIL-CRIT-00001",
    "cleared_at": "2026-11-23T12:20:00Z",
    "status": "CLEARED"
  }
}
```

#### `INCIDENT_CREATED`
Emitted upon persistent insertion of a new incident ticket:
```json
{
  "type": "INCIDENT_CREATED",
  "timestamp": "2026-11-23T12:05:00Z",
  "payload": {
    "incident_id": "INC-0da172cac7f0",
    "correlation_group_id": "CORR-SITE-01-20261123120500-001",
    "status": "OPEN",
    "severity": "CRITICAL",
    "priority": "P1",
    "title": "[CRITICAL] BACKHAUL_FAILURE on LINK-AGG-01-SITE-01"
  }
}
```

#### `INCIDENT_ACKNOWLEDGED`
Emitted when an operator claims ownership of an incident:
```json
{
  "type": "INCIDENT_ACKNOWLEDGED",
  "timestamp": "2026-11-23T12:08:14Z",
  "payload": {
    "incident_id": "INC-0da172cac7f0",
    "status": "ACKNOWLEDGED",
    "acknowledged_at": "2026-11-23T12:08:14Z",
    "acknowledged_by": "noc_operator_john"
  }
}
```

#### `INCIDENT_RESOLVED`
Emitted when incident remediation is complete:
```json
{
  "type": "INCIDENT_RESOLVED",
  "timestamp": "2026-11-23T12:22:30Z",
  "payload": {
    "incident_id": "INC-0da172cac7f0",
    "status": "RESOLVED",
    "resolved_at": "2026-11-23T12:22:30Z",
    "resolved_by": "noc_operator_john"
  }
}
```

#### `TOPOLOGY_STATUS_CHANGED`
Emitted when a node transitions operational status (e.g. `ONLINE` to `OFFLINE`):
```json
{
  "type": "TOPOLOGY_STATUS_CHANGED",
  "timestamp": "2026-11-23T12:05:00Z",
  "payload": {
    "node_id": "SITE-01",
    "previous_status": "ONLINE",
    "new_status": "DEGRADED",
    "timestamp": "2026-11-23T12:05:00Z"
  }
}
```
