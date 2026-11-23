# NEXUS — Observability, Monitoring & Deployment Guide

This document details the observability architecture, Prometheus metrics catalog, and container deployment topology for the **NEXUS Network Intelligence & Incident Management Platform**.

---

## Observability Architecture

```
                                  ┌─────────────────────────────────────────┐
                                  │           Prometheus Server             │
                                  │        (Host: 127.0.0.1:9090)           │
                                  └────────────────────┬────────────────────┘
                                                       │
                                   Scrapes /metrics    │ Internal Scrape (5s)
                                   over Docker Network │ (Prometheus format)
                                                       ▼
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│     NOC Dashboard / Client      │       │       NEXUS FastAPI Backend     │
│     (Host: 127.0.0.1:3000)      │       │     (Host: 127.0.0.1:8000)      │
└────────────────┬────────────────┘       └────────────────┬────────────────┘
                 │                                         │
                 │ /health, /ready                         │ Persistent State
                 ▼ (Public Proxy)                          ▼
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│       Nginx Reverse Proxy       │       │           PostgreSQL            │
│   (/metrics returns 404!)       │       │         (Internal Port 5432)    │
└─────────────────────────────────┘       └─────────────────────────────────┘
```

### Observability Design Principles
1. **Low Cardinality**: Metric labels use strict, bounded enumerations (`node_tier`, `severity`, `status`, `method`, `endpoint`). Dynamic identifiers (node IDs, alarm IDs, incident IDs, operator notes) are never placed in Prometheus labels to prevent time-series database (TSDB) memory explosion.
2. **Ground Truth Decoupling**: Ground-truth records and synthetic generation internals are strictly isolated from operational metrics. No synthetic ground truth leaks into runtime monitoring.
3. **Internal Metrics Scraping**: Production deployments restrict `/metrics` to the private Docker bridge network. Public ingress through the frontend reverse proxy returns `404 Not Found`.
4. **Grafana Dashboards**: Five provisioned Grafana dashboards provide pre-configured visualizations for HTTP performance, telemetry trends, alarm counts, fault scenarios, and SLA compliance metrics.

---

## Prometheus Configuration

Prometheus is configured via `deploy/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 10s
  evaluation_interval: 10s
  scrape_timeout: 5s

scrape_configs:
  # Self-monitoring
  - job_name: "prometheus"
    metrics_path: "/metrics"
    static_configs:
      - targets: ["localhost:9090"]

  # Primary scraper job targeting NEXUS FastAPI backend
  - job_name: "nexus-backend"
    metrics_path: "/metrics"
    scrape_interval: 5s
    scrape_timeout: 4s
    static_configs:
      - targets: ["backend:8000"]
```

---

## Prometheus Metrics Catalog

### 1. HTTP Request Metrics

| Metric Name | Type | Labels | Description |
| :--- | :---: | :--- | :--- |
| `nexus_http_requests_total` | Counter | `method`, `endpoint`, `status` | Total HTTP requests processed, partitioned by route template and HTTP status code. |
| `nexus_http_request_duration_seconds` | Histogram | `method`, `endpoint` | Processing latency in seconds across standard buckets (0.005s to 10.0s). |

> [!NOTE]
> `/metrics` is excluded from recursive HTTP tracking to prevent scrape traffic from skewing latency and request metrics.

### 2. Application Readiness & Subsystem Health

| Metric Name | Type | Labels | Description |
| :--- | :---: | :--- | :--- |
| `nexus_app_info` | Gauge | `version`, `platform` | Static metadata indicator gauge (value=1.0). |
| `nexus_ready_status` | Gauge | None | Overall application readiness (1.0 = ready, 0.0 = not ready). |
| `nexus_component_ready` | Gauge | `component` | Subsystem status (1.0 = ready, 0.0 = not ready). Subsystems: `topology`, `broadcaster`, `telemetry_store`, `alarm_service`, `fault_service`, `database`. |

### 3. Telemetry Domain Metrics

| Metric Name | Type | Labels | Description |
| :--- | :---: | :--- | :--- |
| `nexus_telemetry_snapshots_total` | Gauge | None | Count of snapshots currently retained in memory buffer. |
| `nexus_telemetry_last_timestamp_seconds`| Gauge | None | UTC epoch timestamp of most recent snapshot. |
| `nexus_telemetry_throughput_mbps_avg` | Gauge | `node_tier` | Average throughput in Mbps by tier (`CORE`, `AGGREGATION`, `SITE`, `CELL`). |
| `nexus_telemetry_latency_ms_avg` | Gauge | `node_tier` | Average latency in ms by tier. |
| `nexus_telemetry_drop_rate_pct_avg` | Gauge | `node_tier` | Average connection drop rate percentage by tier. |
| `nexus_telemetry_availability_pct_avg` | Gauge | `node_tier` | Average operational availability percentage by tier. |
| `nexus_telemetry_radio_sinr_db_avg` | Gauge | None | Average SINR in dB across active CELL nodes. |
| `nexus_telemetry_radio_prb_utilization_pct_avg` | Gauge | None | Average PRB utilization percentage across active CELL nodes. |

### 4. Alarm Subsystem Metrics

| Metric Name | Type | Labels | Description |
| :--- | :---: | :--- | :--- |
| `nexus_alarms_active` | Gauge | `severity` | Number of currently active alarms (`CRITICAL`, `MAJOR`, `WARNING`). |
| `nexus_alarms_total` | Gauge | `severity`, `status` | Total alarms tracked across states (`ACTIVE`, `CLEARED`). |

