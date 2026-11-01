# NEXUS Frontend Architecture — M7.1 NOC Dashboard Foundation

## 1. Overview & Purpose

Milestone 7.1 introduces the operator-facing Network Operations Center (NOC) dashboard for the NEXUS platform. Built to serve network operations engineers and incident commanders, the interface prioritizes clear operational visibility, actionable diagnostic hierarchy, dark-mode ergonomics for 24/7 monitoring environments, and strict fidelity to real backend data contracts without mock fabrication.

## 2. Technology Stack & Directory Structure

The frontend is housed in `frontend/` as an independent, reproducible Single Page Application (SPA):

- **Core Framework**: React 18 with Strict TypeScript (`tsconfig.json`)
- **Build Tool**: Vite 5.4.x
- **Routing**: React Router v6
- **Styling**: Tailwind CSS with custom Dark NOC Design tokens
- **Icons**: Lucide React
- **Testing**: Vitest, React Testing Library, jsdom
- **Linting**: ESLint 9 (flat config) + typescript-eslint

```text
frontend/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
├── eslint.config.js
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── vite-env.d.ts
│   ├── styles/
│   │   └── index.css
│   ├── types/
│   │   ├── api.ts              # Backend API contract interfaces
│   │   ├── websocket.ts        # WebSocket event and status definitions
│   │   └── navigation.ts       # Navigation routes & metadata
│   ├── api/
│   │   └── client.ts           # Configurable REST API client with timeout & abort
│   ├── websocket/
│   │   ├── client.ts           # Native WebSocket abstraction with exponential backoff
│   │   └── useWebSocket.ts     # React hooks for connection & subscriptions
│   ├── components/
│   │   ├── common/
│   │   │   ├── StatusBadge.tsx
│   │   │   ├── SeverityBadge.tsx
│   │   │   ├── MetricCard.tsx
│   │   │   ├── DataTable.tsx
│   │   │   ├── LoadingState.tsx
│   │   │   ├── ErrorState.tsx
│   │   │   ├── EmptyState.tsx
│   │   │   └── ConnectionIndicator.tsx
│   │   └── layout/
│   │       ├── AppShell.tsx
│   │       ├── Sidebar.tsx
│   │       ├── TopBar.tsx
│   │       └── PageHeader.tsx
│   └── pages/
│       ├── OverviewPage.tsx
│       ├── NetworkMapPage.tsx
│       ├── KpisPage.tsx
│       ├── AlarmsPage.tsx
│       ├── IncidentsPage.tsx
│       └── AnalyticsPage.tsx
└── tests/
    ├── setup.ts
    ├── components.test.tsx
    ├── navigation.test.tsx
    ├── api_client.test.ts
    └── websocket_client.test.ts
```

## 3. Dark NOC Design System

The visual design system implements high-contrast, low-eyestrain operational surfaces:

- **Canvas Background**: Deep charcoal `#070a10`
- **Sidebar & TopBar Surface**: `#0c121e`
- **Panel & Card Surface**: `#111927` with `#1e293b` borders
- **Operational Status Palette** (always paired with explicit text labels):
  - **Healthy**: Emerald (`#22c55e` / `#052e16`)
  - **Warning / Degraded**: Amber (`#f59e0b` / `#451a03`)
  - **Critical**: Rose/Red (`#ef4444` / `#450a0a`)
  - **Offline / Unknown**: Slate (`#94a3b8` / `#1e293b`)
- **Typography**: Dual font hierarchy utilizing clean sans (`Inter`) for interface navigation and monospace (`JetBrains Mono`, `ui-monospace`) for timestamps, identifiers, and telemetry values.

## 4. REST API Client Architecture

The `NexusApiClient` (`src/api/client.ts`) provides typed access to backend FastAPI endpoints, matching `src/nexus/incidents/schemas.py` and `api.py` exactly:

- **Environment Configurable**: Reads `VITE_API_BASE_URL` with fallback to relative origin. Operator role and environment banner are dynamically configurable via `VITE_OPERATOR_ROLE` (default: `OPERATOR (DUTY)`) and `VITE_NOC_ENV` (default: `PRIMARY NOC`).
- **Request Cancellation & Timeout**: Integrated `AbortController` distinguishing internal timeouts (`408 REQUEST_TIMEOUT`) from caller cancellations (`499 CLIENT_CANCELLED`).
- **Error Handling**: Throws typed `ApiError` preserving HTTP status codes, validation details, and backend error codes (`INCIDENT_NOT_FOUND`, `DUPLICATE_INCIDENT`, etc.).
- **Live Endpoint Integration**:
  - `GET /health`: Health probe returning `{ status }`.
  - `GET /api/v1/incidents`: Query filtered incident lists using pagination query parameters `limit` (default 50) and `offset` (default 0), returning `{ items, total, limit, offset }`.
  - `GET /api/v1/incidents/{id}`: Single incident retrieval returning full `IncidentResponse` with typed `HypothesisDTO` and `EvidenceItemDTO` items.
  - `GET /api/v1/incidents/metrics`: Incident workload metrics returning `IncidentMetricsResponse` with `total_incidents`, `open_incident_count`, `incidents_by_status`, `incidents_by_severity`, `mtta_seconds`, `mttr_seconds`, `mttd_seconds`, `ack_sla_breached_count`, `resolve_sla_breached_count`, and `as_of`.
  - `GET /api/v1/incidents/{id}/timeline`: Append-only audit events (`IncidentTimelineResponse[]`).
  - `POST /api/v1/incidents/{id}/acknowledge`: Operator acknowledgment with `{ actor: string }`.
  - `POST /api/v1/incidents/{id}/resolve`: Operator resolution with `{ actor: string, notes?: string | null }`.

## 5. WebSocket Client Architecture

The `NexusWebSocketClient` (`src/websocket/client.ts`) provides native WebSocket connectivity:

- **Configurable**: Configured via `VITE_WS_URL`.
- **Connection States**: Explicit state transitions across `CONNECTING`, `CONNECTED`, `DISCONNECTED`, and `RECONNECTING`.
- **Automatic Exponential Backoff**: Bounded retry delay (`initial 1000ms`, `decay 1.5x`, `ceiling 30000ms`, `max attempts 20`).
- **Resilience**: Safe JSON envelope parsing and discarding of malformed payloads without crashing the event loop.
- **Duplicate Connection Guard**: Prevents redundant socket instantiation when already connected or negotiating handshake.
- **Reconnection Snapshot Sync**: Exposes `onReconnectSnapshot` callback allowing components to fetch fresh REST data after reconnecting.
- **Live Endpoint Integration**: Connects to the FastAPI backend WebSocket endpoint at `/ws/live`.

## 6. M7.2 Backend Read APIs & Live Event Infrastructure

Milestone 7.2 bridges the backend domain models and real-time state with the frontend NOC dashboard:

### 6.1 Topology Read Endpoint (`GET /api/v1/topology`)
- **Source of Truth**: Reads directly from the in-memory `Topology` registry (reference 27-node simulated network: 1 Core, 2 Aggregation, 6 Sites, 18 Cells).
- **Coordinate Schema**: Strict geographic coordinates with optional `latitude` ($[-90.0, 90.0]$) and `longitude` ($[-180.0, 180.0]$).
  - Validation requires both latitude and longitude to be present or both `null`. Incomplete pairs, non-finite floats (`NaN`, `inf`), and out-of-range values are strictly rejected.
  - Returns `null` when coordinates have not been explicitly configured; no synthetic coordinates are fabricated.
- **Hierarchy & Relationships**: Each node includes `parent_id` and list of `children` node IDs, enabling recursive tree and graph rendering without secondary lookups.

### 6.2 Telemetry Ingestion & Read Endpoint (`GET /api/v1/telemetry`)
- **Generation & Store Population**: Powered by `TelemetryPipeline` (`src/nexus/telemetry/orchestrator.py`), which orchestrates `SyntheticTelemetryGenerator` and ingests genuine `KPISnapshot` instances into `TelemetryStore`.
  - There are NO uncontrolled background loops or infinite telemetry threads spawned at import time.
  - Snapshots are recorded when explicitly requested (e.g., via `pipeline.generate_step()`, scenario replay, or fault simulation).
  - Deduplication: Ingesting the same timestamp and node ID more than once is an idempotent no-op; duplicate snapshots are ignored and do not emit duplicate events.
- **In-Memory Retention & Restart Data Loss**: `TelemetryStore` maintains a thread-safe, bounded in-memory ring buffer storing up to 10,000 snapshots with FIFO eviction upon saturation.
  - Telemetry snapshots are strictly ephemeral and are NOT persisted to SQL database storage.
  - All retained snapshots are lost upon backend process restart.
- **Query Filtering**:
  - `node_id`: Exact match for target network entity.
  - `node_type`: Tier-based filtering (`CORE`, `AGGREGATION`, `SITE`, `CELL`).
  - `start_time` / `end_time`: ISO 8601 UTC time windows (validates `start_time <= end_time`).
  - `limit` (1–1,000, default 100) and `offset` (>= 0, default 0).
- **Deterministic Ordering**: Ordered deterministically by timestamp descending, with tie-breaking on `node_id` ascending.
- **Metric Integrity**: Non-radio nodes (Core, Aggregation, Site) preserve `radio=null` without fabricating fictitious radio parameters.

