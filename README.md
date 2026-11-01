# NEXUS — Network Intelligence & Incident Management Platform

NEXUS is an independent Python platform providing hierarchical network modeling, synthetic telemetry generation, and controlled fault injection for telecommunications infrastructure engineering and testing.

---

## Current Capabilities

The repository currently implements the following modules:

- **Network Topology Domain (`nexus.topology`)**:
  - Validated hierarchical graph modeling Core, Aggregation, Site, and Cell tiers.
  - Immutable node entities (`Node`) with operational statuses (`ONLINE`, `OFFLINE`, `DEGRADED`, `MAINTENANCE`).
  - Tier hierarchy rules, cycle detection, and atomic reparenting safeguards.
  - Reference 27-node simulated network builder (`CORE-01`, 2 Aggregation nodes, 6 Sites, 18 Cells).
- **Transport Network Domain (`nexus.transport`)**:
  - Bidirectional transport links (`TransportLink`) with capacity and latency attributes.
  - Endpoint validation and strict parent-child link alignment over the network topology.
  - Reference 26-link transport network builder connecting all non-root hierarchy edges.
- **Telemetry & KPI Domain (`nexus.telemetry`)**:
  - Typed, validated KPI snapshots covering radio parameters (RSRP, SINR, PRB utilization), performance metrics (throughput, latency), and reliability metrics (drop rate, availability, handover success rate).
  - Construction-time validation enforcing finite bounds, non-negative rates, and percentage limits.
  - Tier baseline operating profiles (`DEFAULT_PROFILES`) with custom profile mapping support.
  - Deterministic synthetic generator (`SyntheticTelemetryGenerator`) providing reproducible time-series steps and temporal continuity.
- **Fault Injection & Scenario Engine (`nexus.fault`)**:
  - Validated immutable fault models (`CELL_OUTAGE`, `BACKHAUL_FAILURE`, `RADIO_INTERFERENCE`, `CELL_CONGESTION`, `SITE_POWER_FAILURE`).
  - Half-open active interval evaluation (`start_time <= timestamp < end_time`).
  - Downstream blast-radius propagation over topology and transport networks.
  - Conflict detection rejecting ambiguous overlapping faults on the same target.
  - Deterministic ground-truth recording (`GroundTruthRecord`) for benchmark evaluation.
  - Reference suite of 5 standard fault scenarios (`build_reference_scenarios`).
- **Anomaly Detection & Alarm Generation (`nexus.detection`)**:
  - Configurable threshold-based detection with comparison operators and hysteresis recovery.
  - Statistical anomaly detection using Rolling Median (MAD-based) and EWMA baselines with contamination prevention.
  - Alarm lifecycle management (`ACTIVE`, `CLEARED`), stable deduplication identity, and diagnostic evidence preservation.
  - Sequential, deterministic batch processing with strict chronological monotonicity and duplicate observation guards.
  - Strict decoupling: zero import dependency or runtime reliance on fault ground truth.
- **Alarm Correlation Subsystem (`nexus.correlation`)**:
  - Deterministic clustering of point-in-time alarms into immutable correlation groups (`AlarmCorrelationEngine`).
  - Strict maximum onset-time span invariant enforcing time windows and preventing transitive time-window chaining.
  - Lowest Common Ancestor (LCA) resolution preferring nearest meaningful dependencies (Site, Aggregation) based on topology hierarchy.
  - Distant ancestor protection preventing spurious correlation of independent branches at the Core level.
  - Symptom compatibility isolation ensuring localized RF and resource spikes do not cross node boundaries.
  - Immutable correlation groups (`CorrelationGroup`) and noise reduction ratio metrics.
- **Root Cause Analysis Subsystem (`nexus.rca`)**:
  - Explainable, deterministic rule-based diagnostic engine (`RootCauseAnalysisEngine`).
  - Active telemetry participation using fresh `KPISnapshot` observations with deterministic freshness windows and explicit source attribution (`evidence_source: ALARM, SNAPSHOT, TOPOLOGY`).
  - Five core diagnostic pattern evaluators with strict diagnostic thresholds: Backhaul link cut, Site power failure, Radio interference, Cell congestion, and Cell outage.
  - Multi-tier target identification (distinguishing `NODE` and `TRANSPORT_LINK` root causes).
  - Additive evidence scoring, strict tie-breaking ranking, and explicit `UNKNOWN` fallback policy.
  - Actionable operational remediation guidance for incident response.
