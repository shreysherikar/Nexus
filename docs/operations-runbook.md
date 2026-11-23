# NEXUS Operations Runbook

## 1. Overview & Operational Responsibilities

This runbook provides complete operational guidance for deploying, operating, verifying, and troubleshooting the **NEXUS Network Intelligence & Incident Management Platform**.

NEXUS provides real-time telemetry processing, anomaly detection, topological alarm correlation, Root Cause Analysis (RCA), and incident lifecycle tracking across a simulated 27-node telecommunications network.

---

## 2. Prerequisites & Environment Setup

### 2.1 Software Prerequisites

- **Python**: $\ge 3.11$ (Python 3.11 or 3.12 recommended)
- **Node.js**: $\ge 18$ (Node.js 20 LTS recommended)
- **Docker & Docker Compose**: Docker $\ge 24.0$, Docker Compose v2
- **PostgreSQL**: Version 15+ (when running natively without Docker)

### 2.2 Local Development Setup (Native Workstation)

```bash
# 1. Clone repository and navigate to root
cd nexus-network-intelligence

# 2. Python virtual environment setup
python -m venv .venv
# On Linux / macOS:
source .venv/bin/activate
# On Windows PowerShell:
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -e ".[test]"

# 3. Frontend dependency installation
cd frontend
npm ci
cd ..
```

---

## 3. Containerized Deployment (Docker Compose)

The production-like deployment runs five containerized services orchestrated via Docker Compose:
- `nexus-postgres`: PostgreSQL 15 database storing persistent incidents and timeline events
- `nexus-backend`: FastAPI application exposing REST endpoints and WebSocket feeds
- `nexus-frontend`: Nginx serving compiled React assets and reverse-proxying API requests
- `nexus-prometheus`: Prometheus server scraping backend metric endpoints
- `nexus-grafana`: Grafana dashboard server visualizing system and network telemetry

### 3.1 Environment Configuration

```bash
# Copy environment template
cp .env.example .env

# Generate secure PostgreSQL and Grafana credentials
# Linux / macOS:
openssl rand -hex 32
# Windows PowerShell:
-join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
```

Update `.env` with strong passwords for `POSTGRES_PASSWORD` and `GRAFANA_ADMIN_PASSWORD`.

### 3.2 Launching Services

```bash
# Build and launch all services in detached mode
docker compose up --build -d

# Verify container health
docker compose ps
```

Expected status:
- `nexus-postgres`: Up (healthy)
- `nexus-backend`: Up (healthy)
- `nexus-frontend`: Up (healthy)
- `nexus-prometheus`: Up (running)
- `nexus-grafana`: Up (running)

### 3.3 Health and Readiness Verification

Query the health and readiness probes:

```bash
# Liveness probe
curl -s http://127.0.0.1:8000/health
# Response: {"status":"healthy"}

# Readiness probe
curl -s http://127.0.0.1:8000/ready
# Expected response:
# {
#   "status": "ready",
#   "components": {
#     "topology": "ready",
#     "broadcaster": "ready",
#     "telemetry_store": "ready",
#     "alarm_service": "ready",
#     "fault_service": "ready",
#     "database": "ready"
#   }
# }
```

---

## 4. Operational Workflows & Fault Simulation

### 4.1 Generating Telemetry Steps

In the default state, telemetry is generated per discrete step on demand:

```bash
# Generate a single telemetry observation step across all 27 nodes
curl -X POST http://127.0.0.1:8000/api/v1/telemetry/generate-step
```

In the NOC web dashboard (`http://localhost:3000/kpis`), click **"Generate One Telemetry Step"** in the top action bar to populate live charts.

### 4.2 Executing Reference Fault Scenarios

NEXUS includes six deterministic fault scenarios:

#### Scenario 1: Single Cell Outage (`cell_outage`)
- **Target**: `CELL-01`
- **Impact**: Cell throughput drops to 0 Mbps, availability to 0%, drop rate to 100%.

```bash
# Activate fault
curl -X POST http://127.0.0.1:8000/api/v1/faults/scenarios/cell_outage/activate

# Advance simulation step
curl -X POST http://127.0.0.1:8000/api/v1/telemetry/generate-step

# Query raised alarms
curl -s "http://127.0.0.1:8000/api/v1/alarms?node_id=CELL-01&status=ACTIVE"

# Deactivate fault and recover
curl -X POST http://127.0.0.1:8000/api/v1/faults/scenarios/deactivate
curl -X POST http://127.0.0.1:8000/api/v1/telemetry/generate-step
```

#### Scenario 2: Backhaul Link Failure (`backhaul_failure`)
- **Target**: `LINK-AGG-01-SITE-01`
- **Impact**: Complete transport cut isolating `SITE-01` and sector cells `CELL-01`, `CELL-02`, and `CELL-03`.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/faults/scenarios/backhaul_failure/activate
curl -X POST http://127.0.0.1:8000/api/v1/telemetry/generate-step
```

#### Scenario 3: Radio Interference (`radio_interference`)
- **Target**: `CELL-05`
- **Impact**: Severe SINR degradation (< 5 dB) on `CELL-05`, reducing throughput and elevating packet drop rates while availability remains intact.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/faults/scenarios/radio_interference/activate
curl -X POST http://127.0.0.1:8000/api/v1/telemetry/generate-step
```

