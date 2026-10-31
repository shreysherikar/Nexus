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

*Notice: Network telemetry and fault scenarios are generated by an internal synthetic simulation engine. NEXUS operates independently without requiring live carrier feeds or physical hardware.*

---

## Planned Capabilities

The following capabilities are planned for upcoming milestones and are not yet implemented:
- Automated closed-loop remediation workflows and incident ticket management.
- Real-time telemetry ingestion pipeline and Prometheus metric export.
- Interactive topology visualization and operations web dashboard.

---

## Technology Stack

- **Language**: Python 3.11+
- **Architecture**: Modular monolith with decoupled domain boundaries
- **Packaging & Build**: `pyproject.toml` with `setuptools`
- **Testing**: `pytest`
- **Dependencies**: Pure Python standard library (no external runtime dependencies)

---

## Prerequisites

- Python 3.11 or higher
- Git

---

## Installation

Clone the repository and install the project in editable mode with testing dependencies:

```bash
git clone https://github.com/shreysherikar/Nexus.git
cd Nexus/nexus-network-intelligence
python -m pip install --upgrade pip
pip install -e ".[test]"
```

---

## Running the Code

You can instantiate the reference topology, transport network, and fault scenarios directly via Python:

```python
from datetime import datetime, timedelta, timezone
from nexus.topology import build_simulated_network
from nexus.transport import build_reference_transport_network
from nexus.telemetry import SyntheticTelemetryGenerator
from nexus.fault import build_reference_scenarios

# 1. Build reference topology & transport network
topology = build_simulated_network()
transport = build_reference_transport_network(topology)

# 2. Initialize generator and fault scenarios
base_time = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
generator = SyntheticTelemetryGenerator(topology=topology, seed=42)
scenarios = build_reference_scenarios(topology, transport, base_time=base_time)

# 3. Evaluate a backhaul fiber cut scenario at 12:15 UTC (active fault window)
eval_time = base_time + timedelta(minutes=15)
base_snapshots = generator.generate_step(timestamp=eval_time)
effective_snapshots = scenarios["backhaul_failure"].apply_faults(base_snapshots, timestamp=eval_time)

site1_snap = next(s for s in effective_snapshots if s.node_id == "SITE-01")
print(f"Node: {site1_snap.node_id}")
print(f"Throughput under backhaul failure: {site1_snap.performance.throughput_mbps} Mbps")
print(f"Availability under backhaul failure: {site1_snap.reliability.availability_pct}%")

# 4. Detect anomalies and generate alarms independently
from nexus.detection import AnomalyDetectionEngine

engine = AnomalyDetectionEngine()
result = engine.process_batch(effective_snapshots)
print(f"Detected {len(result.new_alarms)} alarms across the network")
```

---

## Running Tests

Execute the complete automated test suite from the repository root:

```bash
python -m pytest -v
```

---

## Project Documentation

Detailed architectural decisions and design specifications are documented in `docs/`:

- [System Architecture & Initial Design](docs/architecture/initial-design.md)
- [Telemetry & KPI Domain Design](docs/architecture/telemetry-kpi-design.md)
- [Fault Injection & Scenario Engine Design](docs/architecture/fault-injection-design.md)
- [Anomaly Detection & Alarm Generation Design](docs/architecture/anomaly-detection-design.md)
- [Alarm Correlation & RCA Design](docs/architecture/alarm-correlation-rca-design.md)
- [ADR-001: Modular Project Architecture](docs/decisions/ADR-001-project-architecture.md)