### 6.3 Standalone Alarms Inventory (`GET /api/v1/alarms`)
- **Query Filtering**:
  - `node_id`: Exact match for affected node.
  - `severity`: Filter by `CRITICAL`, `MAJOR`, `WARNING`, `MINOR`.
  - `status`: Filter by `ACTIVE` or `CLEARED`.
  - `limit` (1–500, default 50) and `offset` (>= 0, default 0).
- **Deterministic Ordering**: Ordered by `last_seen` descending, then `alarm_id` ascending.
- **State Fidelity**: Wraps `AlarmService` and `AlarmManager`, capturing authentic threshold breaches and statistical anomalies.

### 6.4 Real-Time WebSocket Infrastructure (`WS /ws/live`)
- **Event Envelope Contract**:
  Every live event conforms strictly to the canonical envelope:
  ```json
  {
    "type": "<EVENT_TYPE>",
    "timestamp": "<ISO_8601_UTC_STRING>",
    "payload": { ... }
  }
  ```
- **Supported Event Types and Real Producers**:
  1. `TELEMETRY_SNAPSHOT`: Published by `TelemetryStore` when genuine KPI snapshots are recorded.
  2. `ALARM_CREATED`: Published by `AlarmService` when an anomaly generates a new active alarm.
  3. `ALARM_UPDATED`: Published by `AlarmService` when an existing alarm observation count or severity updates.
  4. `ALARM_CLEARED`: Published by `AlarmService` when an alarm condition normalizes.
  5. `INCIDENT_CREATED`: Published by `IncidentService` upon creating an operational incident from correlation and RCA.
  6. `INCIDENT_ACKNOWLEDGED`: Published by `IncidentService` upon operator acknowledgment.
  7. `INCIDENT_RESOLVED`: Published by `IncidentService` upon incident resolution with audit notes.
  8. `TOPOLOGY_STATUS_CHANGED`: Published by `Topology.update_node_status()` when a node's operational status actually transitions. No event is emitted if the status has not changed.

- **Cross-Thread Event Dispatch Design**:
  - Domain services (such as `IncidentService` or background pipelines) can run in synchronous worker threads.
  - `EventBroadcaster` captures the active `asyncio` event loop for each WebSocket subscriber at registration time.
  - Cross-thread broadcasts invoke `loop.call_soon_threadsafe()` to schedule queue insertions on the subscriber's loop.
  - All `asyncio.Queue` mutations (`get_nowait`, `put_nowait`) execute strictly on the event loop that owns the queue.
  - Subscriber state is protected by thread locks, ensuring full isolation between clients.

- **Serialized Outbound Writes**:
  - In `src/nexus/events/api.py`, a dedicated `sender_task` is the single writer to `websocket.send_text()`.
  - The `receiver_task` reads from the client and routes heartbeat `PONG` frames into an internal queue consumed by the sender task.
  - Event broadcasts and heartbeat responses cannot concurrently write to the underlying WebSocket connection.

- **Queue Management & Backpressure**:
  - Each connected client is allocated a bounded queue (`maxsize=100`).
  - When a slow client's queue reaches capacity, the broadcaster applies FIFO drop policy (discarding the oldest unconsumed event) to safeguard server memory without dropping connections or blocking the event loop.

### 6.5 Authoritative Snapshot & Reconnection Recovery Pattern
- **No Durable Event Replay**: The WebSocket transport is strictly ephemeral and does not retain historical event logs for replay.
- **Synchronization Sequence**:
  1. **Initial Hydration**: Client issues parallel REST calls (`GET /api/v1/topology`, `GET /api/v1/incidents`, `GET /api/v1/alarms`, `GET /api/v1/telemetry`, `GET /api/v1/detection/rules`) to obtain the authoritative baseline snapshot.
  2. **Streaming Handshake**: Client establishes the WebSocket connection to `/ws/live` and applies live incremental delta events to local state.
  3. **Reconnection Recovery**: Upon socket disconnection and subsequent reconnection, the client automatically invokes `onReconnectSnapshot()` to re-fetch authoritative REST snapshots, reconciling any state changes that occurred during the outage.

### 6.6 Authoritative Threshold Detection Rules (`GET /api/v1/detection/rules`)
- **Single Source of Truth**: Exposes the 8 configured baseline threshold rules from `src/nexus/detection/rules.py` through `AlarmService.get_rules()`.
- **Response Schema**: Returns `rule_id`, `metric_name`, `operator`, `threshold`, `clear_threshold`, `severity`, `node_types`, `description`, `enabled`.
- **Frontend Consumption**: KPI monitoring and trend charts query this endpoint directly rather than maintaining duplicated threshold constants. Metrics evaluate dynamically against matching rules and node tiers. Non-radio nodes and missing telemetry are presented honestly with explicit unknown states.