- **Evaluation Subsystem (`nexus.evaluation`)**:
  - Post-detection and post-RCA benchmark evaluation against fault ground-truth records.
  - Pure spatio-temporal ground-truth-independent candidate selection matching without diagnostic confirmation bias.
  - Detection metric calculations: Precision, Recall, F1 score, and Mean Time to Detect (MTTD).
  - RCA accuracy metrics (`evaluate_rca`): Top-1 cause accuracy, target accuracy, diagnosis coverage, and alarm noise reduction ratio.
  - Configurable evaluation grace periods and full scenario replay harness (`ScenarioReplayEvaluator`).

- **Incident Management & SLA Tracking Subsystem (`nexus.incidents`)**:
  - Persistent operational incident entity with strict lifecycle state machine (`OPEN -> ACKNOWLEDGED -> RESOLVED`).
  - Validated alarm ingestion (`CorrelatedAlarmDTO`) preserving actual alarm metrics, severities, and timestamps without fabrication.
  - Operational-impact severity policy (`CRITICAL`, `MAJOR`, `WARNING`, `MINOR`) decoupled from diagnostic confidence.
  - Strict confidence validation (finite floats in $[0.0, 1.0]$, preserving `None` when unavailable, no invented defaults).
  - Timezone-aware UTC SLA deadline management with configurable targets per severity.
  - Append-only chronological audit timeline capturing state transitions and actor details.
  - Operational metrics tracking: Mean Time to Acknowledge (MTTA), Mean Time to Resolve (MTTR), Mean Time to Detect (MTTD; returned as `None` when evaluation data is absent), and SLA breach accounting computed via $O(1)$ memory streaming iteration.
  - PostgreSQL persistence with SQLAlchemy 2.x and mandatory Alembic schema migrations (`alembic upgrade head`), with SQLite automatic table creation supported for lightweight local development.
  - REST API powered by FastAPI with OpenAPI interactive documentation (`/api/v1/incidents`).
- **Backend Read APIs & Real-Time Event Infrastructure (M7.2)**:
  - `GET /api/v1/topology`: Exposes the authoritative 27-node network inventory (Core, Aggregation, Site, Cell) with optional, strictly validated geographic coordinates (`latitude` $[-90, 90]$, `longitude` $[-180, 180]$) and parent/child relationships.
  - `GET /api/v1/telemetry`: Ephemeral, bounded in-memory telemetry store (`TelemetryStore`, capacity 10,000 snapshots with FIFO eviction, unpersisted with restart data loss) populated on-demand via `TelemetryPipeline` (`generate_step`) or scenario replay without uncontrolled background loops. Queryable by `node_id`, `node_type`, and ISO 8601 time windows with deterministic ordering and duplicate rejection.
  - `GET /api/v1/alarms`: Standalone alarm query API wrapping `AlarmService` with status, severity, pagination, and deterministic sorting.
  - `GET /api/v1/detection/rules`: Authoritative threshold rule registry exposing the 8 default telecom detection rules with operators, thresholds, clear thresholds, severities, and applicable node types.
  - WebSocket `/ws/live`: Live event transport publishing authentic system state changes (`TELEMETRY_SNAPSHOT`, `ALARM_CREATED`, `ALARM_UPDATED`, `ALARM_CLEARED`, `INCIDENT_CREATED`, `INCIDENT_ACKNOWLEDGED`, `INCIDENT_RESOLVED`, `TOPOLOGY_STATUS_CHANGED`). Features thread-safe cross-thread dispatch via `call_soon_threadsafe`, serialized outbound writes for event and heartbeat PONG frames, and bounded per-subscriber queues (maxsize 100) with FIFO backpressure eviction. Ephemeral transport without durable replay (authoritative snapshot + delta streams).
