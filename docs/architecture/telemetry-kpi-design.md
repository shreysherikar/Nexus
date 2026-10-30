# NEXUS Telemetry & Synthetic KPI Specification

## 1. Overview and Design Decision

The telemetry domain defines typed, validated performance, reliability, and radio measurements for network elements in the NEXUS hierarchy.

### Design Choice: Structured Snapshot vs. Individual Records

Measurements for a network node are encapsulated as a composite immutable snapshot:
[`KPISnapshot`](../../src/nexus/telemetry/models.py) composed of:
1. [`PerformanceMetrics`](../../src/nexus/telemetry/models.py): Throughput (`throughput_mbps`) and round-trip latency (`latency_ms`).
2. [`ReliabilityMetrics`](../../src/nexus/telemetry/models.py): Connection drop rate (`connection_drop_rate_pct`), availability (`availability_pct`), and optional handover success rate (`handover_success_rate_pct`).
3. [`RadioMetrics`](../../src/nexus/telemetry/models.py) *(CELL tier only)*: Signal power (`rsrp_dbm`), signal quality (`sinr_db`), and capacity load (`prb_utilization_pct`).

#### Rationale:
- **Atomicity and Temporal Consistency**: Cross-metric correlation (e.g. evaluating throughput degradation in the context of high PRB utilization or poor SINR) requires measurements taken at the exact same point in time.
- **Extensibility & Prometheus Compatibility**: A structured snapshot cleanly flattens via `to_metric_dict()` into multi-gauge Prometheus time series (`nexus_throughput_mbps{node_id="..."}`) without maintaining disparate unaligned event streams.
- **Separation of Concerns**: Decomposing into sub-vectors prevents a single monolithic class while guaranteeing strict finite bounds validation on construction.

---

## 2. KPI Definitions, Units, and Operational Rationale

| Measurement | Field Name | Unit | Tier | Purpose & Diagnostic Value |
| :--- | :--- | :--- | :--- | :--- |
| **Reference Signal Received Power** | `rsrp_dbm` | dBm | Cell | Measures cellular downlink coverage strength. Diagnostic indicator of RF path loss, shadowing, or antenna feeder issues. |
| **Signal-to-Interference-plus-Noise Ratio** | `sinr_db` | dB | Cell | Measures RF link quality. Critical indicator for modulation coding scheme (MCS) selection and achievable spectral efficiency. |
| **Physical Resource Block Utilization** | `prb_utilization_pct` | % | Cell | Percentage of radio capacity scheduled. Identifies cell saturation and congestion. |
| **Throughput** | `throughput_mbps` | Mbps | All | Aggregate user-plane transfer rate across the node. |
| **Latency** | `latency_ms` | ms | All | Processing and round-trip queueing latency. |
| **Handover Success Rate** | `handover_success_rate_pct` | % | Cell | Percentage of completed inter-cell handovers without dropped sessions. |
| **Connection Drop Rate** | `connection_drop_rate_pct` | % | All | Percentage of sessions abruptly disconnected due to radio link failures or transport loss. |
| **Availability** | `availability_pct` | % | All | Synthetic measurement-window service availability percentage. *Note: this represents a synthetic window metric, not an instantaneous physical sensor reading or calculated historical uptime.* |

---

## 3. Synthetic Operating Assumptions

Baseline operational assumptions are defined per network tier in [`src/nexus/telemetry/profiles.py`](../../src/nexus/telemetry/profiles.py):

> **Disclaimer**: These ranges represent illustrative synthetic assumptions for simulation and algorithm testing. They do not represent verified production carrier thresholds or physical lab measurements.

### Tier Baselines

| Parameter | Core (`CORE-01`) | Aggregation (`AGG-01..02`) | Site (`SITE-01..06`) | Cell (`CELL-01..18`) |
| :--- | :--- | :--- | :--- | :--- |
| **Throughput (Mbps)** | 8000.0 – 10000.0 | 3000.0 – 5000.0 | 800.0 – 1500.0 | 150.0 – 450.0 |
| **Latency (ms)** | 0.5 – 2.5 | 2.0 – 6.0 | 6.0 – 14.0 | 12.0 – 28.0 |
| **Drop Rate (%)** | 0.00 – 0.02 | 0.01 – 0.05 | 0.02 – 0.10 | 0.05 – 0.50 |
| **Availability (%)** | 99.99 – 100.0 | 99.95 – 100.0 | 99.90 – 100.0 | 99.50 – 100.0 |
| **Handover Success (%)**| N/A | N/A | N/A | 98.0 – 100.0 |
| **RSRP (dBm)** | N/A | N/A | N/A | -105.0 – -75.0 |
| **SINR (dB)** | N/A | N/A | N/A | 10.0 – 30.0 |
| **PRB Utilization (%)** | N/A | N/A | N/A | 20.0 – 65.0 |

---

## 4. Synthetic Telemetry Generator Architecture

The generator ([`SyntheticTelemetryGenerator`](../../src/nexus/telemetry/generator.py)) models continuous, realistic telemetry:

1. **Topology Awareness & Profile Mapping**: Ingests an existing `Topology` instance. Custom profile mappings support partial mappings: nodes whose `NodeType` lacks a profile raise `IncompatibleNodeError` when generating snapshots.
2. **Reproducibility & Determinism**: Built on Python's isolated `random.Random(seed)`.
   - Passing an integer seed alongside explicit timestamps guarantees identical complete snapshot generation across independent generator instances.
   - When timestamp is omitted, default wall-clock timestamps (`datetime.now(timezone.utc)`) differ between runs.
3. **Temporal Continuity**: Uses a validated first-order exponential smoothing filter ($\alpha \in [0.0, 1.0]$, default $0.65$):
   $$\text{value}_t = \alpha \cdot \text{value}_{t-1} + (1 - \alpha) \cdot \text{target}_t$$
   This prevents erratic step jumps between consecutive simulation steps.
4. **Cross-KPI Relationships (Simplified Synthetic Coupling)**:
   - **Cell Performance Coupling**:
     - *SINR & Throughput*: Higher absolute SINR (spanning -10 dB to 30 dB) enhances modulation efficiency, increasing available throughput.
     - *PRB Congestion & Throughput*: Higher PRB utilization dampens remaining throughput headroom.
     - *PRB Congestion & Latency*: Heavy radio block scheduling utilization expands queue buffering, increasing round-trip latency.
   - **Cell Reliability Coupling**:
     - *SINR, Latency, and Handover Success*: Poor channel quality (low SINR) and high latency slightly lower handover success rates.
     - *SINR, Latency, and Connection Drop Rate*: Elevated latency and degraded radio conditions slightly increase connection drop rates.
   - **Transport Nodes (CORE, AGGREGATION, SITE)**:
     - *Throughput as a Load Proxy*: Throughput is used as a simplified scalar traffic load proxy (not an explicit capacity utilization or queue depth measurement). Operating near upper profile throughput ranges moderately elevates transport queueing latency.

---

## 5. Current Assumptions & Limitations

- **Normal Baseline Only**: Currently models healthy steady-state operations. Fault injection scenarios (fiber breaks, link flaps, severe cell congestion) are planned for subsequent milestones.
- **Availability Semantics**: `availability_pct` is generated as a windowed health metric within operating profiles, not a calculated historical uptime or link state machine.
- **Simplified Heuristics**: Cross-metric couplings are illustrative mathematical approximations designed for anomaly detection verification, not 3GPP-calibrated channel models or network equipment benchmarks.
- **In-Memory Generation**: Telemetry snapshots are generated on demand and are not yet persisted to a time-series store (DuckDB, SQLite, or Prometheus).
