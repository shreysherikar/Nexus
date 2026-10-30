# NEXUS System Architecture — Initial Design

## 1. Problem Definition

Telecommunications networks and distributed service provider backbones are hierarchical, highly interdependent environments. Network Operations Centers (NOCs) struggle with:
- **Cascading Alarms**: A failure in an upstream transport or core device triggers dozens or hundreds of symptomatic downstream alarms from subordinate nodes (e.g., a severed backhaul link to a site causes every sector cell at that site to trigger link-loss and unreachable alarms).
- **Heterogeneous Telemetry**: Operational metrics (throughput, latency, packet drop rates), discrete events (syslog strings), and threshold alarms arrive asynchronously with varying formats and timestamps.
- **Context-Free Incident Handling**: Traditional ticketing tools capture raw alert streams without topological awareness, leaving operators to manually infer the failure locus and determine the customer or service blast radius.

NEXUS addresses these operational bottlenecks by integrating hierarchical topology modeling directly into the telemetry ingestion and incident triage lifecycle.

---

## 2. Initial Simulated Network Topology

To maintain total reproducibility and eliminate reliance on live telecommunications carrier connections or physical lab infrastructure, NEXUS models a deterministic synthetic topology comprising **27 total nodes** arranged across 4 hierarchical tiers:

```
+-------------------------------------------------------------+
|                     CORE TIER (1 Node)                      |
|                         [CORE-01]                           |
+------------------------------+------------------------------+
                               |
               +---------------+---------------+
               |                               |
+--------------v--------------+ +--------------v--------------+
|   AGGREGATION TIER (West)   | |   AGGREGATION TIER (East)   |
|         [AGG-01]            | |         [AGG-02]            |
+--------------+--------------+ +--------------+--------------+
               |                               |
       +-------+-------+               +-------+-------+
       |       |       |               |       |       |
+------v-+ +---v----+ +-v------+ +-----v--+ +---v----+ +-v------+
| SITE-01| | SITE-02| | SITE-03| | SITE-04| | SITE-05| | SITE-06|
+---+----+ +---+----+ +---+----+ +----+---+ +---+----+ +---+----+
    |          |          |           |         |          |
 (3 Cells)  (3 Cells)  (3 Cells)   (3 Cells) (3 Cells)  (3 Cells)
 CELL-01..3 CELL-04..6 CELL-07..9  CELL-10..12 CELL-13..15 CELL-16..18
```

### Hierarchy Breakdown

| Tier | Node Count | Identifiers | Description |
| :--- | :--- | :--- | :--- |
| **Core** | 1 | `CORE-01` | Centralized regional routing hub; primary simulated IP transit gateway. |
| **Aggregation** | 2 | `AGG-01`, `AGG-02` | Redundant regional distribution routers managing backhaul links for assigned sites. |
| **Site** | 6 | `SITE-01` to `SITE-06` | Physical base station facilities / tower locations (3 assigned to `AGG-01`, 3 assigned to `AGG-02`). |
| **Cell** | 18 | `CELL-01` to `CELL-18` | Simulated radio sector units (3 cells per site: Alpha, Beta, Gamma sectors handling radio carrier traffic). |

### Structural Mapping

- **Core Tier**: `CORE-01`
  - Downlink -> `AGG-01`
  - Downlink -> `AGG-02`
- **Aggregation Tier**:
  - `AGG-01` -> Manages `SITE-01`, `SITE-02`, `SITE-03`
  - `AGG-02` -> Manages `SITE-04`, `SITE-05`, `SITE-06`
- **Site & Cell Tier**:
  - `SITE-01` -> Hosts `CELL-01`, `CELL-02`, `CELL-03`
  - `SITE-02` -> Hosts `CELL-04`, `CELL-05`, `CELL-06`
  - `SITE-03` -> Hosts `CELL-07`, `CELL-08`, `CELL-09`
  - `SITE-04` -> Hosts `CELL-10`, `CELL-11`, `CELL-12`
  - `SITE-05` -> Hosts `CELL-13`, `CELL-14`, `CELL-15`
  - `SITE-06` -> Hosts `CELL-16`, `CELL-17`, `CELL-18`

---

## 3. Proposed Data Flow

```
+-------------------------------------------------------------------------+
| 1. Synthetic Generator & Ingestion Layer                                |
|    - Deterministic time-series metrics (latency, packet loss, traffic)  |
|    - Synthetic fault injection (link flaps, node degradation, outages)  |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| 2. Normalization & Validation                                           |
|    - Schema validation, timestamp alignment, standard metric units      |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| 3. Topology-Aware Correlation & RCA Engine                              |
|    - Threshold breach detection                                         |
|    - Topological tree traversal (Core -> Aggregation -> Site -> Cell)   |
|    - Symptom suppression (masking downstream alarms when root is identified)
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| 4. Incident Synthesis & State Tracking                                  |
|    - Group related alarms into single actionable Incident ticket        |
|    - Calculate blast radius (impacted cell/site count & traffic loss)   |
|    - Maintain lifecycle: Open -> Investigating -> Mitigated -> Resolved |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| 5. Operational Presentation & API Layer                                 |
|    - REST API & WebSocket event delivery                                |
|    - Interactive Topology Map, Incident Workbench, Real-Time KPI graphs |
+-------------------------------------------------------------------------+
```

