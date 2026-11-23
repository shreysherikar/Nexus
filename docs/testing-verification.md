# NEXUS — Testing & Verification Guide

This guide details the automated test suites, quality gates, and continuous integration workflows for the **NEXUS Network Intelligence & Incident Management Platform**.

---

## Testing Philosophy & Strategy

NEXUS employs multi-layered automated verification across both backend Python engines and the frontend React Single Page Application (SPA):

```
                   ┌─────────────────────────────────────────────────────────┐
                   │                     Continuous Integration              │
                   │                    (GitHub Actions Workflows)           │
                   └────────────────────────────┬────────────────────────────┘
                                                │
                     ┌──────────────────────────┴──────────────────────────┐
                     ▼                                                     ▼
      ┌─────────────────────────────┐                       ┌─────────────────────────────┐
      │     Backend Quality Gate    │                       │    Frontend Quality Gate    │
      │       (Python 3.11+)        │                       │       (Node 20+ / pnpm)     │
      └──────────────┬──────────────┘                       └──────────────┬──────────────┘
                     │                                                     │
       ┌─────────────┼─────────────┐                         ┌─────────────┼─────────────┐
       ▼             ▼             ▼                         ▼             ▼             ▼
  [Unit Tests] [API Tests] [Replay Tests]               [ESLint]      [TypeScript]  [Vitest / RTL]
   557 tests    FastAPI     Scenarios &                 Code quality   Strict types   Components,
   isolated      Mock/DB    Evaluation                                               Client & E2E
```

Key principles:
- **Strict Decoupling**: Anomaly detection, alarm correlation, and RCA engines run tests without importing or referencing fault ground truth.
- **Reproducibility**: Synthetic telemetry and scenario replays use deterministic pseudo-random generators (`Random(seed)`), producing identical time-series curves.
- **Thread Safety**: WebSocket broadcaster, subscriber queues, and concurrent request metrics undergo concurrency stress tests.
- **Async Event Synchronization**: Frontend tests query asynchronous React state updates using async queries (`findAllBy*`, `waitFor`) to avoid microtask race conditions.

---

## Backend Test Suite (Python / Pytest)

### Running the Backend Tests

Execute all tests from the repository root:
```bash
python -m pytest -v
```

Execute a targeted test module:
```bash
python -m pytest tests/test_backend_read_api.py -v
```

Execute with code coverage reporting:
```bash
python -m pytest --cov=nexus --cov-report=term-missing
```

### Authoritative Backend Test Catalog (17 Modules, 557 Tests)

The backend suite comprises **557 tests** across 17 test modules:

| Test File | Test Count | Test Focus & Scope |
| :--- | :---: | :--- |
| `tests/test_backend_read_api.py` | 23 | FastAPI read endpoints (`/topology`, `/telemetry`, `/alarms`, `/detection/rules`), query filters, pagination, and step generation. |
| `tests/test_correlation.py` | 40 | Lowest Common Ancestor (LCA) clustering, distant ancestor protection, maximum time-window span invariants, and correlation reasons. |
| `tests/test_detection.py` | 61 | Configurable threshold detector with hysteresis, MAD rolling median, EWMA baselines, alarm deduplication and clearing. |
| `tests/test_evaluation.py` | 16 | Detection evaluation metrics, Precision, Recall, F1 score, Mean Time to Detect (MTTD), and spatio-temporal matching. |
| `tests/test_fault.py` | 63 | Five fault types, half-open active intervals, downstream blast radius calculation, and target conflict rejection. |
| `tests/test_fault_integration.py` | 5 | Fault scenario activation, telemetry transformation pipeline integration, and scenario deactivation. |
| `tests/test_incidents_api.py` | 37 | Incident REST API (`/api/v1/incidents`), acknowledge/resolve mutations, timeline retrieval, and metrics endpoint. |
| `tests/test_incidents_domain.py` | 40 | Incident entity lifecycle state machine (`OPEN -> ACKNOWLEDGED -> RESOLVED`), SLA deadline tracking, and timeline audit trail. |
| `tests/test_incidents_persistence.py` | 9 | SQLAlchemy relational repository, transactions, index uniqueness, and cascading timeline deletes. |
| `tests/test_main_integration.py` | 15 | Central FastAPI application lifespan, subsystem wiring, CORS middleware, `/ready` and `/health` probes. |
| `tests/test_prometheus_metrics.py` | 10 | Prometheus metrics registry, normalized route templates, low-cardinality labels, domain gauge updates, and `/metrics` exposition. |
| `tests/test_rca.py` | 71 | Explainable rule-based RCA engine, 5 diagnostic pattern evaluators, additive scoring, target attribution (`NODE` vs. `TRANSPORT_LINK`), and hypothesis ranking. |
| `tests/test_rca_evaluation.py` | 16 | RCA benchmark evaluation against ground truth, top-1 cause accuracy, target accuracy, diagnostic coverage, and noise reduction ratio. |
| `tests/test_telemetry.py` | 53 | Typed KPI snapshots, finite bounds validation, tier baseline profiles, and deterministic synthetic time-series continuity. |
| `tests/test_topology.py` | 43 | 27-node topology graph, tier validation (`CORE`, `AGGREGATION`, `SITE`, `CELL`), cycle detection, coordinate validation, and status transitions. |
| `tests/test_transport.py` | 36 | 26 transport links, capacity, latency, and endpoint alignment across the network hierarchy. |
| `tests/test_websocket_events.py` | 19 | WebSocket event broadcaster, cross-thread dispatch, FIFO backpressure queue eviction, outbound write serialization, and PING/PONG heartbeats. |

