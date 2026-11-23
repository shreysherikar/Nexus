# NEXUS — REST API & WebSocket Protocol Reference

This document provides the authoritative reference specification for the **NEXUS Network Intelligence & Incident Management Platform** HTTP REST API and real-time WebSocket protocol.

All endpoints adhere to OpenAPI 3.0 standards and are documented interactively via Swagger UI at `/docs` and ReDoc at `/redoc`.

---

## Architecture Overview

```
                                      ┌─────────────────────────────────────────┐
                                      │            API Consumers                │
                                      │     (NOC Dashboard, Scripts, CLI)       │
                                      └─────────────┬───────────────────────────┘
                                                    │
                                                    ▼
                                      ┌─────────────────────────────────────────┐
                                      │       Nginx Reverse Proxy (:80)         │
                                      └─────────────┬───────────────────────────┘
                                                    │
                           ┌────────────────────────┴────────────────────────┐
                           │ /api/v1/*, /health, /ready                       │ /ws/live
                           ▼                                                 ▼
             ┌───────────────────────────┐                     ┌───────────────────────────┐
             │    FastAPI HTTP Engine    │                     │   WebSocket Broadcaster   │
             │   (Subsystem Routers)     │                     │ (Bounded Per-Client Queue)│
             └─────────────┬─────────────┘                     └─────────────┬─────────────┘
                           │                                                 │
            ┌──────────────┼──────────────┬──────────────┐                   │
            ▼              ▼              ▼              ▼                   ▼
       [Topology]     [Telemetry]      [Alarms]     [Incidents]     [Push Event Envelopes]
       In-Memory      Bounded FIFO    Thresholds    PostgreSQL/
       Hierarchy      Store (10k)      Manager       SQLAlchemy
```

---

## Global API Conventions

### Base Path & Versioning
- **Current Version**: `v1`
- **Prefix**: `/api/v1`
- **Interactive Documentation**: `http://localhost:8000/docs` (Swagger UI), `http://localhost:8000/redoc` (ReDoc)
- **OpenAPI Schema**: `http://localhost:8000/openapi.json`

### Content Type & Caching
- All request and response bodies use `Content-Type: application/json`.
- All `/api/` responses carry anti-caching HTTP response headers:
  ```http
  Cache-Control: no-cache, no-store, must-revalidate, max-age=0
  Pragma: no-cache
  Expires: 0
  ```

### Timestamps
- All timestamps sent to or returned by the API are formatted in **ISO 8601 UTC** with explicit offset: `YYYY-MM-DDTHH:MM:SSZ` or `YYYY-MM-DDTHH:MM:SS+00:00`.

### Error Responses
Domain exceptions return structured JSON error payloads with standard HTTP status codes:
```json
{
  "detail": "Descriptive human-readable explanation of error",
  "error_code": "ERROR_CLASSIFICATION_CODE"
}
```

| HTTP Status | Error Code | Description |
| :--- | :--- | :--- |
| `400 Bad Request` | `INVALID_STATE_TRANSITION` | Attempted invalid incident state machine transition |
| `404 Not Found` | `INCIDENT_NOT_FOUND` | Specified incident ID does not exist |
| `404 Not Found` | `NODE_NOT_FOUND` | Specified topology node does not exist in registry |
| `409 Conflict` | `DUPLICATE_INCIDENT` | Incident already exists for the correlation group |
| `409 Conflict` | `TELEMETRY_GENERATION_IN_PROGRESS` | Telemetry step generation lock is currently held |
| `422 Unprocessable Entity` | `INVALID_INCIDENT_DATA` | Request validation failed (schema/type constraints) |
| `503 Service Unavailable` | `SERVICE_NOT_READY` | One or more critical subsystems failed readiness probe |

---

## System Probes & Health Endpoints

### 1. Platform Root Overview
- **Path**: `GET /`
- **Tags**: `system`
- **Summary**: Returns platform metadata and core system links.
- **Response**: `200 OK`
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

### 2. Service Liveness Probe
- **Path**: `GET /health`
- **Tags**: `system`
- **Summary**: Lightweight liveness probe for process uptime verification.
- **Response**: `200 OK`
```json
{
  "status": "healthy"
}
```

