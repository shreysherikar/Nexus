# NEXUS Fault Injection & Scenario Engine Specification

## 1. Overview and Architectural Boundary

The `nexus.fault` and `nexus.transport` packages introduce controlled, deterministic fault injection and ground-truth recording over the NEXUS simulated network.

### Difference Between Topology and Transport Links

- **Topology Hierarchy (`nexus.topology`)**:
  Represents organizational, containment, and administrative relationships (`CORE -> AGGREGATION -> SITE -> CELL`). Each non-root node has exactly one parent node. Node models are immutable entities.
- **Transport Network (`nexus.transport`)**:
  Represents physical and logical transport connections (`TransportLink`) between network elements. In this milestone, links connect a parent node to its direct child. Links are bidirectional for user traffic, with upstream and downstream labels establishing the hierarchy direction and downstream failure impact propagation.
- **Constraint**: Transport links do not mutate or loosen topology invariants; topology remains a strict 4-tier tree.

---

## 2. Fault Domain Model & Lifecycle

Defined in [`src/nexus/fault/models.py`](../../src/nexus/fault/models.py), each `Fault` is an immutable specification:

| Field | Type | Description |
| :--- | :--- | :--- |
| `fault_id` | `str` | Unique non-empty string identifier. |
| `fault_type` | `FaultType` | Enum value specifying the fault category. |
| `target_id` | `str` | ID of the target entity (CELL, SITE, or transport link). |
| `start_time` | `datetime` | Activation timestamp (normalized to UTC). |
| `end_time` | `datetime` | Recovery timestamp (normalized to UTC; strictly greater than `start_time`). |
| `severity` | `float` | Finite intensity factor within `[0.0, 1.0]`. |
| `description`| `Optional[str]` | Optional human-readable notes. |

### Active Interval Semantics

Fault activity follows a strict half-open interval:
$$\text{start\_time} \le \text{timestamp} < \text{end\_time}$$
- A fault activates at its exact start time.
- A fault is active during the window.
- A fault is fully recovered at its exact end time.

---

## 3. Supported Fault Types & Impact Propagation

| Fault Type | Target Tier | Downstream Blast Radius | Effective Telemetry Transformation |
| :--- | :--- | :--- | :--- |
| `CELL_OUTAGE` | `CELL` node | Target cell only. | Throughput $\to 0.0$ Mbps, Availability $\to 0.0\%$, Drop rate $\to 100\%$, Handover $\to 0.0\%$, RSRP $\to -145.0$ dBm, PRB $\to 0.0\%$. |
| `BACKHAUL_FAILURE` | `TransportLink` | Downstream node + all its descendants. | Downlink downstream router/site/cells suffer complete communication loss (0 Mbps throughput, 0% availability). Unrelated branches remain unaffected. |
| `RADIO_INTERFERENCE`| `CELL` node | Target cell only. | Degrades SINR proportional to severity (up to -20 dB). Radio spectral efficiency drops, reducing throughput and slightly increasing session drops. |
| `CELL_CONGESTION` | `CELL` node | Target cell only. | PRB utilization spikes towards 100%. Scheduler queue delays increase latency; available per-session throughput drops. |
| `SITE_POWER_FAILURE`| `SITE` node | Target site + all 3 subordinate cells. | Facility power loss takes site and all 3 sector cells offline (0 Mbps throughput, 0% availability). |

---

## 4. Conflict & Overlap Policy

Multiple faults may coexist in the same scenario when they affect different target nodes or non-conflicting operational dimensions.

### Operational Effect Dimensions

Faults modulate telecommunications metrics across five explicit operational effect dimensions:
- **`AVAILABILITY`**: Service accessibility and complete outage state (e.g. `CELL_OUTAGE`, `BACKHAUL_FAILURE`, `SITE_POWER_FAILURE`).
- **`RADIO_SIGNAL`**: Physical radio signal quality and signal-to-noise ratio (e.g. `RADIO_INTERFERENCE`).
- **`RADIO_RESOURCE`**: Physical radio block utilization and scheduling saturation (e.g. `CELL_CONGESTION`).
- **`PERFORMANCE`**: User-plane throughput and propagation latency.
- **`RELIABILITY`**: Session drop rate and handover success rate.

### Impact-Aware Conflict Detection

Rather than comparing target identifiers alone (which would overlook overlapping downstream blast radii between different target tiers), `FaultScenarioEngine` calculates the exact set of affected topology nodes for every fault during construction.

A conflict occurs and raises [`ConflictingFaultError`](../../src/nexus/fault/exceptions.py) when **all** of the following conditions are met:
1. **Temporal Overlap**: The active intervals $[t_{\text{start1}}, t_{\text{end1}})$ and $[t_{\text{start2}}, t_{\text{end2}})$ intersect.
2. **Blast Radius Overlap**: The faults share at least one affected topology node ($\text{affected}_1 \cap \text{affected}_2 \ne \emptyset$).
3. **Dimension Overlap**: The faults share at least one operational effect dimension ($\text{dims}_1 \cap \text{dims}_2 \ne \emptyset$).

**Examples:**
- A `BACKHAUL_FAILURE` on `LINK-AGG-01-SITE-01` impacts `SITE-01` and descendant `CELL-01..03`. Simultaneous `RADIO_INTERFERENCE` on `CELL-01` is rejected because `CELL-01` would simultaneously suffer complete outage and radio interference.
- Two `CELL_CONGESTION` faults on `CELL-01` during overlapping intervals are rejected.
- Independent faults affecting disjoint node branches (e.g., `BACKHAUL_FAILURE` on `SITE-01` branch and `RADIO_INTERFERENCE` on `CELL-04` under `SITE-02`) or non-overlapping time intervals on the same node are valid.
- If two effects cannot be combined safely, NEXUS rejects them at configuration time rather than inventing arbitrary execution precedence or silently suppressing degradation.

---

## 5. Ground Truth Recording

For every fault in a scenario, the engine precomputes an immutable [`GroundTruthRecord`](../../src/nexus/fault/models.py):
- `scenario_id`: Identifier of the scenario.
- `fault_id`, `fault_type`, `target_id`: Identifiers and type.
- `start_time`, `end_time`, `severity`: Exact duration and intensity.
- `affected_node_ids`: Deterministic, breadth-first ordered tuple of all impacted topology node IDs.

Ground truth records capture what the engine actually impacts, serving as the benchmark for subsequent anomaly detection and root-cause analysis (RCA) verification.

The scenario engine freezes the affected-node impact set for all faults at construction time. An engine uses a topology snapshot of fault impact at construction time. Reconstruct the engine to use a changed topology.

---

## 6. Deterministic Replay & Limitations

- **Topology Snapshot Semantics**: An engine uses a topology snapshot of fault impact at construction time. Reconstruct the engine to use a changed topology.
- **Complete Replay Reproducibility**: Because the scenario engine uses explicit timestamps and seeded PRNG telemetry, evaluating a scenario across any timestamp sequence produces identical telemetry and ground truth records.
- **Pure In-Memory Evaluation**: No databases, threads, background clocks, or external messaging brokers are utilized.
- **Synthetic Assumptions**: Fault degradations model stylized telecommunications behaviors for observability testing, not physical circuit simulations.