---

## 4. Planned System Components

1. **Topology Service**:
   - In-memory/relational graph store maintaining node definitions, attributes, parent-child links, and geographic/logical coordinates.
   - Provides path resolution and upstream/downstream neighbor discovery.

2. **Simulation & Ingestion Engine**:
   - Configurable generator that emits periodic metric samples and discrete status events for all 27 topology nodes.
   - Controllable fault-injection scenarios to simulate realistic incidents (e.g., `AGG-01` fiber break affecting 3 sites and 9 cells).

3. **Metrics & KPI Pipeline**:
   - Computes rolling aggregations (p95 latency, average packet loss, traffic bandwidth utilization).
   - Evaluates baseline breaches against dynamic or static operational thresholds.

4. **Correlation & Root-Cause Analysis (RCA) Engine**:
   - Intersects incoming threshold alarms with the topology graph.
   - Applies deterministic correlation rules (e.g., if parent `SITE-01` is unreachable, suppress alarms for `CELL-01`, `CELL-02`, and `CELL-03` and attach them to the parent fault).

5. **Incident Management Service**:
   - Maintains incident lifecycle, status transitions, severity classification (`Critical`, `Major`, `Minor`, `Warning`), and operational activity logs.
   - Calculates blast radius and estimated service impact.

6. **API Gateway & Core Service**:
   - FastAPI application exposing clean, typed REST endpoints for topology exploration, telemetry feeds, and incident management actions.

7. **Operations Web Console**:
   - Single-page application providing an interactive node-link graph view, active incident queue, detailed incident workbench, and metric telemetry dashboards.

---

## 5. Functional Requirements

- **FR-01: Synthetic Topology Modeling**: System must model the defined 27-node hierarchy (1 Core, 2 Aggregation, 6 Sites, 18 Cells) with parent-child linkage and node metadata.
- **FR-02: Deterministic Telemetry Generation**: Simulator must emit simulated metric samples (latency, jitter, packet loss, bandwidth, radio link quality) at configurable intervals (e.g., 5-second tick).
- **FR-03: Controlled Fault Injection**: System must support triggering predefined failure scenarios (e.g., core route flap, aggregation link cut, site power outage, cell radio degradation) and returning to baseline.
- **FR-04: Metric Thresholding & Alarm Generation**: System must detect threshold anomalies and generate normalized alarms with standardized severity levels.
- **FR-05: Topological Alarm Suppression**: Downstream alarms caused by upstream failures must be correlated and suppressed from generating separate top-level incidents.
- **FR-06: Incident Aggregation & Blast Radius**: Related alarms must synthesize into a single Incident containing root-cause analysis, timeline, and an accurate list of all impacted downstream nodes.
- **FR-07: Incident State Lifecycle**: Operators must be able to view, acknowledge, update status, and resolve active incidents via API.
- **FR-08: RESTful API & Observability**: System must provide documented REST endpoints to query topology, node statuses, live metrics, and incident history.

---

## 6. Non-Functional Requirements

- **NFR-01: Low Latency & High Responsiveness**:
  - API query responses for topology and incident lists must return within < 200ms under standard local load.
  - Telemetry correlation processing delay must remain under 1 second from generation to incident creation.
- **NFR-02: Portability & Zero-Cost Infrastructure**:
  - The entire stack must run locally on developer workstations (Linux, macOS, Windows) without requiring paid cloud accounts, Kubernetes clusters, or external hardware appliances.
- **NFR-03: Architectural Modularity**:
  - Strict separation of concerns between simulation, correlation logic, data persistence, and API delivery. Components communicate via well-defined domain contracts.
- **NFR-04: Maintainability & Testability**:
  - Python codebase must adhere to standard linting/formatting (PEP 8), type annotations, and automated unit/integration test coverage with `pytest`.
- **NFR-05: Extensibility**:
  - Clean abstractions to allow future replacement of the synthetic simulator with external telemetry streams (e.g., Kafka, MQTT, SNMP, or real netflow feeds) without rewriting correlation or incident modules.

---

## 7. Known Assumptions and Limitations

1. **Synthetic Data Only**: All network counters, packets, and device states are synthetically modeled. Real-world 3GPP protocol internals (e.g., GTP-U tunnel state machines, RRC connection protocols) are abstracted to representative KPIs.
2. **Fixed Topology Scale (Initial Phase)**: The initial phase is intentionally constrained to 27 nodes (1 Core, 2 Agg, 6 Sites, 18 Cells) to validate correlation algorithms and system ergonomics before scaling to tens of thousands of nodes.
3. **Embedded / Local Storage**: Initial implementation targets in-memory structures and embedded storage (SQLite / DuckDB), avoiding distributed database infrastructure during early architectural validation.
4. **Single-Tenant Operational Model**: Initial design focuses on core NOC engineering capabilities without multi-tenant authentication or external SSO enterprise integrations.