### 3. Subsystem Readiness Probe
- **Path**: `GET /ready`
- **Tags**: `system`
- **Summary**: Validates connectivity and operational health across all six internal subsystems.
- **Security Safeguard**: Returns clean operational state strings (`ready`, `not_ready`, `error`, `unhealthy`) without exposing raw database connection strings, credentials, or internal stack traces.
- **Responses**:
  - `200 OK`: All subsystems ready.
  - `503 Service Unavailable`: One or more subsystems unhealthy.
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

### 4. Prometheus Metrics Exposition
- **Path**: `GET /metrics`
- **Tags**: `system`
- **Summary**: Exposes OpenMetrics / Prometheus plaintext exposition format.
- **Security Safeguard**: Direct access through the frontend Nginx reverse proxy returns `404 Not Found`. Must be scraped directly on backend port 8000 over the internal Docker network.
- **Response**: `200 OK` (`Content-Type: text/plain; version=0.0.4`)

---

## Network Topology API

### 1. Retrieve Complete Topology
- **Path**: `GET /api/v1/topology`
- **Summary**: Returns authoritative 27-node network inventory with hierarchy and geographic coordinates.
- **Response**: `200 OK`
```json
{
  "nodes": [
    {
      "node_id": "CORE-01",
      "node_type": "CORE",
      "parent_id": null,
      "status": "ONLINE",
      "latitude": 59.3293,
      "longitude": 18.0686,
      "children": ["AGG-01", "AGG-02"]
    },
    {
      "node_id": "AGG-01",
      "node_type": "AGGREGATION",
      "parent_id": "CORE-01",
      "status": "ONLINE",
      "latitude": 59.3325,
      "longitude": 18.0649,
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

### 2. Retrieve Topology Node by ID
- **Path**: `GET /api/v1/topology/nodes/{node_id}`
- **Parameters**: `node_id` (path, string, e.g. `CELL-01`)
- **Responses**:
  - `200 OK`: Node found.
  - `404 Not Found`: Node ID does not exist in registry.
```json
{
  "node_id": "CELL-01",
  "node_type": "CELL",
  "parent_id": "SITE-01",
  "status": "ONLINE",
  "latitude": 59.3326,
  "longitude": 18.0651,
  "children": []
}
```

---

## Telemetry & Synthetic Simulation API

### 1. Query Telemetry Snapshots
- **Path**: `GET /api/v1/telemetry`
- **Query Parameters**:
  - `node_id` (string, optional): Filter by specific node identifier.
  - `node_type` (string, optional): Filter by tier (`CORE`, `AGGREGATION`, `SITE`, `CELL`).
  - `start_time` (datetime ISO 8601, optional): Inclusive start time UTC.
  - `end_time` (datetime ISO 8601, optional): Inclusive end time UTC.
  - `limit` (integer, default `50`, min `1`, max `1000`): Results per page.
  - `offset` (integer, default `0`, min `0`): Pagination offset.
- **Responses**:
  - `200 OK`: Success.
  - `422 Unprocessable Entity`: Invalid `node_type` or `start_time > end_time`.
```json
{
  "items": [
    {
      "node_id": "CELL-01",
      "timestamp": "2026-11-22T10:00:00Z",
      "performance": {
        "throughput_mbps": 48.25,
        "latency_ms": 14.5
      },
      "reliability": {
        "connection_drop_rate_pct": 0.45,
        "availability_pct": 99.98,
        "handover_success_rate_pct": 98.7
      },
      "radio": {
        "rsrp_dbm": -88.5,
        "sinr_db": 18.2,
        "prb_utilization_pct": 52.4
      }
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### 2. Generate Discrete Telemetry Step
- **Path**: `POST /api/v1/telemetry/generate-step`
- **Summary**: Operator-triggered simulation cycle generating exactly one discrete synthetic telemetry observation per node.
- **Responses**:
  - `200 OK`: Step generated and broadcast.
  - `409 Conflict`: Step generation already in progress.
```json
{
  "generated_count": 27,
  "timestamp": "2026-11-22T10:01:00Z",
  "message": "Deterministic simulation step generated and recorded into in-memory store."
}
```

---

## Alarm Management API

### 1. List Alarms
- **Path**: `GET /api/v1/alarms`
- **Query Parameters**:
  - `node_id` (string, optional): Filter by node ID.
  - `severity` (string, optional): Filter by severity (`WARNING`, `MAJOR`, `CRITICAL`).
  - `status` (string, optional): Filter by lifecycle state (`ACTIVE`, `CLEARED`).
  - `limit` (integer, default `50`, min `1`, max `100`): Page limit.
  - `offset` (integer, default `0`, min `0`): Pagination offset.
- **Response**: `200 OK`
```json
{
  "items": [
    {
      "alarm_id": "ALM-CELL-01-HIGH_LATENCY-1732270000",
      "node_id": "CELL-01",
      "rule_id": "RULE-LATENCY-CRIT",
      "metric_name": "latency_ms",
      "source": "THRESHOLD",
      "severity": "CRITICAL",
      "current_value": 125.4,
      "threshold": 100.0,
      "first_seen": "2026-11-22T10:00:00Z",
      "last_seen": "2026-11-22T10:05:00Z",
      "observation_count": 5,
      "status": "ACTIVE",
      "cleared_at": null,
      "description": "Critical latency threshold exceeded on node CELL-01",
      "evidence": {
        "observed_value": 125.4,
        "threshold": 100.0
      }
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### 2. Get Alarm by ID
- **Path**: `GET /api/v1/alarms/{alarm_id}`
- **Responses**:
  - `200 OK`: Alarm record returned.
  - `404 Not Found`: Alarm ID does not exist.

### 3. List Detection Rules
- **Path**: `GET /api/v1/detection/rules`
- **Summary**: Returns authoritative catalog of configured telecom threshold rules.
- **Response**: `200 OK`
```json
{
  "items": [
    {
      "rule_id": "RULE-LATENCY-CRIT",
      "metric_name": "latency_ms",
      "operator": "GT",
      "threshold": 100.0,
      "clear_threshold": 80.0,
      "severity": "CRITICAL",
      "node_types": ["CELL", "SITE"],
      "description": "Latency exceeds critical limit",
      "enabled": true
    }
  ],
  "total": 8
}
```

---

## Fault Injection API

### 1. List Predefined Reference Scenarios
- **Path**: `GET /api/v1/faults/scenarios`
- **Summary**: Catalog of standard telecom reference fault scenarios.
- **Response**: `200 OK`

### 2. Get Active Fault Scenario Status
- **Path**: `GET /api/v1/faults/active`
- **Summary**: Returns current active scenario and affected topology targets.
- **Response**: `200 OK`
```json
{
  "active": true,
  "scenario_key": "cell_outage",
  "name": "Single Cell Outage",
  "description": "Simulates sudden complete cell outage on CELL-01",
  "affected_nodes": ["CELL-01"],
  "start_time": "2026-11-22T10:00:00Z"
}
```

### 3. Activate Fault Scenario
- **Path**: `POST /api/v1/faults/scenarios/{scenario_id}/activate`
- **Path Parameters**: `scenario_id` (`cell_outage`, `backhaul_failure`, `radio_interference`, `cell_congestion`, `site_power_failure`)
- **Request Body** (optional):
```json
{
  "immediate": true,
  "base_time": null
}
```
- **Responses**:
  - `200 OK`: Scenario activated.
  - `400 Bad Request`: Scenario conflict or active fault on target.
  - `404 Not Found`: Invalid scenario ID.

### 4. Deactivate Active Fault Scenario
- **Path**: `POST /api/v1/faults/scenarios/deactivate`
- **Summary**: Halts all active faults, restoring nominal telemetry profiles.
- **Response**: `200 OK`

---

## Incident Management & SLA Tracking API

### 1. Create Incident
- **Path**: `POST /api/v1/incidents`
- **Summary**: Ingests correlated alarms and RCA hypotheses to instantiate a managed operational incident.
- **Request Body**:
```json
{
  "correlation_group_id": "GRP-20261122-001",
  "anchor_node_id": "SITE-01",
  "root_cause_tier": "SITE",
  "time_window_start": "2026-11-22T10:00:00Z",
  "time_window_end": "2026-11-22T10:05:00Z",
  "correlation_reason": "Multiple cell dropouts anchored at SITE-01",
  "alarms": [
    {
      "alarm_id": "ALM-CELL-01-AVAIL",
      "node_id": "CELL-01",
      "rule_id": "RULE-AVAIL-CRIT",
      "metric_name": "availability_pct",
      "source": "THRESHOLD",
      "severity": "CRITICAL",
      "current_value": 0.0,
      "threshold": 95.0,
      "first_seen": "2026-11-22T10:00:00Z",
      "last_seen": "2026-11-22T10:05:00Z",
      "observation_count": 3,
      "status": "ACTIVE"
    }
  ],
  "suspected_cause_type": "SITE_POWER_FAILURE",
  "suspected_target_id": "SITE-01",
  "suspected_target_type": "NODE",
  "rca_confidence_score": 0.95,
  "created_by": "auto-correlation-engine"
}
```
- **Responses**:
  - `201 Created`: Incident created. Returns the instantiated incident with its server-generated `incident_id` (`INC-<hex12>`):
```json
{
  "incident_id": "INC-8f3a1b02cd4e",
  "correlation_group_id": "GRP-20261122-001",
  "status": "OPEN",
  "severity": "CRITICAL",
  "priority": "P1",
  "title": "Incident GRP-20261122-001: SITE_POWER_FAILURE on SITE-01",
  "description": "Diagnosed SITE_POWER_FAILURE on SITE-01",
  "alarm_ids": ["ALM-CELL-01-AVAIL"],
  "affected_node_ids": ["CELL-01"],
  "suspected_cause_type": "SITE_POWER_FAILURE",
  "suspected_target_id": "SITE-01",
  "suspected_target_type": "NODE",
  "rca_confidence_score": 0.95,
  "created_at": "2026-11-22T10:05:00Z",
  "ack_deadline": "2026-11-22T10:20:00Z",
  "resolve_deadline": "2026-11-22T12:05:00Z",
  "sla_status": {
    "ack_breached": false,
    "resolve_breached": false,
    "ack_time_seconds": null,
    "resolve_time_seconds": null,
    "evaluation_timestamp": "2026-11-22T10:05:00Z"
  }
}
```
  - `409 Conflict`: Duplicate incident for correlation group.
  - `422 Unprocessable Entity`: Validation error or missing required targets.

### 2. List Incidents
- **Path**: `GET /api/v1/incidents`
- **Query Parameters**:
  - `status` (`OPEN`, `ACKNOWLEDGED`, `RESOLVED`, optional)
  - `severity` (`CRITICAL`, `MAJOR`, `WARNING`, `MINOR`, optional)
  - `limit` (default `50`, min `1`, max `100`)
  - `offset` (default `0`, min `0`)
- **Response**: `200 OK`

### 3. Retrieve Incident Details
- **Path**: `GET /api/v1/incidents/{incident_id}`
- **Responses**:
  - `200 OK`: Full incident record with SLA status and RCA hypotheses.
  - `404 Not Found`: Incident ID not found.

### 4. Acknowledge Incident
- **Path**: `POST /api/v1/incidents/{incident_id}/acknowledge`
- **State Transition**: `OPEN -> ACKNOWLEDGED`
- **Request Body**:
```json
{
  "actor": "operator_jane"
}
```
- **Responses**:
  - `200 OK`: Incident acknowledged.
  - `400 Bad Request`: Incident is already acknowledged or resolved.
  - `404 Not Found`: Incident not found.

### 5. Resolve Incident
- **Path**: `POST /api/v1/incidents/{incident_id}/resolve`
- **State Transition**: `ACKNOWLEDGED -> RESOLVED`
- **Request Body**:
```json
{
  "actor": "operator_jane",
  "notes": "Power restored via backup generator; all cells reporting nominal telemetry."
}
```
- **Responses**:
  - `200 OK`: Incident resolved.
  - `400 Bad Request`: Incident not in ACKNOWLEDGED state or empty resolution notes.
  - `404 Not Found`: Incident not found.

### 6. Incident Audit Timeline
- **Path**: `GET /api/v1/incidents/{incident_id}/timeline`
- **Summary**: Chronological append-only event trail of incident lifecycle changes.
- **Response**: `200 OK`

### 7. Operational & SLA Analytics
- **Path**: `GET /api/v1/incidents/metrics`
- **Summary**: Real-time aggregated MTTA, MTTR, MTTD, breach totals, and compliance percentage computed via streaming database iteration.
- **Response**: `200 OK`
```json
{
  "total_incidents": 12,
  "open_incident_count": 2,
  "incidents_by_status": {
    "OPEN": 2,
    "ACKNOWLEDGED": 1,
    "RESOLVED": 9
  },
  "incidents_by_severity": {
    "CRITICAL": 3,
    "MAJOR": 4,
    "WARNING": 3,
    "MINOR": 2
  },
  "mtta_seconds": 142.5,
  "mttr_seconds": 1820.0,
  "mttd_seconds": 18.4,
  "total_incidents_evaluated": 12,
  "compliant_incident_count": 11,
  "breached_incident_count": 1,
  "ack_sla_breached_count": 0,
  "resolve_sla_breached_count": 1,
  "sla_compliance_pct": 91.67,
  "as_of": "2026-11-22T10:15:00Z"
}
```

---

## Real-Time WebSocket Protocol

### Connection URL
- **Path**: `ws://localhost:8000/ws/live` (or reverse-proxied at `ws://localhost:3000/ws/live`)
- **Transport**: Standard WebSocket (RFC 6455)

### Outbound Serialization Architecture
All outbound frames on each client connection are strictly serialized through an isolated asynchronous sender task (`sender_task`). Concurrent writes to `websocket.send_text()` are strictly prohibited.

```
                           ┌───────────────────────────────┐
                           │   Inbound Client Messages     │
                           └───────────────┬───────────────┘
                                           │
                                           ▼
                                 [receiver_task]
                                           │
                           PING frame      │
                                           ▼
                           ┌───────────────────────────────┐
                           │   pong_queue (Maxsize: 20)    │
                           └───────────────┬───────────────┘
                                           │
  ┌────────────────────────────────┐       │
  │ event_queue (Maxsize: 100)     │       │
  │ (Domain events from Broadcaster│       │
  └────────────────┬───────────────┘       │
                   │                       │
                   ▼                       ▼
            ┌─────────────────────────────────────┐
            │             sender_task             │
            │  - Max 3 consecutive PONGs priority │
            │  - Stashed event preservation       │
            │  - Serialized websocket.send_text   │
            └──────────────────┬──────────────────┘
                               │
                               ▼
            ┌─────────────────────────────────────┐
            │         Single Outbound Wire        │
            └─────────────────────────────────────┘
```

### Heartbeat PING / PONG
Clients or proxies maintain connectivity by sending PING frames:
- **Client Frame**:
  ```json
  {"type": "PING"}
  ```
- **Server Response**:
  ```json
  {"type": "PONG"}
  ```
- Priority Policy: Outbound PONG frames are given high delivery priority up to 3 consecutive frames before interleaving pending broadcast domain events, preventing starvation in either direction.

### Canonical Live Event Envelope
All server push events adhere to the immutable envelope structure:
```json
{
  "type": "<EVENT_TYPE>",
  "timestamp": "2026-11-22T10:00:00Z",
  "payload": { ... }
}
```

### Event Catalog

| Event Type | Trigger Subsystem | Payload Key Elements |
| :--- | :--- | :--- |
| `TELEMETRY_SNAPSHOT` | `telemetry.store` | `node_id`, `timestamp`, `performance`, `reliability`, `radio` |
| `ALARM_CREATED` | `detection.service` | `alarm_id`, `node_id`, `rule_id`, `severity`, `current_value`, `threshold` |
| `ALARM_UPDATED` | `detection.service` | `alarm_id`, `node_id`, `current_value`, `last_seen`, `observation_count` |
| `ALARM_CLEARED` | `detection.service` | `alarm_id`, `node_id`, `cleared_at` |
| `INCIDENT_CREATED` | `incidents.service` | `incident_id`, `correlation_group_id`, `severity`, `status`, `title` |
| `INCIDENT_ACKNOWLEDGED` | `incidents.service` | `incident_id`, `status`, `acknowledged_by`, `acknowledged_at` |
| `INCIDENT_RESOLVED` | `incidents.service` | `incident_id`, `status`, `resolved_by`, `resolved_at`, `notes` |
| `TOPOLOGY_STATUS_CHANGED` | `topology.registry` | `node_id`, `previous_status`, `new_status`, `timestamp` |

### Backpressure & Disconnection Policy
- **Queue Bounds**: Each subscriber has a private queue bounded to 100 events.
- **Eviction Strategy**: FIFO eviction of oldest events upon overflow with metrics tracking (`dropped_events_count`).
- **Clean Teardown**: Upon connection disconnect, queues are emptied, tasks are cleanly cancelled, and subscriber references are purged from registry locks.