**Total Backend Tests**: **557 tests**

---

## Frontend Test & Quality Suite (TypeScript / Vitest)

### Running Frontend Checks

All frontend checks run from `frontend/`:

```bash
cd frontend

# 1. Run ESLint code quality checks
npm run lint

# 2. Strict TypeScript compiler verification (no emit)
npm run typecheck

# 3. Run complete Vitest suite with JSDOM
npm test

# 4. Verify optimized production bundle build
npm run build
```

### Authoritative Frontend Test Catalog (6 Modules, 68 Tests)

The frontend suite comprises **68 tests** across 6 test modules:

| Test File | Test Count | Verified Functionality |
| :--- | :---: | :--- |
| `tests/api_client.test.ts` | 16 | REST client query construction, parameter serialization, error extraction, anti-cache header handling, and abort signals. |
| `tests/components.test.tsx` | 10 | Reusable UI components: MetricCard, StatusBadge, SeverityBadge, DataTable, PageHeader, ErrorState, and fault panels. |
| `tests/kpis_accuracy.test.tsx` | 18 | Inactive rule handling (`Rule inactive`), threshold badge colors, empty rule handling, and async DOM update synchronization. |
| `tests/m7_end_to_end.test.tsx` | 7 | Operational workflows: initial startup empty states, telemetry step generation, fault scenario injection, and incident acknowledge/resolve lifecycle. |
| `tests/navigation.test.tsx` | 6 | Application shell, sidebar navigation, top bar layout, root `/` redirect to `/overview`, and 404 fallback routing. |
| `tests/websocket_client.test.ts` | 11 | WebSocket client lifecycle, auto-reconnection, event deserialization, heartbeat dispatch, and subscriber callbacks. |

**Total Frontend Tests**: **68 tests**

---

## Continuous Integration (GitHub Actions)

NEXUS enforces continuous integration on all branches and pull requests via two parallel GitHub Actions workflows:

### 1. `CI / Run Python Test Suite`
- **Environment**: Ubuntu Linux with Python 3.11 and PostgreSQL 15 service container
- **Steps**:
  1. Check out repository code.
  2. Set up Python environment with pip caching.
  3. Install backend package with test dependencies: `pip install -e ".[test]"`.
  4. Run Alembic database migrations: `python -m alembic upgrade head`.
  5. Execute full pytest suite: `python -m pytest`.

### 2. `CI / Frontend Quality & Build`
- **Environment**: Ubuntu Linux with Node.js 20
- **Steps**:
  1. Check out repository code.
  2. Set up Node.js 20 with npm caching.
  3. Install dependencies via frozen package lock: `npm ci`.
  4. Run ESLint: `npm run lint`.
  5. Run TypeScript compiler verification: `npm run typecheck`.
  6. Execute Vitest test suite: `npm test`.
  7. Verify production build: `npm run build`.

Both checks must pass before any code is merged into `main`.