- **Network Operations Center (NOC) Dashboard (M7)**:
  - **Overview Dashboard (`/overview`)**: Real-time operational summary with KPI cards, incident and alarm queues, severity and lifecycle distributions, and health classification (Healthy, Degraded, Offline, Insufficient Telemetry) evaluated directly against actual topology and telemetry.
  - **Network Topology & Hierarchy (`/network-map`)**: Complete logical hierarchy tree (Core -> Aggregation -> Sites -> Cells) with search, node tier filters, status filters, node detail drawer, and honest coordinate visualization (empty state when physical GPS is not configured).
  - **KPI Monitoring & Telemetry (`/kpis`)**: Synthetic telemetry monitoring with deliberate operator step generation (`POST /api/v1/telemetry/generate-step`), node selection, live trend charts with backend detection thresholds, and honest single-observation rendering.
  - **Alarms Inventory (`/alarms`)**: Paginated alarm management with severity and status filters, rule search, node search, and detailed alarm drawer with diagnostic evidence.
  - **Incident Workspace (`/incidents`)**: Complete incident operations with automated RCA hypothesis inspection, audit timeline, and operational lifecycle actions (Acknowledge with operator identity, Resolve with mandatory operator findings and confirmation dialog).
  - **SLA & Operational Analytics (`/analytics`)**: Compliance rate breakdown, MTTA, MTTR, MTTD reporting, and severity/status distribution charts computed live from persistent PostgreSQL storage.
  - **Real-Time Live Transport (`/ws/live`)**: WebSocket synchronization with automatic reconnection, deduplication, backpressure handling, and REST state reconciliation.
  - **Frontend Quality Assurance**: Full Vitest and React Testing Library suite covering components, client API, navigation routing, and end-to-end operational scenarios.

*Notice: Network telemetry and fault scenarios are generated by an internal synthetic simulation engine. NEXUS operates independently without requiring live carrier feeds or physical hardware.*

---

## Planned Capabilities

The following capabilities are planned for upcoming milestones and are not yet implemented:
- Automated closed-loop remediation workflows and incident ticket management.
- Real-time telemetry ingestion pipeline and Prometheus metric export.

---

## Technology Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL (`psycopg[binary]`), Pydantic v2
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, React Router v6, Lucide React
- **Architecture**: Modular monolith with decoupled domain boundaries and independent SPA frontend
- **Testing & Quality**: `pytest` (backend), `vitest`, `@testing-library/react`, `eslint` (frontend)

---

## Local Setup & Quickstart

### 1. Install Dependencies
Clone the repository and install the project in editable mode with all dependencies:

```bash
git clone https://github.com/shreysherikar/Nexus.git
cd Nexus/nexus-network-intelligence
python -m pip install --upgrade pip
pip install -e ".[test]"
```

### 2. Configure Environment & Start Database
Copy the example environment configuration:

```bash
cp .env.example .env
```

Start the local PostgreSQL instance via Docker Compose (optional; SQLite fallback is available for offline testing):

```bash
docker compose up -d
```

### 3. Apply Database Migrations
Apply Alembic migrations to set up the incident management and timeline schema:

```bash
python -m alembic upgrade head
```

### 4. Start the REST API
Launch the FastAPI development server:

```bash
uvicorn nexus.incidents.api:app --host 0.0.0.0 --port 8000 --reload
```

The interactive OpenAPI documentation will be accessible at `http://localhost:8000/docs`.

### 5. Launch the Frontend NOC Dashboard
Install frontend dependencies and start the Vite development server:

```bash
cd frontend
npm install
npm run dev
```

The dashboard will be accessible at `http://localhost:3000`.

---

## Running Tests

### Backend Test Suite
Execute the complete Python automated test suite from the repository root:

```bash
python -m pytest -v
```

### Frontend Test & Quality Suite
Execute the frontend tests, linting, and typechecks from `frontend/`:

```bash
cd frontend
npm test            # Run Vitest component and client tests
npm run lint        # Run ESLint quality checks
npm run typecheck   # Run strict TypeScript compiler verification
npm run build       # Build optimized production bundle
```

---

## Project Documentation

Detailed architectural decisions and design specifications are documented in `docs/`:

- [System Architecture & Initial Design](docs/architecture/initial-design.md)
- [Telemetry & KPI Domain Design](docs/architecture/telemetry-kpi-design.md)
- [Fault Injection & Scenario Engine Design](docs/architecture/fault-injection-design.md)
- [Anomaly Detection & Alarm Generation Design](docs/architecture/anomaly-detection-design.md)
- [Alarm Correlation & RCA Design](docs/architecture/alarm-correlation-rca-design.md)
- [Incident Management & SLA Tracking Design](docs/architecture/incident-management-design.md)
- [Frontend NOC Dashboard Architecture (M7.1)](docs/architecture/frontend-noc-architecture.md)
- [ADR-001: Modular Project Architecture](docs/decisions/ADR-001-project-architecture.md)