### 5. Incident & SLA Performance Metrics

| Metric Name | Type | Labels | Description |
| :--- | :---: | :--- | :--- |
| `nexus_incidents_total` | Gauge | None | Total incidents recorded in database. |
| `nexus_incidents_active` | Gauge | `severity` | Unresolved incidents by severity. |
| `nexus_incidents_by_status` | Gauge | `status` | Incidents categorized by state (`OPEN`, `ACKNOWLEDGED`, `RESOLVED`). |
| `nexus_incidents_by_severity` | Gauge | `severity` | Incidents categorized by severity. |
| `nexus_incidents_sla_breaches_total` | Gauge | `sla_type` | Total SLA breaches (`acknowledgement`, `resolution`). |
| `nexus_incidents_mtta_seconds` | Gauge | None | Mean Time To Acknowledge in seconds. |
| `nexus_incidents_mttr_seconds` | Gauge | None | Mean Time To Resolve in seconds. |
| `nexus_incidents_mttd_seconds` | Gauge | None | Mean Time To Detect in seconds (0.0 if unrecorded). |
| `nexus_incidents_sla_compliance_pct` | Gauge | None | SLA compliance percentage across evaluated incidents. |

### 6. Fault Scenario Metrics

| Metric Name | Type | Labels | Description |
| :--- | :---: | :--- | :--- |
| `nexus_fault_scenario_active` | Gauge | `scenario_key` | Activation state per scenario (1.0 = active, 0.0 = inactive). Keys: `cell_outage`, `backhaul_failure`, `radio_interference`, `cell_congestion`, `site_power_failure`, `core_router_failure`. |
| `nexus_fault_affected_nodes_count` | Gauge | None | Number of topology nodes impacted by active faults. |

---

## Essential PromQL Queries

### API Health & Latency
- **Request rate across endpoints (requests/sec)**:
  ```promql
  sum(rate(nexus_http_requests_total[1m])) by (endpoint, status)
  ```
- **95th percentile request latency**:
  ```promql
  histogram_quantile(0.95, sum(rate(nexus_http_request_duration_seconds_bucket[5m])) by (le, endpoint))
  ```
- **Error rate percentage**:
  ```promql
  sum(rate(nexus_http_requests_total{status=~"5.."}[5m])) / sum(rate(nexus_http_requests_total[5m])) * 100
  ```

### Telecom Operations & SLAs
- **Active critical & major alarms**:
  ```promql
  sum(nexus_alarms_active{severity=~"CRITICAL|MAJOR"})
  ```
- **SLA compliance rate**:
  ```promql
  nexus_incidents_sla_compliance_pct
  ```
- **Mean time to resolve (minutes)**:
  ```promql
  nexus_incidents_mttr_seconds / 60
  ```
- **Cell-tier average PRB utilization**:
  ```promql
  nexus_telemetry_radio_prb_utilization_pct_avg
  ```

---

## Container Deployment Architecture

NEXUS uses Docker Compose to deploy five coordinated containers connected via an isolated bridge network (`nexus-network`):

| Container | Image / Dockerfile | Host Port | Internal Port | Security Profile | Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `nexus-postgres` | `postgres:15-alpine` | None (internal) | `5432` | `no-new-privileges:true` | Relational incident & audit persistence |
| `nexus-backend` | `./Dockerfile` | `127.0.0.1:8000` | `8000` | Non-root `nexus` (UID 1000), `no-new-privileges:true` | FastAPI ASGI REST & WebSocket engine |
| `nexus-frontend` | `./frontend/Dockerfile` | `127.0.0.1:3000` | `80` | `no-new-privileges:true` | React SPA static delivery & Nginx proxy |
| `nexus-prometheus` | `prom/prometheus:v2.51.0` | `127.0.0.1:9090` | `9090` | `no-new-privileges:true` | Time-series scraper and monitoring UI |
| `nexus-grafana` | `grafana/grafana:10.4.0` | `127.0.0.1:3001` | `3000` | `no-new-privileges:true` | Grafana visual analytics and operational dashboards |

### Hardening Safeguards
1. **Loopback Interface Binding**:
   - Host ports bind strictly to `127.0.0.1` by default (`${BACKEND_BIND_IP:-127.0.0.1}:${BACKEND_PORT:-8000}:8000`), protecting against unintentional exposure on public or LAN network interfaces.
2. **Mandatory Secret Validation**:
   - Docker Compose enforces `${POSTGRES_PASSWORD:?...}`. Attempting to start the stack with an empty or missing database password halts execution immediately.
3. **Non-Root Execution**:
   - Backend runs under an unprivileged user (`nexus`, UID 1000, GID 1000).
   - Privilege escalation flags are blocked via `security_opt: [no-new-privileges:true]`.
4. **Proxy Route Filtering**:
   - Public frontend proxy blocks `/metrics` with HTTP 404, keeping raw operational counters internal to the cluster.
5. **Sanitized Probes**:
   - `/ready` and `/health` report structured status without exposing raw exception messages, connection URLs, or database credentials.

---

## Lifecycle Commands

### Start Deployment
```bash
cp .env.example .env
# Set strong POSTGRES_PASSWORD in .env
docker compose up --build -d
```

### Inspect Container Health
```bash
docker compose ps
```

### Stream Logs
```bash
docker compose logs -f backend
```

### Clean Teardown
```bash
# Stop containers, preserve data volumes
docker compose down

# Stop containers and purge all database & metric volumes
docker compose down -v
```
