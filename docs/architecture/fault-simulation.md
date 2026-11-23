# NEXUS Fault Simulation & Scenario Engine

## 1. Overview and Architectural Boundary

The `nexus.fault` and `nexus.transport` packages provide controlled, deterministic fault simulation and ground-truth recording across the NEXUS simulated network.

### Topology Hierarchy vs. Transport Network

- **Topology Hierarchy (`nexus.topology`)**:
  Represents organizational containment and administrative hierarchy (`CORE -> AGGREGATION -> SITE -> CELL`). Each non-root node has exactly one parent node. Node models are immutable entities.
- **Transport Network (`nexus.transport`)**:
  Represents physical and logical transport connections (`TransportLink`) between network elements. Links connect parent nodes to direct children, with upstream and downstream labels establishing the hierarchy direction and downstream failure impact propagation.
- **Constraint**: Transport links do not loosen topology invariants; topology remains a strict 4-tier tree.

---

## 2. Fault Domain Model & Lifecycle

Defined in `nexus.fault.models`, each `Fault` is an immutable specification:

| Field | Type | Description |
| :--- | :--- | :--- |
| `fault_id` | `str` | Unique non-empty string identifier. |
| `fault_type` | `FaultType` | Enum value specifying the fault category. |
| `target_id` | `str` | ID of the target entity (CELL, SITE, CORE, or transport link). |
| `start_time` | `datetime` | Activation timestamp (normalized to UTC). |
| `end_time` | `datetime` | Recovery timestamp (normalized to UTC; strictly greater than `start_time`). |
| `severity` | `float` | Finite intensity factor within $[0.0, 1.0]$. |
| `description`| `Optional[str]` | Optional human-readable notes. |

### Active Interval Semantics

Fault activity follows a strict half-open interval:
$$\text{start\_time} \le \text{timestamp} < \text{end\_time}$$
- A fault activates at its exact start time.
- A fault is active throughout the interval.
- A fault is fully recovered at its exact end time.

---

## 3. Reference Fault Scenarios

NEXUS implements six standard reference fault scenarios:

| Scenario Key | Fault Type | Target ID | Target Tier | Blast Radius | Telemetry Impact |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `cell_outage` | `CELL_OUTAGE` | `CELL-01` | Cell | 1 node (`CELL-01`) | Throughput $\to 0$ Mbps, Availability $\to 0\%$, Drop rate $\to 100\%$, Handover $\to 0\%$, RSRP $\to -145$ dBm, PRB $\to 0\%$. |
| `backhaul_failure` | `BACKHAUL_FAILURE` | `LINK-AGG-01-SITE-01` | Transport Link | 4 nodes (`SITE-01`, `CELL-01`..`03`) | Complete communication loss across downstream branch (0 Mbps throughput, 0% availability). Unrelated branches remain unaffected. |
| `radio_interference`| `RADIO_INTERFERENCE` | `CELL-05` | Cell | 1 node (`CELL-05`) | Severe SINR degradation (< 5 dB). Spectral efficiency drops, reducing throughput and elevating packet drop rates. |
| `cell_congestion` | `CELL_CONGESTION` | `CELL-10` | Cell | 1 node (`CELL-10`) | PRB utilization spikes to $\ge 90\%$. Scheduler queue delays elevate latency (> 80 ms); per-user throughput collapses. |
| `site_power_failure`| `SITE_POWER_FAILURE` | `SITE-04` | Site | 4 nodes (`SITE-04`, `CELL-10`..`12`) | Total facility power loss takes site and all 3 sector cells offline (0 Mbps throughput, 0% availability). |
| `core_router_failure`| `CORE_ROUTER_FAILURE` | `CORE-01` | Core | 1 node direct / Systemic | Transit gateway failure elevating system latency and triggering critical availability alarms across the core tier. |

---

## 4. Conflict & Overlap Policy

Multiple faults may coexist in the same scenario when they affect disjoint target nodes or non-conflicting operational dimensions.

### Operational Effect Dimensions

Faults modulate telecommunications metrics across five explicit operational effect dimensions:
- **`AVAILABILITY`**: Service accessibility and complete outage state (e.g., `CELL_OUTAGE`, `BACKHAUL_FAILURE`, `SITE_POWER_FAILURE`).
- **`RADIO_SIGNAL`**: Physical radio signal quality and signal-to-noise ratio (e.g., `RADIO_INTERFERENCE`).
- **`RADIO_RESOURCE`**: Physical radio block utilization and scheduling saturation (e.g., `CELL_CONGESTION`).
- **`PERFORMANCE`**: User-plane throughput and propagation latency.
- **`RELIABILITY`**: Session drop rate and handover success rate.

### Impact-Aware Conflict Detection

`FaultScenarioEngine` calculates the exact set of affected topology nodes for every fault during construction. A conflict occurs and raises `ConflictingFaultError` when **all** of the following conditions are met:
1. **Temporal Overlap**: The active intervals $[t_{\text{start1}}, t_{\text{end1}})$ and $[t_{\text{start2}}, t_{\text{end2}})$ intersect.
2. **Blast Radius Overlap**: The faults share at least one affected topology node ($\text{affected}_1 \cap \text{affected}_2 \ne \emptyset$).
3. **Dimension Overlap**: The faults share at least one operational effect dimension ($\text{dims}_1 \cap \text{dims}_2 \ne \emptyset$).

---

## 5. Ground Truth Recording

For every fault in a scenario, the engine precomputes an immutable `GroundTruthRecord` (`nexus.fault.models`):
- `scenario_id`: Identifier of the scenario.
- `fault_id`, `fault_type`, `target_id`: Identifiers and type.
- `start_time`, `end_time`, `severity`: Exact duration and intensity.
- `affected_node_ids`: Deterministic, breadth-first ordered tuple of all impacted topology node IDs.

Ground truth records capture the exact ground truth of injected faults, serving as the benchmark for subsequent anomaly detection and root-cause analysis (RCA) verification.

---

## 6. Recovery Verification

Fault recovery is evaluated by verifying that:
1. Deactivation API succeeds (`POST /api/v1/faults/scenarios/deactivate`).
2. Subsequent telemetry step generation produces nominal baseline observations within tier-specific operating ranges.
3. Relevant scenario alarms transition from `ACTIVE` to `CLEARED`.
4. Node KPIs converge within baseline tolerance boundaries.