#### Scenario 4: Cell Congestion (`cell_congestion`)
- **Target**: `CELL-10`
- **Impact**: PRB utilization saturates ($\ge 90\%$), queue latency spikes (> 80 ms), and user throughput degrades.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/faults/scenarios/cell_congestion/activate
curl -X POST http://127.0.0.1:8000/api/v1/telemetry/generate-step
```

#### Scenario 5: Site Power Failure (`site_power_failure`)
- **Target**: `SITE-04`
- **Impact**: Total blackout taking `SITE-04` and subordinate cells `CELL-10`, `CELL-11`, and `CELL-12` completely offline.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/faults/scenarios/site_power_failure/activate
curl -X POST http://127.0.0.1:8000/api/v1/telemetry/generate-step
```

#### Scenario 6: Core Router Degradation (`core_router_failure`)
- **Target**: `CORE-01`
- **Impact**: System-wide transit degradation elevating core latency and triggering critical availability warnings across the regional gateway.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/faults/scenarios/core_router_failure/activate
curl -X POST http://127.0.0.1:8000/api/v1/telemetry/generate-step
```

---

## 5. Incident Management & Triage Workflow

### 5.1 Creating an Incident

Incidents are created by submitting a diagnosed correlation cluster with genuine alarm records:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "correlation_group_id": "GRP-CELL-01-OUTAGE-001",
    "anchor_node_id": "CELL-01",
    "root_cause_tier": "CELL",
    "time_window_start": "2026-11-23T12:00:00Z",
    "time_window_end": "2026-11-23T12:05:00Z",
    "correlation_reason": "Single cell outage diagnosed on CELL-01",
    "alarms": [
      {
        "alarm_id": "ALARM-CELL-01-AVAIL-001",
        "node_id": "CELL-01",
        "rule_id": "RULE-AVAIL-CRIT",
        "metric_name": "availability_pct",
        "source": "THRESHOLD",
        "severity": "CRITICAL",
        "current_value": 0.0,
        "threshold": 95.0,
        "first_seen": "2026-11-23T12:00:00Z",
        "last_seen": "2026-11-23T12:05:00Z",
        "observation_count": 1,
        "status": "ACTIVE"
      }
    ],
    "suspected_cause_type": "CELL_OUTAGE",
    "suspected_target_id": "CELL-01",
    "suspected_target_type": "NODE",
    "rca_confidence_score": 0.95,
    "created_by": "operator_triage"
  }'
```

The API returns the created incident including the server-assigned `incident_id` (e.g. `INC-3f4a9b1c2d0e`), operational severity, and SLA deadlines.

### 5.2 Acknowledging an Incident

```bash
curl -X POST http://127.0.0.1:8000/api/v1/incidents/INC-3f4a9b1c2d0e/acknowledge \
  -H "Content-Type: application/json" \
  -d '{ "actor": "duty_engineer" }'
```

### 5.3 Resolving an Incident

```bash
curl -X POST http://127.0.0.1:8000/api/v1/incidents/INC-3f4a9b1c2d0e/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "actor": "duty_engineer",
    "notes": "Cell transceiver power-cycled; KPIs returned to nominal baselines."
  }'
```

### 5.4 Inspecting the Audit Timeline

```bash
curl -s http://127.0.0.1:8000/api/v1/incidents/INC-3f4a9b1c2d0e/timeline
```

---

## 6. Observability & Monitoring Verification

### 6.1 Prometheus Metrics

Prometheus scrapes backend metrics at `http://backend:8000/metrics`.
Verify Prometheus targets:
1. Open `http://localhost:9090/targets` in a browser.
2. Confirm the `nexus-backend` target reports state `UP`.

### 6.2 Grafana Dashboards

Grafana is provisioned with dashboards visualizing:
- **System Health & HTTP Performance**: Request rate, latency percentiles, error rates.
- **Network Telemetry Overview**: Real-time throughput, latency, drop rates across the 27-node hierarchy.
- **Incident & SLA Metrics**: Active incidents, MTTA, MTTR, and SLA breach tracking.
- **Fault Simulation Tracking**: Active fault scenarios and affected blast radii.

---

## 7. Troubleshooting & Recovery Procedures

### 7.1 Database Connection Failures
- **Symptom**: Backend readiness probe returns `"database": "down"`.
- **Resolution**:
  1. Check PostgreSQL container status: `docker compose ps nexus-postgres`.
  2. Inspect container logs: `docker compose logs nexus-postgres`.
  3. Verify `POSTGRES_PASSWORD` in `.env` matches backend database connection string.

### 7.2 Database Schema Not Migrated
- **Symptom**: Backend log reports `RuntimeError: Database schema is not up to date`.
- **Resolution**:
  Execute Alembic migrations:
  ```bash
  docker compose exec backend python -m alembic upgrade head
  ```

### 7.3 Port Conflicts
- **Symptom**: Docker fails to bind host ports `3000`, `8000`, or `9090`.
- **Resolution**: Check for conflicting local processes using `netstat` or PowerShell `Get-NetTCPConnection` and terminate conflicting instances.

### 7.4 WebSocket Connection Drops
- **Symptom**: Top navigation bar shows `RECONNECTING` or `DISCONNECTED`.
- **Resolution**: Frontend client automatically initiates exponential backoff reconnects (up to 20 attempts). If backend was restarted, refreshing the page forces complete state rehydration.
