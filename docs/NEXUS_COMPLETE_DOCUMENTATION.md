# NEXUS — Complete System Architecture & Engineering Documentation

**Authoritative Technical Specification & Implementation Guide**  
**Classification**: Engineering Single Source of Truth (SSOT)  
**Target Repository**: `https://github.com/shreysherikar/Nexus`  
**Platform Version**: `1.0.0`  
**Document Release Date**: November 23, 2026  
**Audience**: Principal Architects, Senior Backend Engineers, SREs, Network Systems Engineers, Technical Interviewers  

---

## Executive Abstract

NEXUS is a modular, high-reliability network intelligence, telemetry monitoring, and incident management platform engineered for telecommunications infrastructure observability and operations. Designed to address the fundamental challenge of cascading alarm storms in hierarchical carrier networks, NEXUS replaces decoupled, symptom-blind ticketing systems with topology-embedded real-time diagnostics.

The platform models a deterministic 4-tier network graph comprising 27 nodes (`CORE -> AGGREGATION -> SITE -> CELL`) interconnected by 26 bidirectional physical and logical transport links. Synthetic radio frequency (RF) and transport telemetry streams are generated on demand via a calibrated mathematical baseline engine incorporating first-order temporal exponential smoothing and physical cross-metric dependencies. Decoupled anomaly detection pipelines combine configurable static thresholds with hysteresis anti-flapping controls alongside dual rolling statistical baselines (Median Absolute Deviation [MAD] and Exponentially Weighted Moving Average [EWMA]), enforced by an Evaluate-Then-Commit baseline protection policy.

To conquer alert fatigue, NEXUS introduces a topology-aware alarm correlation engine powered by Lowest Common Ancestor (LCA) graph traversal, distant-core suppression, and symptom compatibility policies, collapsing cascading symptoms into focused failure clusters. These clusters are diagnosed by an explainable multi-hypothesis Root Cause Analysis (RCA) engine that evaluates physical targets (`NODE` vs. `TRANSPORT_LINK`), calculates confidence scores, attributes empirical telemetry evidence, and falls back to explicit `UNKNOWN` hypotheses when evidence is ambiguous. Durable incident records, operational severity policies (derived from topological blast radius rather than algorithmic confidence), strict lifecycle state machines, SLA breach deadline tracking, and an append-only immutable audit history are persisted in PostgreSQL via SQLAlchemy 2.x and Alembic migrations. Real-time telemetry, alarms, and incident events are streamed to a dark-mode React NOC dashboard via WebSocket streams protected by FIFO backpressure queues and serialized outbound writes.

---

# PART I — PROJECT FOUNDATION

## 1. Project Overview

### 1.1 What is NEXUS?
NEXUS is an operational software platform designed for telecommunications Network Operations Centers (NOCs) and service provider backbones. It integrates real-time network topology modeling, synthetic multivariate KPI telemetry generation, statistical anomaly detection, graph-theoretic alarm correlation, explainable root-cause diagnosis, and transactional incident lifecycle management into a cohesive, observable software platform.

### 1.2 Problem Statement
Telecommunications networks are inherently hierarchical, distributed, and tightly coupled. A modern cellular radio access network (RAN) and packet core depend on complex transport backhaul networks spanning optical fiber lines, microwave links, facility power grids, and routing switches. In such environments, physical or logical impairments rarely produce isolated symptoms; instead, a single failure cascades downstream, generating hundreds of simultaneous symptom alarms across subordinate base stations and cell towers.

Traditional Network Operations Center monitoring systems suffer from three critical architectural flaws:
1. **Cascading Alarm Storms**: When an upstream transport link is severed or a base station facility loses grid power, all downstream sector cells immediately trigger failure alerts. Conventional network monitoring tools (SNMP traps, syslog aggregators, generic ticket queues) treat every alarm as an independent event. Operators are inundated with hundreds of disjointed tickets for a single underlying fault, obscuring the primary root cause and overwhelming operations teams.
2. **Context-Free Telemetry Triage**: Performance telemetry (throughput, round-trip latency, connection drop rates, signal-to-noise ratio) is collected in isolation without embedded awareness of the underlying network graph. Determining whether a sudden throughput collapse across three radio sectors is caused by localized RF interference or an upstream fiber cut requires manual cross-referencing of static network topology diagrams and physical inventory databases.
3. **Manual, Error-Prone SLA Tracking**: Correlating related alerts by hand introduces severe triage delays, directly degrading Mean Time to Acknowledge (MTTA) and Mean Time to Resolve (MTTR). In service provider environments governed by contractual Service Level Agreements (SLAs), uncoordinated triage leads to SLA breaches, financial penalties, and degraded subscriber quality of experience (QoE).

### 1.3 Proposed Solution: The NEXUS Approach
NEXUS resolves these bottlenecks by embedding physical and logical network dependency awareness directly into every stage of the telemetry, detection, correlation, and triage lifecycle:
- **Topology-Embedded Telemetry**: Every measurement is indexed against a validated 4-tier network graph (`CORE -> AGGREGATION -> SITE -> CELL`) and associated transport link infrastructure.
- **Dual-Engine Anomaly Detection**: Point-in-time threshold breaches with hysteresis recovery bounds operate alongside non-parametric rolling statistical baselines (Median/MAD and EWMA), automatically filtering transient noise while catching subtle baseline drifts.
- **Topology-Aware Alarm Correlation**: Active alarms are clustered into coherent groups using Lowest Common Ancestor (LCA) graph algorithms, bounding correlation windows to prevent transitive chaining and rejecting false merges at distant core routers.
- **Explainable Multi-Hypothesis RCA**: Instead of predicting failure probabilities with opaque machine learning models, NEXUS evaluates domain diagnostic rules, ranks candidate causes by empirical evidence, identifies physical targets (`NODE` vs. `TRANSPORT_LINK`), and provides actionable operational remediation guidance.
- **Transactional SLA Management**: Incidents persist in relational storage with explicit lifecycle state transitions, immutable audit timelines, and operational severity policies that protect critical backbone infrastructure regardless of diagnostic certainty.
- **Real-Time Delivery & Observability**: Sub-second operational visibility is delivered to web consoles via prioritized WebSockets, while standard Prometheus exporters expose low-cardinality metrics to provisioned Grafana dashboards.

### 1.4 Target Users & Primary Personas
- **Tier-1 NOC Operators**: Monitor real-time telemetry dashboards, observe correlated alarm clusters, claim incident ownership (Acknowledge), and follow prescriptive remediation instructions.
- **Tier-2 / Tier-3 Network Engineers**: Investigate root-cause hypotheses, inspect physical link vs. node target attributions, review attributed telemetry evidence, and dispatch field technicians for physical repair.
- **NOC Operations Managers & SREs**: Track platform reliability, monitor SLA breach percentages, analyze MTTA/MTTR/MTTD operational trends, and evaluate detection precision and recall.
- **Systems & Software Engineers**: Extend diagnostic heuristic rules, integrate real network SNMP/NETCONF/OpenTelemetry telemetry adapters, and enhance graph traversal algorithms.

### 1.5 Primary Operational Use Cases
1. **Fiber Backhaul Severance Triage**: An optical fiber cut between an aggregation hub (`AGG-01`) and a site facility (`SITE-01`) cuts off communications to the site and its 3 subordinate cells (`CELL-01..03`). NEXUS correlates the resulting 20+ alarms under `SITE-01`, identifies `LINK-AGG-01-SITE-01` as the root cause, and opens a single P1 Critical incident.
2. **Facility Grid Power Blackout Handling**: A power outage at `SITE-04` drops the facility and its 3 cell sectors (`CELL-10..12`). NEXUS identifies the root cause as `SITE_POWER_FAILURE` on `SITE-04`, advises emergency generator inspection, and suppresses downstream cell tickets.
3. **Localized RF Interference Isolation**: External RF noise degrades SINR on `CELL-05` without affecting adjacent cells or upstream sites. NEXUS confines correlation to `CELL-05`, flags `RADIO_INTERFERENCE`, and directs operators to perform RF spectrum analysis.
4. **Cellular Congestion Management**: A surge in user traffic saturates Physical Resource Block (PRB) utilization on `CELL-10`. NEXUS distinguishes congestion from radio hardware failure, diagnoses `CELL_CONGESTION`, and recommends dynamic traffic offload.
5. **Core Router Degradation**: Transit latency across regional hub `CORE-01` degrades. NEXUS correlates the resulting systemic symptoms directly to `CORE-01`, alerting tier-3 routing engineers.

### 1.6 Core Engineering Objectives
- **Zero Fabrication**: Ground all documentation, contracts, and behaviors strictly in verifiable repository source code.
- **Mathematical & Algorithmic Rigor**: Explicitly document formulas, scale factors, graph invariants, and computational complexities.
- **Ground-Truth Isolation**: Enforce architectural boundaries preventing production diagnostics from inspecting simulation ground truth.
- **Deterministic Repeatability**: Guarantee identical outputs for identical simulation and alarm inputs across all platform runs.

### 1.7 Scope and Limitations
- **Current Scope**: Implemented for a validated 27-node reference topology; supports 6 reference fault scenarios; stores up to 60 telemetry snapshots per node in an in-memory sliding buffer; persists incidents in PostgreSQL; streams updates over WebSocket to a React SPA; exports Prometheus metrics.
- **Identified Limitations**: Telemetry history is volatile across container restarts; topology changes require engine reconstruction; API endpoints do not currently enforce cryptographic JWT/OAuth2 authentication; graph models assume tree/DAG hierarchy (dynamic multi-path mesh routing requires upstream preprocessing). Evaluation uses synthetic data generated from the project's own generator (`SyntheticTelemetryGenerator`). Simulated MTTD is 0.0 s because fault injection is applied instantaneously at $t=0$. Detector baseline seeds come from the same nominal profiles (`DEFAULT_PROFILES`) that the generator uses.

---

## 2. Functional Capabilities

NEXUS implements 17 distinct functional capabilities spanning simulation, detection, diagnostics, operations, and observability.

### 2.1 Network Topology Modeling
- **Purpose**: Establishes the authoritative physical and logical hierarchy of the network infrastructure.
- **Inputs**: Reference topology specifications defining node identifiers, hierarchical tiers, and parent pointers.
- **Outputs**: Validated in-memory `Topology` graph instance with lookup, lineage traversal, and status change subscription hooks.
- **Internal Implementation**: Implemented in `src/nexus/topology/topology.py` and `builder.py`. Nodes are modeled as immutable dataclasses (`Node`) classified into 4 tiers (`CORE`, `AGGREGATION`, `SITE`, `CELL`). Tree invariants (acyclicity, single root, valid parent tier) are enforced at registration time.
- **Important Source Files**:
  - `src/nexus/topology/models.py`
  - `src/nexus/topology/topology.py`
  - `src/nexus/topology/builder.py`
  - `src/nexus/topology/enums.py`
- **Dependencies**: Python standard library (`dataclasses`, `typing`).
- **Edge Cases & Failure Handling**: Attempting to add duplicate node IDs raises `DuplicateNodeError`. Establishing parent references to non-existent nodes raises `InvalidParentError`. Creating cycles or invalid hierarchy steps (e.g. CELL parenting AGGREGATION) is blocked by explicit invariant validators.

### 2.2 Physical & Logical Transport Modeling
- **Purpose**: Models physical transport links between adjacent topological tiers, specifying bandwidth capacity, propagation latency, and operational status.
- **Inputs**: End-to-end endpoint node identifiers (`upstream_node_id`, `downstream_node_id`), capacity in Mbps, and baseline latency.
- **Outputs**: Validated `TransportNetwork` graph supporting link lookups, downstream node set resolution, and link state mutation.
- **Internal Implementation**: Implemented in `src/nexus/transport/network.py` and `builder.py`. Contains 26 links (2 Core-Agg, 6 Agg-Site, 18 Site-Cell) mapping 1:1 to all non-root hierarchy edges.
- **Important Source Files**:
  - `src/nexus/transport/models.py`
  - `src/nexus/transport/network.py`
  - `src/nexus/transport/builder.py`
- **Dependencies**: `nexus.topology`.
- **Edge Cases & Failure Handling**: Links must connect nodes with valid parent-child relationships; inverted or cross-branch endpoints raise `InvalidEndpointError`. Duplicate link IDs raise `DuplicateLinkError`.

### 2.3 Synthetic Telemetry Generation
- **Purpose**: Generates realistic, reproducible, multivariate time-series KPI observations without external dependencies.
- **Inputs**: Node operating profiles (`NodeOperatingProfile`), random seed (default: 42), smoothing factor $\alpha = 0.65$, and target simulation timestamps.
- **Outputs**: Immutable `KPISnapshot` records containing performance, reliability, and (for cells) radio metrics.
- **Internal Implementation**: Implemented in `src/nexus/telemetry/generator.py`. Employs Gaussian sampling around nominal profile values bounded by physical limits, followed by first-order exponential smoothing to ensure temporal continuity. Modulates cross-KPI dependencies (e.g. higher SINR increases throughput; higher PRB utilization increases latency and reduces throughput headroom).
- **Important Source Files**:
  - `src/nexus/telemetry/generator.py`
  - `src/nexus/telemetry/profiles.py`
  - `src/nexus/telemetry/models.py`
- **Dependencies**: `random`, `math`, `nexus.topology`.
- **Edge Cases & Failure Handling**: Nodes missing operating profiles raise `IncompatibleNodeError`. Generating radio metrics for non-CELL tiers is strictly rejected by domain validation.

### 2.4 Controlled Fault Injection Simulation
- **Purpose**: Injects deterministic telecom failure scenarios into synthetic telemetry to benchmark detection, correlation, and RCA capabilities against known ground truth.
- **Inputs**: Scenario activation requests (`cell_outage`, `backhaul_failure`, `radio_interference`, `cell_congestion`, `site_power_failure`, `core_router_failure`).
- **Outputs**: Transformed `KPISnapshot` streams reflecting failure conditions, along with precomputed immutable `GroundTruthRecord` logs.
- **Internal Implementation**: Implemented in `src/nexus/fault/engine.py` and `scenarios.py`. Calculates exact downstream blast radius via breadth-first search (BFS). Rejects conflicting overlapping scenarios. Transforms metrics non-destructively: outages clamp throughput and availability to 0.0 and connection drop to 100%; backhaul cuts elevate transit latency; site power failures zero out facilities while preserving baseline latency.
- **Important Source Files**:
  - `src/nexus/fault/models.py`
  - `src/nexus/fault/engine.py`
  - `src/nexus/fault/scenarios.py`
  - `src/nexus/fault/service.py`
- **Dependencies**: `nexus.topology`, `nexus.transport`, `nexus.telemetry`.
- **Edge Cases & Failure Handling**: Conflicting scenarios with overlapping time windows, shared nodes, or competing effect dimensions raise `ConflictingFaultError`. Target nodes incompatible with fault types raise `IncompatibleTargetError`.

### 2.5 In-Memory Telemetry Storage
- **Purpose**: Provides high-throughput, low-latency, sliding-window storage for recent telemetry observations.
- **Inputs**: Incoming `KPISnapshot` instances.
- **Outputs**: Historical snapshot arrays, latest node observations, and paginated time-range query slices.
- **Internal Implementation**: Implemented in `src/nexus/telemetry/store.py`. Maintains independent, bounded `collections.deque(maxlen=60)` per node (total capacity: $27 \times 60 = 1,620$ snapshots). Thread-safe read/write locking protects concurrent queries and generation cycles.
- **Important Source Files**:
  - `src/nexus/telemetry/store.py`
- **Dependencies**: `threading.RLock`, `collections.deque`.
- **Edge Cases & Failure Handling**: Memory consumption is strictly $O(1)$ bounded by deque maxlen; older snapshots roll off automatically without memory leakage.

### 2.6 Static Threshold Anomaly Detection
- **Purpose**: Evaluates point-in-time KPI values against operational service bounds with hysteresis anti-flapping controls.
- **Inputs**: `KPISnapshot` observations and active `ThresholdRule` configurations.
- **Outputs**: `AnomalyEvent` instances with severity classifications (`WARNING`, `MAJOR`, `CRITICAL`).
- **Internal Implementation**: Implemented in `src/nexus/detection/threshold_detector.py` and `rules.py`. Supports comparison operators (`GT`, `GTE`, `LT`, `LTE`). Enforces optional `clear_threshold` values to prevent flapping when measurements oscillate near threshold boundaries.
- **Important Source Files**:
  - `src/nexus/detection/threshold_detector.py`
  - `src/nexus/detection/rules.py`
  - `src/nexus/detection/models.py`
- **Dependencies**: `nexus.telemetry`.
- **Edge Cases & Failure Handling**: Inverted hysteresis boundaries (e.g. clear threshold higher than trigger threshold for GT operator) are rejected at configuration time with `InvalidRuleError`.

### 2.7 Rolling Statistical Anomaly Detection (Median/MAD & EWMA)
- **Purpose**: Detects subtle, unpredicted deviations from historical normal operating baselines without static threshold limits.
- **Inputs**: Time-series metric streams per `(node_id, metric_name)`.
- **Outputs**: Statistical `AnomalyEvent` instances with evidence detailing median, MAD, scale, EWMA mean, variance, and deviation scores.
- **Internal Implementation**: Implemented in `src/nexus/detection/statistical_detector.py`:
  - *Rolling Median*: Computes median and Median Absolute Deviation (MAD) over a 20-sample sliding window. Scales MAD by $1.4826$ for normal consistency and applies a minimum scale floor derived from nominal profile spread ($(\text{max} - \text{min})/6.0$, or $5\%$ of median / $1.0$). Flags anomalies when deviation score exceeds $3.0$.
  - *Recursive EWMA*: Tracks exponentially weighted mean ($\alpha = 0.2$) and sample variance. Flags anomalies when residual deviates by $\ge 3.0$ standard deviations.
  - *Directional KPI Filtering*: Categorizes metrics into `HIGHER_IS_BETTER_KPIS` (`availability_pct`, `throughput_mbps`, `sinr_db`, `rsrp_dbm`, `handover_success_rate_pct`), `LOWER_IS_BETTER_KPIS` (`latency_ms`, `packet_loss_pct`, `connection_drop_rate_pct`), and `RESOURCE_UTILIZATION_KPIS` (`prb_utilization_pct`, `cpu_utilization_pct`). Positive service improvements (e.g. higher throughput or lower latency) are strictly filtered out to prevent false-positive alarms.
  - *Throughput Surge Threshold*: Directional throughput expansion is permitted up to `surge_ratio_threshold` (default: 2.0x nominal) before flagging positive surge anomalies.
  - *Profile Baseline Pre-Seeding*: Initialized via `seed_from_profile` and `seed_baselines` from `DEFAULT_PROFILES`, ensuring reliable detection from step 1 without cold-start vulnerability.
  - *Two-Sample Recovery Hysteresis*: Employs `consecutive_recovery_count = 2`, requiring 2 consecutive healthy observations before clearing an active statistical alarm and resetting the counter on any unhealthy observation.
  - *Evaluate-Then-Commit Protection*: Any sample flagged as anomalous is strictly excluded from baseline updates, preventing fault data from corrupting historical baselines.
- **Important Source Files**:
  - `src/nexus/detection/statistical_detector.py`
  - `src/nexus/detection/engine.py`
  - `src/nexus/telemetry/profiles.py`
- **Dependencies**: `statistics.median`, `math.sqrt`.
- **Edge Cases & Failure Handling**: Protected against division-by-zero via profile-spread and percentage scale floors. Unhealthy recovery samples immediately reset the 2-sample recovery hysteresis counter.

### 2.8 Alarm Lifecycle Management & Deduplication
- **Purpose**: Tracks active alarms, updates duration and breach counts, prevents alert ticket duplication, and maintains cleared history.
- **Inputs**: `AnomalyEvent` records from detection engines and recovery confirmation signals.
- **Outputs**: Active `Alarm` instances, cleared alarm logs, and WebSocket lifecycle notifications.
- **Internal Implementation**: Implemented in `src/nexus/detection/alarm_manager.py`. Deduplicates alarms using an immutable composite key: `(node_id, metric_name, rule_id, source)`. If an active alarm exists for this key, its `last_seen`, `observation_count`, and `current_value` are updated in place without generating a duplicate alarm ID. When recovery conditions are met, the alarm transitions to `CLEARED`, records `cleared_at`, and archives into cleared history.
- **Important Source Files**:
  - `src/nexus/detection/alarm_manager.py`
  - `src/nexus/detection/models.py`
- **Dependencies**: `dataclasses.replace`.
- **Edge Cases & Failure Handling**: Stale recovery signals for non-existent alarms return `None` safely without mutating state.

### 2.9 Topology-Aware Alarm Correlation (LCA Algorithm)
- **Purpose**: Groups concurrent, related symptom alarms into single correlation clusters based on physical and topological hierarchy dependencies.
- **Inputs**: Active `Alarm` records and the network `Topology`.
- **Outputs**: `CorrelationResult` containing immutable `CorrelationGroup` instances and reduction ratios.
- **Internal Implementation**: Implemented in `src/nexus/correlation/engine.py`. Evaluates temporal proximity (default: $\le 300\text{s}$), same-node multi-metric affinity, Lowest Common Ancestor (LCA) tree traversal, maximum ancestor distance ($\le 2$ hops), distant core suppression (rejects collapsing independent aggregation branches into `CORE-01`), and symptom compatibility (restricts localized radio/congestion metrics to single-node affinity). Employs BFS graph clustering with a maximum onset time-span constraint to prevent uncontrolled transitive chaining.
- **Important Source Files**:
  - `src/nexus/correlation/engine.py`
  - `src/nexus/correlation/models.py`
- **Dependencies**: `nexus.topology`, `collections.deque`.
- **Edge Cases & Failure Handling**: Single isolated alarms are preserved as singleton groups when `group_singletons=True`. Empty alarm inputs return empty correlation envelopes immediately without graph traversal overhead.

### 2.10 Multi-Hypothesis Root Cause Analysis (RCA)
- **Purpose**: Diagnoses the initiating failure cause behind a correlation group, identifies physical targets, and scores hypotheses.
- **Inputs**: `CorrelationGroup` instances, `Topology`, `TransportNetwork`, and fresh `KPISnapshot` records.
- **Outputs**: `RCAResult` records containing ranked candidate `RootCauseHypothesis` items, primary diagnosis, attributed evidence, and recommended operator actions.
- **Internal Implementation**: Implemented in `src/nexus/rca/engine.py` and `rules.py`. Filters telemetry strictly relative to the incident onset timestamp, discarding unobservable future data and stale historical snapshots. Evaluates candidate diagnostic rules (`evaluate_backhaul_failure`, `evaluate_site_power_failure`, `evaluate_radio_interference`, `evaluate_cell_congestion`, `evaluate_cell_outage`, `evaluate_core_router_failure`). Ranks candidates deterministically by confidence score, evidence count, and tie-breakers. Falls back to an explicit `UNKNOWN` hypothesis with recommended tier-2 triage actions if evidence is insufficient.
- **Important Source Files**:
  - `src/nexus/rca/engine.py`
  - `src/nexus/rca/rules.py`
  - `src/nexus/rca/models.py`
- **Dependencies**: `nexus.correlation`, `nexus.topology`, `nexus.transport`.
- **Edge Cases & Failure Handling**: Ambiguous evidence outputs `UNKNOWN` with confidence 0.0 rather than guessing an unverified hypothesis.

### 2.11 Incident Lifecycle & Deduplication Management
- **Purpose**: Converts diagnosed diagnostic clusters into durable operational tickets and manages ticket state transitions.
- **Inputs**: `CorrelationGroup` and `RCAResult` objects, or manual operator creation requests.
- **Outputs**: Persisted `Incident` records with SLA deadlines, status flags, and timeline audit logs.
- **Internal Implementation**: Implemented in `src/nexus/incidents/service.py` and `repository.py`. Uses `create_or_update_incident()`: checks for existing active incidents matching the correlation group ID, anchor node, or intersecting alarm IDs; if found, updates the ticket in place (updating RCA confidence and merging new alarms), strictly preventing ticket duplication during sustained faults. Enforces state transitions (`OPEN -> ACKNOWLEDGED -> RESOLVED`).
- **Important Source Files**:
  - `src/nexus/incidents/service.py`
  - `src/nexus/incidents/repository.py`
  - `src/nexus/incidents/models.py`
- **Dependencies**: `sqlalchemy`, `nexus.rca`, `nexus.correlation`.
- **Edge Cases & Failure Handling**: Modifying or reopening resolved incidents is rejected with HTTP 400. Duplicate creation with identical correlation group IDs raises `DuplicateIncidentError` (HTTP 409).

### 2.12 Operational Severity & Dispatch Policy
- **Purpose**: Assigns operational severity (`CRITICAL`, `MAJOR`, `WARNING`, `MINOR`) and dispatch priority (`P1` to `P4`) based on physical network impact rather than diagnostic confidence.
- **Inputs**: `CorrelationGroup` topological tier and affected node count.
- **Outputs**: Assigned severity and priority.
- **Internal Implementation**: Implemented in `src/nexus/incidents/severity.py`. Any critical alarm on `CORE` or `AGGREGATION` tiers or affecting $\ge 5$ nodes is automatically assigned `CRITICAL (P1)`. Access-tier critical alarms or major backbone alarms are assigned `MAJOR (P2)`. Major access or multi-node warning alarms are `WARNING (P3)`. Isolated minor conditions are `MINOR (P4)`.
- **Important Source Files**:
  - `src/nexus/incidents/severity.py`
- **Dependencies**: `nexus.incidents.enums`.

### 2.13 SLA Deadline Calculation & Compliance Tracking
- **Purpose**: Establishes contractual acknowledgement and resolution deadlines and tracks compliance.
- **Inputs**: Incident creation timestamp and operational severity.
- **Outputs**: `SLADeadlines` timestamps and real-time `SLABreachStatus` compliance flags.
- **Internal Implementation**: Implemented in `src/nexus/incidents/sla.py`. Sets acknowledgement deadlines (15m for P1, 30m for P2, 60m for P3, 120m for P4) and resolution deadlines (1h for P1, 4h for P2, 12h for P3, 24h for P4). When an incident resolves, SLA compliance permanently freezes based on historical timestamps, preventing retroactive breaches from future clock ticks.
- **Important Source Files**:
  - `src/nexus/incidents/sla.py`
- **Dependencies**: `datetime`, `math`.

### 2.14 Append-Only Incident Audit History
- **Purpose**: Provides an immutable, chronologically ordered audit log for regulatory compliance and post-incident reviews.
- **Inputs**: State transition events, operator notes, and system attributions.
- **Outputs**: Ordered `TimelineEvent` records linked to parent incidents.
- **Internal Implementation**: Implemented in `src/nexus/incidents/repository.py`. Persisted in table `incident_timeline_events` with foreign key cascade to `incidents`. Every creation, acknowledgement, resolution, or note appends an immutable event with UTC timestamp and actor metadata.
- **Important Source Files**:
  - `src/nexus/incidents/models.py`
  - `src/nexus/incidents/repository.py`
- **Dependencies**: `sqlalchemy`.

### 2.15 Real-Time WebSocket Event Broadcasting
- **Purpose**: Streams live telemetry, alarm transitions, and incident state changes to connected operational consoles.
- **Inputs**: Domain events published from synchronous worker threads or asynchronous route handlers.
- **Outputs**: Serialized JSON frames delivered over persistent WebSocket connections (`/ws/live`).
- **Internal Implementation**: Implemented in `src/nexus/events/broadcaster.py` and `api.py`. Features thread-safe cross-thread dispatch via `loop.call_soon_threadsafe`. Each subscriber receives a bounded queue (`maxsize=100`) with FIFO backpressure (evicting oldest events when full). A dedicated single outbound `sender_task` serializes all socket writes, preventing frame corruption and balancing heartbeat PING/PONG responses with domain event streams.
- **Important Source Files**:
  - `src/nexus/events/broadcaster.py`
  - `src/nexus/events/api.py`
  - `src/nexus/events/models.py`
- **Dependencies**: `asyncio`, `fastapi.WebSocket`.
- **Edge Cases & Failure Handling**: Abrupt client disconnections cleanly unregister the subscriber queue without raising unhandled exceptions or leaking memory.

### 2.16 Prometheus Observability Exporter
- **Purpose**: Instruments the application and exposes operational metrics in standard Prometheus text format.
- **Inputs**: Subsystem state, HTTP requests, telemetry buffers, active alarms, and incident metrics.
- **Outputs**: Prometheus metrics exposition endpoint (`GET /metrics`).
- **Internal Implementation**: Implemented in `src/nexus/metrics.py`. Enforces strict low-cardinality label rules (no dynamic IDs or timestamps). Normalizes HTTP endpoints (e.g. `/api/v1/incidents/{incident_id}`). Tracks request latency histograms and domain state gauges (node tiers, active alarms, MTTA, MTTR, MTTD, SLA compliance). Excludes `/metrics` from request counters to prevent scrape self-distortion.
- **Important Source Files**:
  - `src/nexus/metrics.py`
- **Dependencies**: `prometheus_client`.

### 2.17 Automated Pipeline Evaluation & Benchmarking
- **Purpose**: Evaluates detection accuracy, alarm precision, fault recall, hybrid F1-score, MTTD, and RCA Top-1 diagnostic accuracy against ground truth.
- **Inputs**: Injected `GroundTruthRecord` lists, detected `Alarm` sequences, and `RCAResult` structures.
- **Outputs**: Comprehensive `EvaluationReport` and `RCAEvaluationReport` summaries.
- **Benchmark Performance**: Validated across all 6 reference telecom fault scenarios (seed 42, 30 steps):
  - *Fault Recall*: **100.0%** (6 / 6 scenarios detected, 0 undetected)
  - *Alarm Precision*: **94.46%** micro-average (665 true positives, 39 false positives out of 704 total alarms)
  - *Hybrid F1-Score*: **0.9715** micro-average
  - *Mean Time to Detect (MTTD)*: **0.0 s** (instantaneous synthetic injection)
  - *Alarm Storm Reduction*: **94.60%** reduction ratio (704 raw alarms condensed into 38 correlation groups)
  - *Root Cause Diagnostics*: **100.0%** Top-1 Cause Accuracy, **100.0%** Target Entity Accuracy
- **Internal Implementation**: Implemented in `src/nexus/evaluation/evaluator.py` and `scenario_replay.py`. Matches alarms to ground-truth fault time windows plus configurable grace periods. Compares primary RCA hypotheses against actual injected fault types and physical targets.
- **Important Source Files**:
  - `src/nexus/evaluation/evaluator.py`
  - `src/nexus/evaluation/scenario_replay.py`
  - `src/nexus/evaluation/models.py`
  - `scripts/run_benchmark.py`
- **Dependencies**: `nexus.fault`, `nexus.rca`.

---

## 3. Technology Stack

NEXUS leverages a modern, typed, asynchronous polyglot technology stack engineered for high concurrency, deterministic execution, and operational observability.

| Layer | Technology | Verified Version | Purpose in NEXUS | Selection Rationale | Primary Codebase Locations |
|:---|:---|:---|:---|:---|:---|
| **Backend Runtime** | Python | `3.11` (Docker) / `3.14.7` (Host venv) | Primary backend runtime environment | Strong standard library, native typing, asynchronous event loop (`asyncio`), and rich data modeling capabilities | Entire `nexus-network-intelligence/src/` |
| **Web / ASGI Framework** | FastAPI | `0.162.0` | Central REST API routing and ASGI application server | Native OpenAPI 3.1 generation, dependency injection, high throughput ASGI performance, seamless WebSocket integration | `src/nexus/main.py`, `src/nexus/*/api.py` |
| **ASGI Web Server** | Uvicorn | `0.54.0` | Production ASGI web server running FastAPI | High-concurrency asynchronous HTTP/1.1 and WebSocket protocol handling | `src/nexus/main.py`, `Dockerfile` |
| **Data Validation** | Pydantic | `2.14.2` | Data validation, contract serialization, and schema definition | Strict runtime type enforcement, fast Rust-based core (`pydantic_core 2.50.2`), automatic OpenAPI documentation | `src/nexus/*/schemas.py`, `src/nexus/main.py` |
| **Relational ORM** | SQLAlchemy | `2.1.6` | Relational database mapping, transactional persistence, and queries | Modern 2.0-style type-safe query syntax (`Mapped`, `mapped_column`, `select()`), connection pooling | `src/nexus/incidents/repository.py` |
| **Schema Migrations** | Alembic | `1.20.1` | Relational database schema evolution and version tracking | Reversible, versioned database DDL migration scripts executed automatically upon container startup | `migrations/`, `alembic.ini`, `docker-entrypoint.sh` |
| **PostgreSQL Driver** | Psycopg 3 | `3.3.6` (binary) | Next-generation Python DB-API driver for PostgreSQL | Native PostgreSQL 15 protocol support, async engine compatibility, high performance, robust connection pooling | `pyproject.toml`, `docker-entrypoint.sh` |
| **Relational Database** | PostgreSQL | `15-alpine` | Authoritative persistent storage for incidents and timeline events | ACID compliance, JSON column querying, battle-tested durability in enterprise telecommunications | `docker-compose.yml`, persistent volume `postgres_data` |
| **Embedded Database** | SQLite 3 | Standard Library | Local development and test runner storage | Zero-configuration, file-backed or in-memory persistence for fast local unit test execution | `src/nexus/incidents/api.py`, `tests/` |
| **WebSocket Engine** | WebSockets | `17.4` | Asynchronous real-time full-duplex socket transport | Low latency, RFC 6455 compliance, thread-safe queue integration | `src/nexus/events/api.py`, `src/nexus/events/broadcaster.py` |
| **Metrics Exporter** | Prometheus Client | `0.26.0` | Metrics collection and exposition in text format | Standardized exposition (`/metrics`), thread-safe custom CollectorRegistry support | `src/nexus/metrics.py` |
| **Metrics Scraper** | Prometheus TSDB | `v2.51.0` | Time-series database polling `/metrics` every 5 seconds | Low footprint, PromQL querying, operational alerting foundation | `deploy/prometheus/prometheus.yml`, `docker-compose.yml` |
| **Observability UI** | Grafana | `10.4.0` | Operations dashboards visualizing platform, network, alarms, and APIs | Auto-provisioned datasources and dashboards, rich visual analytics | `deploy/grafana/`, `docker-compose.yml` |
| **Frontend Framework** | React | `18.3.1` | Component-based single-page application UI | Virtual DOM rendering, reactive state hooks, ecosystem maturity | `frontend/src/` |
| **Frontend Language** | TypeScript | `5.6.3` | Static type safety across the web console | Compile-time prevention of null pointer and property access errors, shared API contract types | `frontend/tsconfig.json`, `frontend/src/types/` |
| **Frontend Bundler** | Vite | `5.4.21` | Frontend build tooling and development server | Extremely fast Hot Module Replacement (HMR), optimized production bundling using Rollup | `frontend/vite.config.ts` |
| **CSS / Styling** | Tailwind CSS | `3.4.16` | Utility-first CSS styling with custom dark-mode theme | Clean, consistent styling, dark NOC color palette, responsive layout | `frontend/tailwind.config.js`, `frontend/src/styles/` |
| **UI Icons** | Lucide React | `0.468.0` | Telecommunications and dashboard iconography | High-quality, tree-shakeable SVG vector icons | `frontend/src/components/`, `frontend/src/pages/` |
| **Client Routing** | React Router DOM | `6.28.0` | Client-side declarative route management | SPA navigation without page refreshes, URL state synchronization | `frontend/src/App.tsx` |
| **Package Manager** | pnpm | `9.15.4` | Fast, disk space-efficient node package manager | Pinned via Corepack, frozen lockfile verification (`pnpm-lock.yaml`) | `frontend/package.json`, `frontend/Dockerfile` |
| **Reverse Proxy** | Nginx | `1.25-alpine` | Production web server hosting SPA and proxying API/WS | High-performance static asset delivery, WebSocket upgrade proxying | `frontend/nginx.conf`, `frontend/Dockerfile` |
| **Backend Testing** | Pytest | `9.2.0` | Unit, integration, and scenario testing framework | Fixtures, parameterized testing, fast discovery, async test support | `tests/`, `pyproject.toml` |
| **Frontend Testing** | Vitest | `2.1.8` | Unit and component testing framework for Vite | Direct compatibility with Vite config, Jest-compatible assertions | `frontend/tests/`, `frontend/vite.config.ts` |
| **DOM Testing** | Testing Library | `@testing-library/react 16.1.0` | User-centric DOM testing utilities | Simulates authentic user interactions (clicking, navigating, typing) | `frontend/tests/` |

---

## 4. Complete Repository Structure

The NEXUS platform source code is organized as a clean modular monolithic repository with strict package boundaries:

```
nexus-network-intelligence/
├── .github/
│   └── workflows/
│       └── ci.yml                      # GitHub Actions automated CI workflow (lint, test, build, e2e)
├── deploy/
│   ├── grafana/
│   │   ├── dashboards/
│   │   │   ├── 01-platform-overview.json         # Executive platform overview dashboard
│   │   │   ├── 02-network-kpi-health.json        # Network tier KPI distributions & health
│   │   │   ├── 03-alarm-incident-overview.json   # Alarms by severity & active incidents
│   │   │   ├── 04-fault-simulation.json          # Active scenario status & affected nodes
│   │   │   └── 05-api-infrastructure-health.json # HTTP request latency, status codes, rates
│   │   └── provisioning/
│   │       ├── dashboards/dashboards.yml         # Automated file-based dashboard provider
│   │       └── datasources/prometheus.yml        # Auto-provisioned Prometheus datasource
│   └── prometheus/
│       └── prometheus.yml              # Prometheus scrape configuration (backend:8000/metrics)
├── docs/                               # Operational runbooks, architecture docs, and ADRs
│   ├── api-and-websocket.md
│   ├── database-schema-migrations.md
│   ├── observability-deployment.md
│   ├── operations-runbook.md
│   ├── testing-verification.md
│   ├── architecture/
│   └── decisions/
│       └── ADR-001-project-architecture.md
├── frontend/                           # React 18 / TypeScript single-page application
│   ├── public/
│   ├── src/
│   │   ├── api/
│   │   │   └── client.ts               # Typed REST API client with timeout & cancellation
│   │   ├── components/
│   │   │   ├── common/                 # Reusable UI widgets (MetricCard, DataTable, StatusBadge, etc.)
│   │   │   └── layout/                 # Layout shell, Sidebar, TopBar, PageHeader
│   │   ├── pages/
│   │   │   ├── OverviewPage.tsx        # NOC executive overview, health summary & active alarms
│   │   │   ├── NetworkMapPage.tsx      # Hierarchical 4-tier network visual topology map
│   │   │   ├── KpisPage.tsx            # Live telemetry observation charts & step generator
│   │   │   ├── AlarmsPage.tsx          # Real-time alarm inventory, filtering, and promotion
│   │   │   ├── IncidentsPage.tsx       # Incident tracking, SLA countdowns, triage modals
│   │   │   └── AnalyticsPage.tsx       # Historical SLA metrics, MTTA/MTTR/MTTD charts
│   │   ├── styles/                     # Tailwind CSS global stylesheet
│   │   ├── types/                      # TypeScript type declarations (API, WebSocket, Navigation)
│   │   ├── utils/                      # Helper evaluators (KPI threshold evaluation)
│   │   ├── websocket/                  # Native WebSocket client & React custom subscription hooks
│   │   ├── App.tsx                     # Application shell and React Router route configuration
│   │   └── main.tsx                    # React application entrypoint
│   ├── tests/                          # Vitest component, navigation, and API client test suites
│   ├── Dockerfile                      # Multi-stage Dockerfile (Node 20 builder -> Nginx runner)
│   ├── nginx.conf                      # Nginx reverse proxy configuration (/api & /ws routing)
│   ├── package.json                    # Frontend package dependencies and scripts
│   ├── pnpm-lock.yaml                  # Pinned frozen pnpm lockfile
│   ├── tailwind.config.js              # Dark NOC theme color definitions
│   └── vite.config.ts                  # Vite bundler configuration & vitest environment
├── migrations/                         # Alembic database migration scripts
│   ├── versions/
│   │   └── 0001_initial_incident_schema.py # Initial DDL: incidents & incident_timeline_events
│   ├── env.py                          # Alembic runtime environment and SQLAlchemy metadata hook
│   └── script.py.mako                  # Template for generating future database migrations
├── scripts/
│   └── verify_e2e_acceptance.py        # Authoritative 25-step live acceptance verification harness
├── src/
│   └── nexus/                          # Authoritative backend Python package
│       ├── correlation/                # Topology-aware alarm correlation engine
│       │   ├── engine.py               # AlarmCorrelationEngine, LCA traversal, grouping
│       │   ├── exceptions.py           # Domain exceptions (CorrelationError, MalformedAlarmError)
│       │   └── models.py               # CorrelationGroup, CorrelationResult, CorrelationConfig
│       ├── detection/                  # Anomaly detection and alarm management
│       │   ├── alarm_manager.py        # AlarmManager: deduplication, lifecycle, state machine
│       │   ├── api.py                  # FastAPI REST router for alarms and detection rules
│       │   ├── engine.py               # AnomalyDetectionEngine coordinating detectors
│       │   ├── exceptions.py           # InvalidRuleError, InvalidDetectorConfigError
│       │   ├── models.py               # Alarm, AnomalyEvent, Severity, DetectionSource
│       │   ├── rules.py                # ThresholdRule dataclass, hysteresis, 8 default telecom rules
│       │   ├── schemas.py              # Pydantic request/response schemas for detection API
│       │   ├── service.py              # AlarmService singleton facade
│       │   ├── statistical_detector.py # Rolling Median (MAD) and recursive EWMA detectors
│       │   └── threshold_detector.py   # ThresholdDetector evaluating static bounds
│       ├── evaluation/                 # Post-hoc benchmarking and validation
│       │   ├── evaluator.py            # Precision, recall, F1, MTTD, RCA accuracy calculations
│       │   ├── models.py               # EvaluationReport, RCAEvaluationReport dataclasses
│       │   └── scenario_replay.py      # Automated replay and evaluation of reference scenarios
│       ├── events/                     # Real-time event broadcasting and WebSockets
│       │   ├── api.py                  # WebSocket route handler (/ws/live), serialized writer task
│       │   ├── broadcaster.py          # EventBroadcaster: thread-safe queues, FIFO backpressure
│       │   └── models.py               # LiveEvent envelope, EventType enum
│       ├── fault/                      # Fault injection simulation engine
│       │   ├── api.py                  # FastAPI REST router for scenario catalog & activation
│       │   ├── engine.py               # FaultScenarioEngine: blast radius, conflict detection
│       │   ├── exceptions.py           # ConflictingFaultError, IncompatibleTargetError
│       │   ├── models.py               # Fault, FaultType, GroundTruthRecord, EffectDimension
│       │   ├── scenarios.py            # Reference scenario builders (6 telecom fault profiles)
│       │   ├── schemas.py              # Pydantic schemas for fault API
│       │   └── service.py              # FaultService singleton facade
│       ├── incidents/                  # Transactional incident management and SLA enforcement
│       │   ├── api.py                  # FastAPI REST router (/api/v1/incidents)
│       │   ├── enums.py                # IncidentStatus, IncidentSeverity, IncidentPriority, ActorType
│       │   ├── exceptions.py           # DuplicateIncidentError, InvalidStateTransitionError
│       │   ├── metrics.py              # MetricsCalculator: MTTA, MTTR, MTTD, compliance stats
│       │   ├── models.py               # Domain Incident and TimelineEvent dataclasses
│       │   ├── repository.py           # SQLAlchemy 2.x IncidentRepository, ORM models
│       │   ├── schemas.py              # Pydantic DTOs and API request/response models
│       │   ├── service.py              # IncidentService: lifecycle, transitions, audit timeline
│       │   ├── severity.py             # OperationalSeverityPolicy: blast radius severity mapping
│       │   └── sla.py                  # SLACalculator: deadline calculation and breach evaluation
│       ├── rca/                        # Root cause analysis engine
│       │   ├── engine.py               # RootCauseAnalysisEngine, hypothesis ranking, UNKNOWN
│       │   ├── exceptions.py           # RCAError, InsufficientTelemetryError
│       │   ├── models.py               # RootCauseHypothesis, RCAResult, EvidenceItem
│       │   └── rules.py                # 6 heuristic diagnostic rules (backhaul, power, etc.)
│       ├── telemetry/                  # Telemetry simulation and sliding buffer
│       │   ├── api.py                  # FastAPI REST router for telemetry queries and step trigger
│       │   ├── exceptions.py           # TelemetryError, IncompatibleNodeError
│       │   ├── generator.py            # SyntheticTelemetryGenerator: Gaussian + exponential smoothing
│       │   ├── models.py               # KPISnapshot, PerformanceMetrics, RadioMetrics, ReliabilityMetrics
│       │   ├── orchestrator.py         # TelemetryPipeline wiring generation to detection, correlation & RCA
│       │   ├── profiles.py             # NodeOperatingProfile definitions across 4 tiers
│       │   ├── schemas.py              # Pydantic schemas for telemetry API
│       │   └── store.py                # TelemetryStore: thread-safe sliding buffer (maxlen=60)
│       ├── topology/                   # Network hierarchy graph
│       │   ├── api.py                  # FastAPI REST router for topology discovery
│       │   ├── builder.py              # build_simulated_network(): 27-node reference topology
│       │   ├── enums.py                # NodeType (CORE, AGG, SITE, CELL), NodeStatus
│       │   ├── exceptions.py           # NodeNotFoundError, InvalidParentError, DuplicateNodeError
│       │   ├── models.py               # Node dataclass
│       │   ├── schemas.py              # Pydantic schemas for topology API
│       │   └── topology.py             # Topology graph class: tree traversal, listeners
│       ├── transport/                  # Physical transport links
│       │   ├── builder.py              # build_reference_transport_network(): 26 reference links
│       │   ├── exceptions.py           # TransportError, InvalidEndpointError, DuplicateLinkError
│       │   ├── models.py               # TransportLink dataclass
│       │   └── network.py              # TransportNetwork graph class: link querying, state
│       ├── main.py                     # Central FastAPI application, lifespan context, CORS
│       └── metrics.py                  # Prometheus metrics manager: low-cardinality gauges/counters
├── tests/                              # Pytest backend test suite (597 test cases)
│   ├── test_backend_read_api.py
│   ├── test_correlation.py
│   ├── test_detection.py
│   ├── test_evaluation.py
│   ├── test_fault.py
│   ├── test_fault_integration.py
│   ├── test_ground_truth_isolation.py  # AST inspection verifying zero ground-truth leakage
│   ├── test_incidents_api.py
│   ├── test_incidents_domain.py
│   ├── test_incidents_persistence.py
│   ├── test_main_integration.py
│   ├── test_prometheus_metrics.py
│   ├── test_rca.py
│   ├── test_rca_evaluation.py
│   ├── test_telemetry.py
│   ├── test_topology.py
│   ├── test_transport.py
│   └── test_websocket_events.py
├── alembic.ini                         # Alembic database migration configuration
├── docker-compose.yml                  # 5-service production Compose specification
├── docker-entrypoint.sh                # Container entrypoint: waits for PG & runs migrations
├── Dockerfile                          # Production backend container build definition
├── pyproject.toml                      # Python build configuration and dependencies
└── README.md                           # Quickstart guide and overview
```

---

## 5. Environment Setup and Installation

### 5.1 Prerequisites
- **Docker & Docker Compose**: Docker Engine 24.0+ and Docker Compose v2.20+
- **Host OS**: Linux (Ubuntu 22.04+), macOS (13+), or Windows 10/11 Enterprise with WSL2
- **Python (Local Dev)**: Python 3.11 or Python 3.12 (Python 3.14 compatible)
- **Node.js (Frontend Dev)**: Node.js 20.x LTS with Corepack enabled (`pnpm 9.15.4`)

### 5.2 Environment Variables Reference
Copy `.env.example` to `.env` in the repository root:
```bash
cp .env.example .env
```

| Variable Name | Default Value | Description & Security Guidelines |
|:---|:---|:---|
| `POSTGRES_USER` | `nexus_user` | PostgreSQL application database username |
| `POSTGRES_PASSWORD` | *(Required)* | Strong PostgreSQL password (never commit actual secrets) |
| `POSTGRES_DB` | `nexus_db` | Primary production relational database name |
| `POSTGRES_HOST` | `postgres` | Hostname of database server (`postgres` in Docker, `127.0.0.1` on host) |
| `POSTGRES_PORT` | `5432` | Database port number |
| `DATABASE_URL` | *(Computed)* | SQLAlchemy connection string (`postgresql+psycopg://user:pass@host:5432/db`) |
| `ENVIRONMENT` | `production` | Environment mode (`production`, `development`, `test`) |
| `API_HOST` | `0.0.0.0` | Host IP address binding for Uvicorn |
| `API_PORT` | `8000` | Port for FastAPI backend service |
| `LOG_LEVEL` | `INFO` | Application log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `NEXUS_CORS_ORIGINS` | `http://localhost:3000,...` | Whitelisted frontend origins (comma-separated or `*`) |
| `GRAFANA_ADMIN_USER` | `admin` | Initial Grafana administrator username |
| `GRAFANA_ADMIN_PASSWORD` | *(Required)* | Strong Grafana admin password |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Frontend configuration: backend REST API base URL |
| `VITE_WS_URL` | `ws://localhost:8000/ws/live` | Frontend configuration: backend live WebSocket URL |

### 5.3 Automated Multi-Container Docker Setup
The fastest and most reliable path to run the complete platform is via Docker Compose:

```bash
# 1. Clone repository
git clone https://github.com/shreysherikar/Nexus.git
cd Nexus/nexus-network-intelligence

# 2. Configure environment
cp .env.example .env
# Edit .env and supply secure POSTGRES_PASSWORD and GRAFANA_ADMIN_PASSWORD

# 3. Build and launch all 5 containers in background
docker compose up -d --build

# 4. Verify container health status (wait for 5/5 healthy)
docker compose ps
```

Service Access Points:
- **NOC Web Console**: `http://localhost:3000`
- **FastAPI REST API & Docs**: `http://localhost:8000/docs`
- **Grafana Dashboards**: `http://localhost:3001` (Credentials: `admin` / your password)
- **Prometheus TSDB**: `http://localhost:9090`
- **PostgreSQL Database**: `127.0.0.1:5432` (`nexus_db`)

### 5.4 Local Development Setup (Without Docker)

#### Backend Setup
```bash
cd nexus-network-intelligence

# 1. Create and activate virtual environment
python -m venv .venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1

# 2. Upgrade pip and install package with editable test dependencies
pip install --upgrade pip
pip install -e ".[test]"

# 3. Configure local development mode (uses SQLite)
export ENVIRONMENT=development
export NEXUS_DEV_MODE=true

# 4. Run database migrations (or allow SQLite auto-creation)
alembic upgrade head

# 5. Launch backend development server with hot reload
uvicorn nexus.main:app --host 127.0.0.1 --port 8000 --reload
```

#### Frontend Setup
```bash
cd nexus-network-intelligence/frontend

# 1. Enable Corepack and prepare pinned pnpm
corepack enable
corepack prepare pnpm@9.15.4 --activate

# 2. Install dependencies with frozen lockfile
pnpm install --frozen-lockfile

# 3. Launch Vite development server
pnpm run dev
# The console will be accessible at http://localhost:5173
```

### 5.5 Production Frontend Build
```bash
cd nexus-network-intelligence/frontend
pnpm run typecheck
pnpm run build
# Compiles production distribution bundle into frontend/dist/
```

### 5.6 Executing Test Suites

#### Backend Regression Suite (597 Tests)
```bash
cd nexus-network-intelligence
pytest -v --tb=short
# Expected outcome: 597 passed, 0 skipped, 0 failed (against compose PostgreSQL; 595 passed, 2 skipped, 0 failed against local SQLite)
```

#### Frontend Vitest Suite (69 Tests)
```bash
cd nexus-network-intelligence/frontend
pnpm run test
# Expected outcome: 6 test files passed, 69 tests passed, 0 failed
```

#### End-to-End Acceptance Verification Harness
```bash
cd nexus-network-intelligence
python scripts/verify_e2e_acceptance.py
# Runs 25 comprehensive live runtime checks; duration ~20s; exit code 0
```

### 5.7 Common Installation Errors & Troubleshooting

| Error Message / Symptom | Root Cause | Immediate Resolution |
|:---|:---|:---|
| `POSTGRES_PASSWORD environment variable must be set` | `.env` file missing or empty password | Supply a non-empty password in `.env` before running `docker compose up`. |
| `FATAL: database "nexus_db" does not exist` | Database container not yet initialized | `docker-entrypoint.sh` automatically waits for PG connectivity and executes `alembic upgrade head`. Check container logs with `docker compose logs backend`. |
| `RuntimeError: Database 'postgresql' schema is not migrated` | Application started without running Alembic migrations | Execute `alembic upgrade head` on the command line or restart the container to invoke `docker-entrypoint.sh`. |
| `WebSocket connection to 'ws://...' failed` | Port 8000 unreachable or blocked by CORS | Ensure backend container is healthy (`docker compose ps`). Check that your browser origin matches `NEXUS_CORS_ORIGINS`. |
| `Cannot find module 'pnpm'` | Corepack not enabled in Node environment | Run `corepack enable && corepack prepare pnpm@9.15.4 --activate`. |

---

# PART II — SYSTEM ARCHITECTURE

## 6. High-Level Architecture

NEXUS employs a service-oriented modular monolithic architecture. Backend subsystems communicate through strongly typed domain contracts, exposing RESTful HTTP endpoints and real-time WebSocket event streams to web clients and Prometheus metrics collectors.

### 6.1 Architectural Overview Diagram
```mermaid
flowchart TD
    subgraph Client_Observability ["Client & Observability Layer"]
        SPA["NOC Web Console<br/>(React 18 / TypeScript / Vite)"]
        PROM["Prometheus TSDB<br/>(v2.51.0)"]
        GRAF["Grafana Dashboards<br/>(v10.4.0)"]
        GRAF -->|"PromQL"| PROM
    end

    subgraph Ingress_Layer ["Ingress & Web Server"]
        NGINX["Nginx Alpine Gateway<br/>(Port 80)"]
        SPA -.->|"Bundled Assets"| NGINX
        FASTAPI["FastAPI ASGI Application<br/>(Uvicorn / Port 8000)"]
        NGINX -->|"/api & /ws Reverse Proxy"| FASTAPI
        PROM -->|"Scrape GET /metrics"| FASTAPI
    end

    subgraph Core_Engines ["Diagnostic & Orchestration Pipeline"]
        PIPE["Telemetry Pipeline<br/>(nexus.telemetry.orchestrator)"]
        SIM["Telemetry Generator<br/>(nexus.telemetry.generator)"]
        FAULT["Fault Engine<br/>(nexus.fault.engine)"]
        STORE["Telemetry Store<br/>(In-Memory Sliding Buffer)"]
        DET["Anomaly Detection Engine<br/>(Thresholds, MAD, EWMA)"]
        ALARM["Alarm Manager<br/>(Deduplication & State Machine)"]
        CORR["Alarm Correlation Engine<br/>(Topology-Aware LCA)"]
        RCA["Root Cause Analysis Engine<br/>(Multi-Hypothesis Scoring)"]
        INC_SVC["Incident Domain Service<br/>(nexus.incidents.service)"]
        BCAST["Event Broadcaster<br/>(nexus.events.broadcaster)"]
    end

    subgraph Data_Storage ["Persistent Storage Layer"]
        PG[(PostgreSQL 15<br/>nexus_db / SQLAlchemy 2.x)]
    end

    %% Flow Tracing
    PIPE --> SIM --> FAULT --> STORE
    STORE --> DET --> ALARM --> CORR --> RCA --> INC_SVC --> PG
    STORE --> BCAST
    ALARM --> BCAST
    INC_SVC --> BCAST
    BCAST -->|"WebSocket /ws/live"| FASTAPI
    FASTAPI --> SPA
    FASTAPI -->|"REST API /api/v1"| SPA
```

### 6.2 Subsystem Communication Contracts
- **Simulation Layer**: Produces immutable `KPISnapshot` instances, passing them to the in-memory store and fault engine.
- **Diagnostic Layer**: Reads snapshots from memory, flags `AnomalyEvent` items, manages `Alarm` transitions, clusters alarms into `CorrelationGroup` instances, and evaluates `RCAResult` diagnoses.
- **Operational Persistence**: Converts `RCAResult` records into transactional `Incident` models in PostgreSQL, calculating SLA deadlines and recording timeline audit logs.
- **Event Dispatch**: Dispatches canonical `LiveEvent` envelopes across threads to connected WebSocket subscriber queues.

---

## 7. Backend Architecture

### 7.1 Application Initialization & Lifespan Context
Backend startup and shutdown are managed by FastAPI's asynchronous `lifespan` context manager in `src/nexus/main.py`:

```python
@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    broadcaster = get_broadcaster()
    topo = get_topology_registry()
    store = get_telemetry_store()
    store.set_event_publisher(broadcaster.publish)
    store.set_topology(topo)

    alarm_service = get_alarm_service()
    alarm_service.set_event_publisher(broadcaster.publish)

    fault_service = get_fault_service()
    fault_service.set_event_publisher(broadcaster.publish)

    # Initialize telemetry pipeline without auto-triggering background loops
    get_telemetry_pipeline()

    # Register topology status change listener
    def on_topology_status_change(node_id: str, old_status: NodeStatus, new_status: NodeStatus, ts: datetime):
        broadcaster.publish("TOPOLOGY_STATUS_CHANGED", {
            "node_id": node_id,
            "previous_status": old_status.value,
            "new_status": new_status.value,
            "timestamp": ts.isoformat(),
        }, timestamp=ts)

    topo.add_status_listener(on_topology_status_change)
    yield
    topo.remove_status_listener(on_topology_status_change)
```

### 7.2 Routing Hierarchy & Prefix Layout
Routers are declared with modular responsibility and mounted in `main.py`:
- `incidents_router` (`/api/v1`): Incident CRUD, transitions, SLA metrics, audit timeline.
- `topology_router` (`/api/v1`): Topology nodes, hierarchy inspection, node status.
- `telemetry_router` (`/api/v1`): Telemetry snapshot query and single-step generation trigger.
- `alarm_router` (`/api/v1`): Active alarms, cleared history, detection rules.
- `fault_router` (`/api/v1/faults`): Reference scenario catalog, activation, deactivation.
- `websocket_router` (`/ws`): WebSocket endpoint `/ws/live`.
- System probes: `/`, `/health`, `/ready`, `/metrics`, `/sw.js`.

### 7.3 Middleware Pipeline
1. **CORS Middleware (`CORSMiddleware`)**: Whitelists configured frontend origins (`NEXUS_CORS_ORIGINS`), allowing credentials, standard methods, and custom headers.
2. **Anti-Caching Header Middleware**: Automatically injects `Cache-Control: no-cache, no-store, must-revalidate, max-age=0` on all `/api/*` routes.
3. **Prometheus HTTP Request Instrumentation**: Tracks request count and latency histograms across method, status code, and normalized route path templates (excluding `/metrics` to avoid self-distortion).

### 7.4 Exception Handling Strategy
Custom domain exceptions map to explicit HTTP status codes via FastAPI exception handlers:
- `IncidentNotFoundError` $\to$ HTTP 404 (`INCIDENT_NOT_FOUND`)
- `DuplicateIncidentError` $\to$ HTTP 409 (`DUPLICATE_INCIDENT`)
- `InvalidStateTransitionError` $\to$ HTTP 400 (`INVALID_STATE_TRANSITION`)
- `InvalidIncidentDataError` $\to$ HTTP 422 (`INVALID_INCIDENT_DATA`)
- `NodeNotFoundError` $\to$ HTTP 404 (`NODE_NOT_FOUND`)

### 7.5 Database Session & Transaction Lifecycle
Database sessions are created per-operation using SQLAlchemy `sessionmaker(bind=engine, expire_on_commit=False)`:
- In `IncidentRepository`, database writes (`create()`, `update()`) use contextual blocks:
  ```python
  with self._session_factory() as session:
      try:
          session.add(model)
          session.commit()
          session.refresh(model)
      except IntegrityError as exc:
          session.rollback()
          raise DuplicateIncidentError(group_id) from exc
  ```
- Guarantees transaction atomicity: failure during incident creation rolls back both the incident row and associated timeline events.

---

## 8. Frontend Architecture

### 8.1 Application Shell & Navigation
The frontend single-page application is built with React 18, TypeScript, and Vite. The layout shell (`AppShell.tsx`) provides:
- Collapsible dark-mode navigation sidebar (`Sidebar.tsx`) with real-time status indicators.
- Top bar (`TopBar.tsx`) displaying system health status, active fault scenario pills, and WebSocket connection badges (`CONNECTED`, `RECONNECTING`, `DISCONNECTED`).
- Client-side routing managed by `react-router-dom`:
  - `/overview`: High-level operational summary, health cards, active alarms, recent incidents.
  - `/network-map`: Hierarchical interactive network topology visualization.
  - `/kpis`: Telemetry metric streams, charts, and simulation step generation control.
  - `/alarms`: Active alarm table, severity filters, and manual incident promotion.
  - `/incidents`: Incident ticket management, SLA countdowns, acknowledge/resolve actions.
  - `/analytics`: Historical SLA compliance, MTTA/MTTR/MTTD distribution charts.

### 8.2 Typed REST API Client (`src/api/client.ts`)
- Features configurable base URLs via `VITE_API_BASE_URL`.
- Enforces request timeouts (default: 15,000ms) with `AbortController` cancellation.
- Throws typed `ApiError` instances containing HTTP status codes, error codes, and server details.
- Guarantees non-cached requests using `cache: 'no-store'`.

### 8.3 Native WebSocket Client (`src/websocket/client.ts`)
- Implements connection lifecycle states: `CONNECTING`, `CONNECTED`, `DISCONNECTED`, `RECONNECTING`.
- Supports exponential backoff reconnection (initial interval: 1,000ms; decay: 1.5; ceiling: 30,000ms; max attempts: 20).
- Dynamically resolves relative paths (e.g. `/ws/live`) to native `ws://` or `wss://` based on `window.location`.
- Provides custom React hook `useWebSocketSubscription(eventType, handler)` allowing pages to bind to specific event types and auto-unregister on unmount.

---

## 9. Database Architecture

### 9.1 Schema Design & Relational Tables
NEXUS persists incident state and audit history across two normalized tables in PostgreSQL:

```mermaid
erDiagram
    incidents ||--o{ incident_timeline_events : "fk_incident_id (CASCADE)"

    incidents {
        VARCHAR(64) incident_id PK
        VARCHAR(128) correlation_group_id UK
        VARCHAR(32) status
        VARCHAR(32) severity
        VARCHAR(16) priority
        VARCHAR(256) title
        TEXT description
        JSON alarm_ids
        JSON affected_node_ids
        VARCHAR(64) suspected_cause_type
        VARCHAR(128) suspected_target_id
        VARCHAR(32) suspected_target_type
        FLOAT rca_confidence_score
        JSON rca_hypotheses
        JSON rca_evidence
        TIMESTAMP_TZ created_at
        TIMESTAMP_TZ ack_deadline
        TIMESTAMP_TZ resolve_deadline
        TIMESTAMP_TZ acknowledged_at
        VARCHAR(128) acknowledged_by
        TIMESTAMP_TZ resolved_at
        VARCHAR(128) resolved_by
    }

    incident_timeline_events {
        VARCHAR(64) event_id PK
        VARCHAR(64) incident_id FK
        VARCHAR(32) event_type
        TIMESTAMP_TZ timestamp
        VARCHAR(128) actor
        VARCHAR(32) actor_type
        JSON details
    }
```

### 9.2 Table Specifications

#### Table: `incidents`
- **`incident_id`** (`VARCHAR(64)`, Primary Key): Unique identifier formatted as `INC-<uuid4.hex[:12]>`.
- **`correlation_group_id`** (`VARCHAR(128)`, Unique, Indexed): Identifier of the originating correlation cluster. Enforces database-level ticket deduplication.
- **`status`** (`VARCHAR(32)`, Indexed, Not Null): Lifecycle status (`OPEN`, `ACKNOWLEDGED`, `RESOLVED`).
- **`severity`** (`VARCHAR(32)`, Indexed, Not Null): Operational severity (`CRITICAL`, `MAJOR`, `WARNING`, `MINOR`).
- **`priority`** (`VARCHAR(16)`, Not Null): Operational dispatch priority (`P1`, `P2`, `P3`, `P4`).
- **`title`** (`VARCHAR(256)`, Not Null): Human-readable operational headline.
- **`description`** (`TEXT`, Not Null): Diagnostic summary and evidence reasoning.
- **`alarm_ids`** (`JSON`, Not Null): Array of string alarm identifiers associated with this incident.
- **`affected_node_ids`** (`JSON`, Not Null): Array of impacted topology node IDs.
- **`suspected_cause_type`** (`VARCHAR(64)`, Nullable): Diagnosed root cause classification string.
- **`suspected_target_id`** (`VARCHAR(128)`, Nullable): Suspect entity identifier (e.g. `CELL-01`, `LINK-AGG-01-SITE-01`).
- **`suspected_target_type`** (`VARCHAR(32)`, Nullable): `NODE`, `TRANSPORT_LINK`, or `UNKNOWN`.
- **`rca_confidence_score`** (`FLOAT`, Nullable): Diagnostic confidence score in $[0.0, 1.0]$.
- **`rca_hypotheses`** (`JSON`, Not Null): Array of ranked hypothesis dictionaries.
- **`rca_evidence`** (`JSON`, Not Null): Array of attributed evidence item dictionaries.
- **`created_at`** (`TIMESTAMP WITH TIME ZONE`, Indexed, Not Null): Creation timestamp UTC.
- **`ack_deadline`** (`TIMESTAMP WITH TIME ZONE`, Not Null): Absolute acknowledgement deadline UTC.
- **`resolve_deadline`** (`TIMESTAMP WITH TIME ZONE`, Not Null): Absolute resolution deadline UTC.
- **`acknowledged_at`** (`TIMESTAMP WITH TIME ZONE`, Nullable): Timestamp of operator acknowledgement UTC.
- **`acknowledged_by`** (`VARCHAR(128)`, Nullable): Username or agent identifier who acknowledged the ticket.
- **`resolved_at`** (`TIMESTAMP WITH TIME ZONE`, Nullable): Timestamp of resolution UTC.
- **`resolved_by`** (`VARCHAR(128)`, Nullable): Username or agent identifier who resolved the ticket.

#### Table: `incident_timeline_events`
- **`event_id`** (`VARCHAR(64)`, Primary Key): Unique event identifier formatted as `EVT-<uuid4.hex[:12]>`.
- **`incident_id`** (`VARCHAR(64)`, Foreign Key to `incidents.incident_id`, Indexed, On Delete Cascade, Not Null): Parent incident.
- **`event_type`** (`VARCHAR(32)`, Indexed, Not Null): `CREATED`, `ACKNOWLEDGED`, `RESOLVED`, `NOTE_ADDED`.
- **`timestamp`** (`TIMESTAMP WITH TIME ZONE`, Indexed, Not Null): Event occurrence timestamp UTC.
- **`actor`** (`VARCHAR(128)`, Not Null): Username or service identifier attributing the action.
- **`actor_type`** (`VARCHAR(32)`, Not Null): `SYSTEM`, `OPERATOR`, `AUTOMATION`.
- **`details`** (`JSON`, Not Null): Structured contextual payload describing the mutation.

### 9.3 Alembic Migration History
- **Initial Migration**: `0001_initial_incident_schema.py`
  - Creates tables `incidents` and `incident_timeline_events`.
  - Establishes primary key, foreign key, and unique constraints.
  - Builds performance indexes on `correlation_group_id`, `status`, `severity`, `created_at`, `incident_id`, `event_type`, and `timestamp`.
  - Supports clean bidirectional execution (`upgrade()` and `downgrade()`).

---

# PART III — CORE ENGINEERING MODULES

## 10. Network Topology & Transport Engine

### 10.1 Topological Graph Representation
The network graph is modeled as a strictly hierarchical directed tree $G = (V, E)$ rooted at the central regional core router, where:
- $V = \{v_1, v_2, \dots, v_{27}\}$ represents the 27 physical and logical network nodes.
- $E = \{(u, v) \in V \times V : u = \text{parent}(v)\}$ represents the 26 directed hierarchical dependencies.

```
                    CORE-01 (Tier 1: Regional Hub)
                   /       \
             AGG-01         AGG-02 (Tier 2: Distribution Routers)
            /   |   \      /   |   \
        S-01  S-02  S-03 S-04 S-05 S-06 (Tier 3: Facility Base Station Sites)
       / | \ / | \ / | \ / | \ / | \ / | \
       CELL-01 .. 03      CELL-10 .. 12   (Tier 4: Radio Sector Access Cells)
```

### 10.2 Mathematical Tier Partitioning
The node set $V$ is partitioned into four disjoint subsets:
$$V = V_{\text{CORE}} \cup V_{\text{AGG}} \cup V_{\text{SITE}} \cup V_{\text{CELL}}$$
where:
$$|V_{\text{CORE}}| = 1, \quad |V_{\text{AGG}}| = 2, \quad |V_{\text{SITE}}| = 6, \quad |V_{\text{CELL}}| = 18 \implies |V| = 27$$

Hierarchical tier constraints enforce that for every directed edge $(u, v) \in E$:
$$\text{tier}(u) = \text{tier}(v) - 1$$
Specifically:
- If $v \in V_{\text{AGG}}$, then $u \in V_{\text{CORE}}$ ($u = \text{CORE-01}$).
- If $v \in V_{\text{SITE}}$, then $u \in V_{\text{AGG}}$ ($u \in \{\text{AGG-01}, \text{AGG-02}\}$).
- If $v \in V_{\text{CELL}}$, then $u \in V_{\text{SITE}}$ ($u \in \{\text{SITE-01}, \dots, \text{SITE-06}\}$).

### 10.3 Transport Link Graph
Physical connectivity is represented by the transport link set $L = \{l_1, l_2, \dots, l_{26}\}$ managed by `TransportNetwork` (`src/nexus/transport/network.py`):
- Each link $l_k$ models an upstream endpoint $u$, downstream endpoint $v$, capacity in Mbps, and propagation latency in milliseconds:
  $$l_k = \langle \text{link\_id}, u, v, C_{\text{mbps}}, D_{\text{ms}}, \text{status} \rangle$$
- **Core-to-Aggregation (2 links)**: Capacity $C = 10,000\text{ Mbps}$, Latency $D = 1.5\text{ ms}$.
- **Aggregation-to-Site (6 links)**: Capacity $C = 2,500\text{ Mbps}$, Latency $D = 5.0\text{ ms}$.
- **Site-to-Cell (18 links)**: Capacity $C = 1,000\text{ Mbps}$, Latency $D = 1.0\text{ ms}$.

### 10.4 Graph Traversal & Lineage Construction
Lineage retrieval bottom-up from node $v$ to root is computed in $O(H)$ time where $H \le 4$ is the tree height:
$$\text{lineage}(v) = [v_0 = v, v_1 = \text{parent}(v_0), \dots, v_k = \text{CORE-01}]$$

---

## 11. Telemetry Simulation Engine

### 11.1 Multivariate KPI Snapshot Model
At each discrete simulation step $t$, the state of node $v$ is captured as an immutable composite snapshot:
$$\text{KPISnapshot}(v, t) = \langle \text{node\_id}, t, \text{Performance}, \text{Reliability}, \text{Radio} \rangle$$
where:
1. **Performance**: $\text{throughput\_mbps} \in [0, \infty)$, $\text{latency\_ms} \in [0, \infty)$.
2. **Reliability**: $\text{connection\_drop\_rate\_pct} \in [0, 100]$, $\text{availability\_pct} \in [0, 100]$, $\text{handover\_success\_rate\_pct} \in [0, 100]$.
3. **Radio** (present exclusively for $v \in V_{\text{CELL}}$):
   - $\text{RSRP} \in [-150, -30]\text{ dBm}$ (Reference Signal Received Power)
   - $\text{SINR} \in [-30, 50]\text{ dB}$ (Signal-to-Interference-plus-Noise Ratio)
   - $\text{PRB} \in [0, 100]\%$ (Physical Resource Block Utilization)

### 11.2 Baseline Synthesis & Exponential Smoothing
For each metric $M$, the generator samples a target innovation from a bounded Gaussian distribution parameterized by the configured `NodeOperatingProfile`:
$$X_{\text{raw}} \sim \mathcal{N}\left(\mu = \text{nominal}, \sigma = \frac{\max - \min}{6}\right)$$
$$X_{\text{target}} = \text{clamp}(X_{\text{raw}}, \min, \max)$$

To guarantee temporal continuity between successive discrete steps, first-order exponential smoothing with smoothing factor $\alpha = 0.65$ is applied:
$$S_t(M) = \alpha \cdot S_{t-1}(M) + (1 - \alpha) \cdot X_{\text{target}}$$
where $S_t(M)$ is the smoothed value recorded for metric $M$ at step $t$.

### 11.3 Cross-Metric Dependency Formulations
For cellular radio sectors ($v \in V_{\text{CELL}}$), physical RF interactions modulate performance:
1. **Channel Quality Factor ($\gamma_{\text{SINR}}$)**:
   Maps SINR across the standard cellular operational span $[-10.0\text{ dB}, 30.0\text{ dB}]$:
   $$\gamma_{\text{SINR}} = \text{clamp}\left(\frac{\text{SINR} - (-10.0)}{40.0}, 0.0, 1.0\right)$$
2. **PRB Congestion Attenuation ($\phi_{\text{PRB}}$)**:
   High resource utilization reduces available throughput headroom:
   $$\phi_{\text{PRB}} = 1.0 - 0.3 \cdot \left(\frac{\text{PRB}}{100.0}\right) \in [0.7, 1.0]$$
3. **Target Cell Throughput**:
   $$T_{\text{target}} = T_{\min} + (T_{\max} - T_{\min}) \cdot (0.3 + 0.7 \cdot \gamma_{\text{SINR}}) \cdot \phi_{\text{PRB}} + \epsilon_{\text{noise}}$$
   where $\epsilon_{\text{noise}} \sim \mathcal{U}(-5.0, 5.0)\text{ Mbps}$.
4. **Target Queueing Latency**:
   $$D_{\text{target}} = D_{\min} + (D_{\max} - D_{\min}) \cdot \left(0.2 + 0.8 \cdot \frac{\text{PRB}}{100.0}\right) + \epsilon_{\text{lat}}$$
   where $\epsilon_{\text{lat}} \sim \mathcal{U}(-0.5, 0.5)\text{ ms}$.

---

## 12. Anomaly Detection Engine

NEXUS implements dual decoupled anomaly detection pipelines: static threshold rules with hysteresis anti-flapping controls alongside dual rolling statistical baselines (Median/MAD and EWMA).

### 12.1 Static Threshold Detection & Hysteresis

#### Mathematical Principle
A metric observation $x_t$ triggers an anomaly if relational condition $x_t \odot \theta_{\text{trigger}}$ holds, where $\odot \in \{>, \ge, <, \le\}$.

To eliminate alarm flapping when noisy metric signals oscillate near the threshold boundary, an explicit hysteresis recovery threshold $\theta_{\text{clear}}$ is enforced:
- **Upper-Bound Trigger ($\odot \in \{>, \ge\}$)**:
  $$\text{Trigger Condition}: x_t > \theta_{\text{trigger}}$$
  $$\text{Recovery Condition}: x_t \le \theta_{\text{clear}} \quad \text{where } \theta_{\text{clear}} \le \theta_{\text{trigger}}$$
- **Lower-Bound Trigger ($\odot \in \{<, \le\}$)**:
  $$\text{Trigger Condition}: x_t < \theta_{\text{trigger}}$$
  $$\text{Recovery Condition}: x_t \ge \theta_{\text{clear}} \quad \text{where } \theta_{\text{clear}} \ge \theta_{\text{trigger}}$$

#### Configured Baseline Rules
| Rule Identifier | Target KPI Metric | Operator | Trigger Threshold ($\theta_{\text{trigger}}$) | Clear Threshold ($\theta_{\text{clear}}$) | Target Tier | Assigned Severity |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| `RULE-AVAIL-CRIT` | `availability_pct` | `<` | $95.0\%$ | $98.0\%$ | ALL | `CRITICAL` |
| `RULE-DROP-CRIT` | `connection_drop_rate_pct` | `>` | $5.0\%$ | $2.0\%$ | ALL | `CRITICAL` |
| `RULE-LAT-MAJOR` | `latency_ms` | `>` | $80.0\text{ ms}$ | $60.0\text{ ms}$ | ALL | `MAJOR` |
| `RULE-PRB-MAJOR` | `prb_utilization_pct` | `>` | $85.0\%$ | $75.0\%$ | `CELL` | `MAJOR` |
| `RULE-SINR-MAJOR` | `sinr_db` | `<` | $5.0\text{ dB}$ | $8.0\text{ dB}$ | `CELL` | `MAJOR` |
| `RULE-RSRP-WARN` | `rsrp_dbm` | `<` | $-115.0\text{ dBm}$ | $-110.0\text{ dBm}$ | `CELL` | `WARNING` |
| `RULE-TP-WARN` | `throughput_mbps` | `<` | $5.0\text{ Mbps}$ | $10.0\text{ Mbps}$ | `CELL` | `WARNING` |
| `RULE-HOSR-MAJOR` | `handover_success_rate_pct` | `<` | $90.0\%$ | $95.0\%$ | `CELL` | `MAJOR` |

### 12.2 Rolling Median & Median Absolute Deviation (MAD)

#### Mathematical Foundation
Given a sliding historical window $W = \{x_{t-k}, \dots, x_{t-1}\}$ of clean observations ($|W| \le 20$):
1. **Window Median**:
   $$\tilde{\mu} = \text{median}(W)$$
2. **Median Absolute Deviation (MAD)**:
   $$\text{MAD} = \text{median}\left(\{|x - \tilde{\mu}| : x \in W\}\right)$$
3. **Normal-Consistent Scale Estimator**:
   For normally distributed data, $\mathbb{E}[1.4826 \cdot \text{MAD}] = \sigma$. Thus:
   $$\hat{\sigma}_{\text{raw}} = 1.4826 \cdot \text{MAD}$$
4. **Profile-Spread Scale Floor**:
   To prevent division-by-zero or hypersensitivity during steady-state low-variance conditions, the effective scale floor incorporates the physical metric range spread:
   $$\sigma_{\text{profile\_spread}} = \frac{\text{profile.range\_max} - \text{profile.range\_min}}{6.0}$$
   $$\sigma_{\text{floor}} = \max\left(\sigma_{\text{profile\_spread}}, 0.05 \cdot \max(|\tilde{\mu}|, 1.0)\right)$$
   $$\hat{\sigma}_{\text{effective}} = \max(\hat{\sigma}_{\text{raw}}, \sigma_{\text{floor}})$$
5. **Robust Deviation Score**:
   $$Z_{\text{MAD}} = \frac{|x_t - \tilde{\mu}|}{\hat{\sigma}_{\text{effective}}}$$
   An anomaly is flagged if $Z_{\text{MAD}} \ge \tau_{\text{median}}$ (default: $\tau_{\text{median}} = 3.0$), subject to directional KPI filtering.

### 12.3 Recursive Exponentially Weighted Moving Average (EWMA)

#### Mathematical Foundation
Let $\mu_t$ and $\sigma_t^2$ denote the estimated mean and variance at step $t$ with smoothing weight $\alpha = 0.2$:
1. **Residual Deviation**:
   $$\delta_t = x_t - \mu_{t-1}$$
2. **Effective Spread with Profile-Spread Floor**:
   $$\sigma_{\text{raw}} = \sqrt{\max(0.0, \sigma_{t-1}^2)}$$
   $$\sigma_{\text{floor}} = \max\left(\frac{\text{profile.range\_max} - \text{profile.range\_min}}{6.0}, 0.05 \cdot \max(|\mu_{t-1}|, 1.0)\right)$$
   $$\sigma_{\text{effective}} = \max(\sigma_{\text{raw}}, \sigma_{\text{floor}})$$
3. **EWMA Deviation Score**:
   $$Z_{\text{EWMA}} = \frac{|\delta_t|}{\sigma_{\text{effective}}}$$
   An anomaly is flagged if $Z_{\text{EWMA}} \ge \tau_{\text{EWMA}}$ (default: $\tau_{\text{EWMA}} = 3.0$), subject to directional KPI filtering.
4. **Recursive Baseline Update (Clean Samples Only)**:
   $$\mu_t = \alpha \cdot x_t + (1 - \alpha) \cdot \mu_{t-1}$$
   $$\sigma_t^2 = \alpha \cdot \delta_t^2 + (1 - \alpha) \cdot \sigma_{t-1}^2$$

### 12.4 Evaluate-Then-Commit Contamination Prevention Policy
If either the Rolling Median or EWMA detector flags an observation $x_t$ as an anomaly, $x_t$ is **strictly excluded from updating both baseline states**. The sample is discarded from the median deque and EWMA recursive state, guaranteeing that severe faults cannot pull expected baselines toward failure values.

### 12.5 Directional KPI Operational Filtering
Standard symmetric anomaly detectors flag any deviation from baseline ($|x - \mu| > \tau$), which creates severe false positives in telecommunications when service metrics *improve* (e.g. latency drops or throughput increases). NEXUS categorizes KPIs into operational health directions:
- **`HIGHER_IS_BETTER_KPIS`** (`availability_pct`, `throughput_mbps`, `sinr_db`, `rsrp_dbm`, `handover_success_rate_pct`): Only negative deviations ($x_t < \mu$) represent impairments. Favorable increases ($x_t > \mu$) are suppressed unless throughput exceeds the surge ratio threshold.
- **`LOWER_IS_BETTER_KPIS`** (`latency_ms`, `packet_loss_pct`, `connection_drop_rate_pct`): Only positive deviations ($x_t > \mu$) represent impairments. Beneficial reductions ($x_t < \mu$) are suppressed.
- **`RESOURCE_UTILIZATION_KPIS`** (`prb_utilization_pct`, `cpu_utilization_pct`): Monitored bidirectionally for congestion exhaustion or abnormal idle collapse.

### 12.6 Throughput Surge Ratio Threshold
To accommodate legitimate high-demand user bursts without false alarming, throughput increases above baseline are governed by `surge_ratio_threshold` (default: $2.0\times$):
$$\text{Surge Condition}: x_{\text{throughput}} \ge \text{surge\_ratio\_threshold} \cdot \mu_{\text{nominal}}$$
Increases below $2.0\times$ are treated as normal cellular traffic variations and suppressed from raising alarm tickets.

### 12.7 Profile Baseline Pre-Seeding
To eliminate detection latency and cold-start vulnerabilities during container spin-up, `seed_from_profile()` and `seed_baselines()` populate the rolling median deque and EWMA states from `DEFAULT_PROFILES` during `TelemetryPipeline` initialization. This ensures full anomaly detection sensitivity on step 1 without requiring 20 steps of warmup traffic.

### 12.8 Two-Sample Recovery Hysteresis
To prevent alarm flapping caused by noisy intermediate samples during service recovery, statistical detectors require two consecutive clean observations (`consecutive_recovery_count = 2`) before an active statistical alarm transitions to `CLEARED`:
- When an active alarm experiences a step where no anomaly is flagged, its recovery counter increments to 1.
- If the subsequent step is also clean, the recovery counter reaches 2 and the alarm is cleared.
- If an anomalous or degraded observation occurs while the counter is 1, the counter is immediately reset to 0, ensuring that intermittent flapping cannot prematurely dismiss an unresolved incident.

---

## 13. Alarm Generation and Management

### 13.1 Deduplication Key Architecture
Alarms are uniquely indexed by the immutable 4-tuple:
$$\text{AlarmKey} = \langle \text{node\_id}, \text{metric\_name}, \text{rule\_id}, \text{source} \rangle$$
where $\text{source} \in \{\text{THRESHOLD}, \text{STATISTICAL\_MEDIAN}, \text{STATISTICAL\_EWMA}\}$.

### 13.2 State Machine & Transition Invariants
```mermaid
stateDiagram-v2
    [*] --> ACTIVE : New Breach (process_anomaly)\nAssign Unique ALARM-ID\nobservation_count = 1\nfirst_seen = last_seen = now
    ACTIVE --> ACTIVE : Repeated Breach (process_anomaly)\nobservation_count++\nlast_seen = now\ncurrent_value = updated
    ACTIVE --> CLEARED : Recovery Validated (clear_alarm)\ncleared_at = now\nstatus = CLEARED\nMove to cleared_history
    CLEARED --> [*]
```

---

## 14. Topology-Aware Alarm Correlation

### 14.1 The Correlation Imperative
When an upstream transport link or base station facility fails, downstream sectors trigger cascading symptomatic alarms. Naive incident systems treat these as distinct issues. The correlation engine groups these alarms by physical topology dependency.

### 14.2 Lowest Common Ancestor (LCA) Algorithm
For any pair of alarmed nodes $(u, v) \in V \times V$, their lineages to root are constructed:
$$\text{lineage}(u) = [u, p_1(u), p_2(u), \dots, \text{CORE-01}]$$
$$\text{lineage}(v) = [v, p_1(v), p_2(v), \dots, \text{CORE-01}]$$

The Lowest Common Ancestor $\text{LCA}(u, v)$ is the first node appearing in both sequences:
$$\text{LCA}(u, v) = \arg\min_{w \in \text{lineage}(u) \cap \text{lineage}(v)} (\text{dist}(u, w))$$
The hop distances $d_u = \text{dist}(u, \text{LCA})$ and $d_v = \text{dist}(v, \text{LCA})$ represent the hierarchy separation.

### 14.3 Pairwise Correlation Compatibility Conditions
Two alarms $a_1$ and $a_2$ share an undirected edge in the correlation graph if and only if all five predicates hold:
1. **Temporal Proximity**:
   $$|\text{first\_seen}(a_1) - \text{first\_seen}(a_2)| \le \Delta T_{\text{window}} \quad (\text{default: } 300\text{s})$$
2. **Topological Existence**: Both $a_1.\text{node\_id}$ and $a_2.\text{node\_id}$ exist in $G$.
3. **Maximum Hierarchy Distance**:
   $$\max(d_{a_1}, d_{a_2}) \le D_{\max} \quad (\text{default: } 2\text{ hops})$$
4. **Distant Core Protection Policy**:
   If $\text{LCA}(a_1.\text{node\_id}, a_2.\text{node\_id}) = \text{CORE-01}$, an edge is permitted **if and only if** at least one alarm is located directly on $\text{CORE-01}$:
   $$\text{tier}(\text{LCA}) = \text{CORE} \implies (a_1.\text{node\_id} = \text{CORE-01} \lor a_2.\text{node\_id} = \text{CORE-01})$$
   *Rationale*: Prevents unrelated failures in West and East aggregation branches from collapsing into a false global cluster.
5. **Symptom Compatibility**:
   If $a_1.\text{node\_id} \ne a_2.\text{node\_id}$, localized metrics (`sinr_db`, `rsrp_dbm`, `prb_utilization_pct`) are forbidden from correlating across nodes. Only systemic branch metrics (`availability_pct`, `latency_ms`, `throughput_mbps`, `connection_drop_rate_pct`) correlate across parent-child links.

### 14.4 Time-Window Chaining Prevention Policy
When traversing connected components via BFS, an edge is traversed only if adding the candidate alarm maintains the group's total onset span constraint:
$$\max_{a \in \text{group} \cup \{a_{\text{cand}}\}} (\text{first\_seen}(a)) - \min_{a \in \text{group} \cup \{a_{\text{cand}}\}} (\text{first\_seen}(a)) \le \Delta T_{\text{window}}$$
If adding $a_{\text{cand}}$ would violate the span, it is deferred to a subsequent correlation group, preventing infinite transitive chaining.

---

## 15. Root Cause Analysis (RCA) Engine

### 15.1 Diagnostic Principles
The Root Cause Analysis engine (`RootCauseAnalysisEngine` in `src/nexus/rca/engine.py`) evaluates correlation groups against domain diagnostic rules to identify the primary failure hypothesis, isolate the suspect target, compute confidence scores, and provide actionable operational recommendations.

### 15.2 Freshness Reference & Anti-Lookahead Policy
Telemetry snapshot selection enforces strict anti-lookahead invariants:
1. **Reference Timestamp ($t_{\text{ref}}$)**: Freshness is evaluated relative to $t_{\text{ref}} = \text{analysis\_timestamp}$.
2. **Zero Future Lookahead**: Any snapshot with $t > t_{\text{ref}}$ is discarded.
3. **Staleness Boundary**: Snapshots older than $t_{\text{ref}} - \Delta T_{\text{stale}}$ (default: 300s) are rejected as stale.

### 15.3 Diagnostic Rule Evaluators & Scoring Formulations

#### 1. Backhaul Transport Failure (`evaluate_backhaul_failure`)
- **Target Entity**: `TRANSPORT_LINK` (e.g. `LINK-AGG-01-SITE-01`).
- **Signature**: Anchor at `SITE` or `AGGREGATION`; elevated latency ($> 50\text{ ms}$), collapsed throughput ($< 20\text{ Mbps}$), or severe availability loss ($\le 10\%$).
- **Scoring Formula**:
  $$S = S_{\text{lat}} + S_{\text{tp}} + S_{\text{avail}} + S_{\text{child\_cells}} + S_{\text{target\_link}}$$
  - Latency degradation: $+0.25$
  - Throughput collapse: $+0.20$
  - Availability collapse: $+0.10$
  - Multiple child cells degraded ($\ge 2$): $+0.15$
  - Upstream transport link confirmed: $+0.15$
  - Confidence capped at $1.0$.

#### 2. Site Power Failure (`evaluate_site_power_failure`)
- **Target Entity**: `NODE` (at `SITE` tier).
- **Signature**: Complete facility blackout taking down the site and all subordinate cells; availability drops to $0.0\%$, throughput drops to $0.0\text{ Mbps}$, while baseline latency remains unamplified.
- **Scoring Formula**:
  $$S = S_{\text{base}} + S_{\text{avail}} + S_{\text{tp}} + S_{\text{child\_cells}}$$
  - Base facility match: $+0.30$
  - Complete availability loss: $+0.30$
  - Zero throughput: $+0.20$
  - All child cells offline: $+0.15$

#### 3. Radio Interference (`evaluate_radio_interference`)
- **Target Entity**: `NODE` (at `CELL` tier).
- **Signature**: Localized to a single cell sector; severe SINR collapse ($< 5.0\text{ dB}$), elevated connection drop rate ($> 3.0\%$).
- **Scoring Formula**:
  $$S = S_{\text{sinr}} + S_{\text{drop}} + S_{\text{tp}} + S_{\text{isolation}}$$
  - SINR $< 5.0\text{ dB}$: $+0.40$
  - Connection drop $> 3.0\%$: $+0.25$
  - Throughput degraded: $+0.15$
  - Strict single-cell isolation: $+0.15$

#### 4. Cell Congestion (`evaluate_cell_congestion`)
- **Target Entity**: `NODE` (at `CELL` tier).
- **Signature**: Saturated Physical Resource Block utilization ($\text{PRB} \ge 80\%$), elevated scheduling queue latency ($> 60\text{ ms}$), while radio signal (SINR) remains healthy ($\ge 10\text{ dB}$).
- **Scoring Formula**:
  $$S = S_{\text{prb}} + S_{\text{lat}} + S_{\text{sinr\_clean}}$$
  - $\text{PRB} \ge 80\%$: $+0.45$
  - Latency $> 60\text{ ms}$: $+0.30$
  - Healthy SINR floor ($\ge 10\text{ dB}$): $+0.20$

#### 5. Single Cell Outage (`evaluate_cell_outage`)
- **Target Entity**: `NODE` (at `CELL` tier).
- **Signature**: Isolated sector failure; availability drops to $0.0\%$, connection drop rate spikes to $100\%$, while sibling cells on the same site operate normally.
- **Scoring Formula**:
  $$S = S_{\text{avail\_zero}} + S_{\text{drop\_100}} + S_{\text{sibling\_healthy}}$$
  - Availability $= 0.0\%$: $+0.45$
  - Drop rate $= 100\%$: $+0.30$
  - Sibling cells healthy: $+0.20$

#### 6. Core Router Failure (`evaluate_core_router_failure`)
- **Target Entity**: `NODE` (at `CORE` tier, `CORE-01`).
- **Signature**: Systemic regional transit failure; alarms directly on `CORE-01` or spanning multiple independent aggregation hubs.
- **Scoring Formula**:
  $$S = S_{\text{core\_alarm}} + S_{\text{cross\_branch}} + S_{\text{systemic\_lat}}$$
  - Direct `CORE-01` alarm: $+0.50$
  - Both aggregation branches affected: $+0.30$
  - Systemic latency elevation: $+0.15$

### 15.4 Deterministic Ranking & UNKNOWN Fallback
Candidate hypotheses are sorted deterministically:
1. `confidence_score` (Descending)
2. Number of attributed `evidence_items` (Descending)
3. `target_id` (Alphabetical ASC)
4. `cause_type.value` (Alphabetical ASC)

If the top-ranked candidate has $\text{confidence} < 0.30$, or if no candidate is generated, an explicit `UNKNOWN` hypothesis is emitted:
- `cause_type = RootCauseType.UNKNOWN`
- `target_type = TargetType.UNKNOWN`
- `confidence_score = 0.0`
- `recommended_action = "Gather detailed diagnostic traces and assign to Tier-2 operations for triage."`

---

## 16. Incident Management System

### 16.1 Operational Severity & Priority Mapping
Severity is decoupled from diagnostic confidence and driven by network blast radius (`OperationalSeverityPolicy` in `src/nexus/incidents/severity.py`):

| Severity | Dispatch Priority | Criteria & Topological Blast Radius |
|:---:|:---:|:---|
| **CRITICAL** | **P1** | Any `CRITICAL` alarm on `CORE` or `AGGREGATION` tiers, OR any `CRITICAL` alarm impacting $\ge 5$ nodes. |
| **MAJOR** | **P2** | Any `CRITICAL` alarm on access tier (`SITE`, `CELL`), OR any `MAJOR` alarm on backbone (`CORE`, `AGGREGATION`), OR any `MAJOR` alarm impacting $\ge 3$ nodes. |
| **WARNING** | **P3** | Any `MAJOR` alarm on access tier (`SITE`, `CELL`), OR multiple nodes ($\ge 2$) with `WARNING` alarms. |
| **MINOR** | **P4** | Isolated single-node `WARNING` condition. |

### 16.2 SLA Targets & Deadline Freezing
SLA response targets are defined in `src/nexus/incidents/sla.py`:

| Severity | Priority | Acknowledgement Target ($\Delta T_{\text{ack}}$) | Resolution Target ($\Delta T_{\text{res}}$) |
|:---:|:---:|:---:|:---:|
| **CRITICAL** | **P1** | 15 minutes | 60 minutes (1 hour) |
| **MAJOR** | **P2** | 30 minutes | 240 minutes (4 hours) |
| **WARNING** | **P3** | 60 minutes | 720 minutes (12 hours) |
| **MINOR** | **P4** | 120 minutes (2 hours) | 1440 minutes (24 hours) |

#### Deadline Freezing Invariant
Deadlines are computed at creation:
$$t_{\text{ack\_deadline}} = t_{\text{created}} + \Delta T_{\text{ack}}, \quad t_{\text{res\_deadline}} = t_{\text{created}} + \Delta T_{\text{res}}$$
- **While Open**:
  $$\text{ack\_breached} = (t_{\text{now}} > t_{\text{ack\_deadline}})$$
  $$\text{resolve\_breached} = (t_{\text{now}} > t_{\text{res\_deadline}})$$
- **Upon Resolution ($t_{\text{resolved}}$)**:
  Both breach evaluations **permanently freeze**:
  $$\text{ack\_breached} = (t_{\text{acknowledged}} > t_{\text{ack\_deadline}})$$
  $$\text{resolve\_breached} = (t_{\text{resolved}} > t_{\text{res\_deadline}})$$
  Future clock advances cannot cause resolved incidents to breach retroactively.

---

## 17. Real-Time Communication Architecture

### 17.1 WebSocket Concurrency & Ingress Handshake
Clients connect to `WS /ws/live`. The ASGI server performs protocol switching (`HTTP 101`). `live_events_websocket` registers a dedicated bounded queue (`asyncio.Queue(maxsize=100)`) with the `EventBroadcaster`.

### 17.2 Cross-Thread Fan-Out (`EventBroadcaster`)
When backend worker threads (e.g. during incident persistence or simulation steps) publish events, they invoke:
```python
broadcaster.publish("INCIDENT_CREATED", payload)
```
Internally, `EventBroadcaster` bridges synchronous worker threads onto each subscriber's captured `asyncio` event loop using `loop.call_soon_threadsafe()`.

### 17.3 Backpressure & Bounded Memory Policy
If a slow client fails to consume frames and its queue reaches `maxsize=100`:
- The broadcaster executes FIFO backpressure: it pops and discards the oldest unconsumed message (`queue.get_nowait()`), increments `dropped_events_count`, and enqueues the latest frame.
- Guarantees bounded memory and prevents slow consumers from degrading backend publishers or crashing the application with out-of-memory errors.

### 17.4 Outbound Serialization & Starvation Prevention
In `src/nexus/events/api.py`, a dedicated `sender_task` serializes all outbound frames over the socket:
- Concurrent calls to `websocket.send_text()` are strictly prevented.
- Heartbeat PING frames from clients enqueue responses into a separate `pong_queue`.
- To prevent heartbeat floods from starving domain events, a priority counter allows at most **3 consecutive PONGs** before yielding to pending domain events in `event_queue`.

---

## 18. Observability and Monitoring

### 18.1 Prometheus Instrumentation Standards (`nexus.metrics`)
To prevent cardinality explosions in production TSDB instances:
1. **Zero Dynamic Label Values**: Dynamic identifiers (`node_id`, `alarm_id`, `incident_id`), timestamps, and operator notes are strictly forbidden in Prometheus labels.
2. **Normalized Route Templates**: HTTP request metrics use route templates (`/api/v1/incidents/{incident_id}`) rather than concrete paths.
3. **Scrape Isolation**: The `/metrics` endpoint is excluded from HTTP request tracking to eliminate scrape self-distortion.

### 18.2 Exported Prometheus Metric Inventory

#### Application & Health Gauges
- `nexus_app_info{platform="NEXUS", version="1.0.0"}`: Constant 1.0 build metadata.
- `nexus_ready_status`: Overall platform readiness (1.0 = ready, 0.0 = degraded).
- `nexus_component_ready{component="..."}`: Readiness state across 6 subsystems (`topology`, `broadcaster`, `telemetry_store`, `alarm_service`, `fault_service`, `database`).

#### Telemetry Domain Gauges
- `nexus_telemetry_snapshots_total`: Total snapshots currently held in sliding buffer.
- `nexus_telemetry_throughput_mbps_avg{node_tier="..."}`: Average throughput per tier.
- `nexus_telemetry_latency_ms_avg{node_tier="..."}`: Average latency per tier.
- `nexus_telemetry_drop_rate_pct_avg{node_tier="..."}`: Average drop rate per tier.
- `nexus_telemetry_availability_pct_avg{node_tier="..."}`: Average availability per tier.
- `nexus_telemetry_radio_sinr_db_avg`: Average SINR across all active CELL nodes.
- `nexus_telemetry_radio_prb_utilization_pct_avg`: Average PRB utilization across CELL nodes.

#### Alarm Gauges
- `nexus_alarms_active{severity="..."}`: Count of active alarms by severity.
- `nexus_alarms_total{severity="...", status="..."}`: Total alarms by severity and status.

#### Incident & SLA Gauges
- `nexus_incidents_total`: Total incidents in persistent storage.
- `nexus_incidents_active{severity="..."}`: Active unresolved incidents by severity.
- `nexus_incidents_by_status{status="..."}`: Incidents categorized by status.
- `nexus_incidents_by_severity{severity="..."}`: Incidents categorized by severity.
- `nexus_incidents_sla_breaches_total{sla_type="..."}`: SLA breach counts.
- `nexus_incidents_mtta_seconds`: Mean Time to Acknowledge in seconds.
- `nexus_incidents_mttr_seconds`: Mean Time to Resolve in seconds.
- `nexus_incidents_mttd_seconds`: Mean Time to Detect in seconds.
- `nexus_incidents_sla_compliance_pct`: Overall SLA compliance percentage.

#### Fault & Queue Gauges
- `nexus_fault_active{scenario_key="..."}`: 1.0 if scenario active, 0.0 otherwise.
- `nexus_fault_affected_nodes{scenario_key="..."}`: Count of impacted nodes.
- `nexus_broadcaster_subscribers_active`: Active WebSocket connections.
- `nexus_broadcaster_events_dropped_total`: Discarded events due to FIFO backpressure.

### 18.3 Grafana Dashboard Catalog
NEXUS automatically provisions five operational Grafana dashboards (`deploy/grafana/dashboards/`):
1. **`01-platform-overview.json`**: Executive high-level status, node health, active alarm tallies, open incidents, and MTTA/MTTR gauges.
2. **`02-network-kpi-health.json`**: Deep-dive telemetry distributions, throughput/latency by tier, and cell radio SINR/PRB heatmaps.
3. **`03-alarm-incident-overview.json`**: Real-time alarm severity breakdown, active ticket status, and SLA compliance percentages.
4. **`04-fault-simulation.json`**: Scenario activation indicators, blast radius tracking, and simulated degradation curves.
5. **`05-api-infrastructure-health.json`**: FastAPI request throughput (RPS), p50/p95/p99 latency histograms, HTTP status codes, and WebSocket subscriber counts.

---

# PART IV — INTERFACES AND IMPLEMENTATION

## 19. Complete API Reference

NEXUS implements 17 RESTful HTTP endpoints across 6 functional routers. All endpoints adhere to anti-caching standards, uniform JSON response envelopes, and explicit HTTP status codes.

### 19.1 Master REST Endpoint Inventory

| HTTP Method | Route Path | Subsystem | Purpose & Summary | Status Codes |
|:---:|:---|:---|:---|:---:|
| `GET` | `/` | `nexus.main` | Platform metadata, version, and documentation links | 200 |
| `GET` | `/health` | `nexus.main` | Lightweight liveness probe for container orchestrators | 200 |
| `GET` | `/ready` | `nexus.main` | Deep readiness probe verifying all 6 subsystems | 200, 503 |
| `GET` | `/metrics` | `nexus.metrics` | Prometheus metrics exposition in standard text format | 200 |
| `GET` | `/api/v1/topology` | `nexus.topology` | Complete 27-node topology registry and hierarchy tiers | 200 |
| `GET` | `/api/v1/topology/nodes/{node_id}` | `nexus.topology` | Single topology node details and direct children list | 200, 404 |
| `GET` | `/api/v1/telemetry` | `nexus.telemetry` | Query telemetry snapshots with pagination and filters | 200, 422 |
| `POST` | `/api/v1/telemetry/generate-step` | `nexus.telemetry` | Generate one discrete simulation step for all 27 nodes | 200, 409 |
| `GET` | `/api/v1/alarms` | `nexus.detection` | Query active and cleared alarms with filtering | 200, 422 |
| `GET` | `/api/v1/alarms/{alarm_id}` | `nexus.detection` | Single alarm record lookup by unique identifier | 200, 404 |
| `GET` | `/api/v1/detection/rules` | `nexus.detection` | List configured threshold rules and hysteresis bounds | 200 |
| `GET` | `/api/v1/faults/scenarios` | `nexus.fault` | Catalog of 6 reference failure scenarios | 200 |
| `GET` | `/api/v1/faults/active` | `nexus.fault` | Current active fault scenario and affected nodes | 200 |
| `POST` | `/api/v1/faults/scenarios/{id}/activate` | `nexus.fault` | Activate reference fault scenario | 200, 400, 404 |
| `POST` | `/api/v1/faults/scenarios/deactivate` | `nexus.fault` | Deactivate active faults; restore nominal baseline | 200 |
| `GET` | `/api/v1/incidents` | `nexus.incidents` | Query operational incidents with pagination & filters | 200 |
| `POST` | `/api/v1/incidents` | `nexus.incidents` | Create incident ticket from correlation/RCA cluster | 201, 409, 422 |
| `GET` | `/api/v1/incidents/metrics` | `nexus.incidents` | System MTTA, MTTR, MTTD, and SLA compliance metrics | 200 |
| `GET` | `/api/v1/incidents/{incident_id}` | `nexus.incidents` | Retrieve single incident details and SLA status | 200, 404 |
| `POST` | `/api/v1/incidents/{id}/acknowledge` | `nexus.incidents` | Transition incident from OPEN to ACKNOWLEDGED | 200, 400, 404 |
| `POST` | `/api/v1/incidents/{id}/resolve` | `nexus.incidents` | Transition incident to RESOLVED with operator notes | 200, 400, 404 |
| `GET` | `/api/v1/incidents/{id}/timeline` | `nexus.incidents` | Chronological immutable audit history for incident | 200, 404 |

---

## 20. WebSocket Event Reference

All real-time events streamed via `WS /ws/live` share the canonical JSON envelope structure:
```json
{
  "type": "<EVENT_TYPE>",
  "timestamp": "2026-11-23T12:00:00Z",
  "payload": { ... }
}
```

| Event Type Name | Emitting Subsystem | Triggering Condition | Payload Contents | Consumer Impact |
|:---|:---|:---|:---|:---|
| `TELEMETRY_SNAPSHOT` | `nexus.telemetry.store` | A new KPI snapshot is recorded in memory | `node_id`, `timestamp`, `performance`, `reliability`, `radio` | Updates live charts, KPI tables, and node status pills |
| `ALARM_CREATED` | `nexus.detection.service` | An anomaly violation creates a new active alarm | `alarm_id`, `node_id`, `rule_id`, `severity`, `threshold`, `current_value` | Adds alarm row to Alarms page; increments active count |
| `ALARM_UPDATED` | `nexus.detection.service` | An active alarm receives repeated breaches | `alarm_id`, `observation_count`, `last_seen`, `current_value` | Updates last-seen timestamp and count in place |
| `ALARM_CLEARED` | `nexus.detection.service` | Metric recovers past hysteresis threshold | `alarm_id`, `status: "CLEARED"`, `cleared_at` | Moves alarm to cleared tab; decrements active count |
| `INCIDENT_CREATED` | `nexus.incidents.service` | New incident persisted from diagnosed cluster | `incident_id`, `title`, `severity`, `priority`, `status: "OPEN"` | Displays P1/P2 banner; appends row to Incidents page |
| `INCIDENT_ACKNOWLEDGED`| `nexus.incidents.service` | Operator acknowledges incident ticket | `incident_id`, `status: "ACKNOWLEDGED"`, `acknowledged_by` | Changes status badge; freezes acknowledgement SLA |
| `INCIDENT_RESOLVED` | `nexus.incidents.service` | Operator resolves incident ticket | `incident_id`, `status: "RESOLVED"`, `resolved_by`, `resolved_at` | Marks ticket resolved; freezes resolution SLA |
| `TOPOLOGY_STATUS_CHANGED`| `nexus.topology` | Node transitions operational status | `node_id`, `previous_status`, `new_status`, `timestamp` | Rerenders node color on Network Map page |

---

## 21. Frontend Pages and Components

### 21.1 Application Pages

#### 1. Overview Page (`frontend/src/pages/OverviewPage.tsx`)
- **Responsibility**: Executive NOC dashboard presenting critical operational health indicators, active incident tallies, critical alarm counts, and high-level distributions.
- **Components Used**: `PageHeader`, `MetricCard`, `DataTable`, `SeverityBadge`, `StatusBadge`, `BarChartDistribution`, `FaultInjectionPanel`.
- **API & WebSocket Integration**: Fetches metrics, incidents, alarms, and topology on mount. Subscribes to all 8 WebSocket event types to perform selective silent state reconciliation without full-page reloads.

#### 2. Network Map Page (`frontend/src/pages/NetworkMapPage.tsx`)
- **Responsibility**: Visualizes the 4-tier network graph (`CORE`, `AGGREGATION`, `SITE`, `CELL`), node statuses, parent-child link lines, and geographic coordinates (when configured).
- **Features**: Interactive node selection displaying real-time node metadata and latest telemetry observations in an inspection drawer.

#### 3. KPIs & Telemetry Page (`frontend/src/pages/KpisPage.tsx`)
- **Responsibility**: Live multi-variate metric exploration across radio, performance, and reliability dimensions.
- **Controls**: Includes an operator action button invoking `POST /api/v1/telemetry/generate-step` with loading state indicators and double-click protection.

#### 4. Alarms Page (`frontend/src/pages/AlarmsPage.tsx`)
- **Responsibility**: Authoritative alarm inventory supporting filtering by severity (`CRITICAL`, `MAJOR`, `WARNING`), status (`ACTIVE`, `CLEARED`), and node.
- **Operator Workflows**: Multi-select checkbox column allowing operators to select multiple active alarms and trigger "Promote to Incident" into a unified ticket.

#### 5. Incidents Page (`frontend/src/pages/IncidentsPage.tsx`)
- **Responsibility**: Full operational incident lifecycle management, SLA countdown timers, triage modal dialogs, and timeline audit logs.
- **Actions**: "Acknowledge" modal (capturing operator ID) and "Resolve" modal (enforcing mandatory resolution summary notes). Manual "Create Incident" action.

#### 6. Analytics Page (`frontend/src/pages/AnalyticsPage.tsx`)
- **Responsibility**: Historical operational intelligence reporting system SLA compliance percentages, MTTA/MTTR/MTTD duration averages, and severity distribution charts.

### 21.2 Reusable Component Library

- **`MetricCard`** (`MetricCard.tsx`): Displays large numeric values, trend indicators, status icons, and subtext descriptions.
- **`DataTable`** (`DataTable.tsx`): Generic typed table with sorting, column customization, empty states, and multi-select support.
- **`SeverityBadge`** (`SeverityBadge.tsx`): Color-coded visual pills for `CRITICAL` (red), `MAJOR` (orange), `WARNING` (amber), and `MINOR` (blue).
- **`StatusBadge`** (`StatusBadge.tsx`): Visual indicator for operational states (`ONLINE`, `DEGRADED`, `OFFLINE`).
- **`FaultInjectionPanel`** (`FaultInjectionPanel.tsx`): Interactive control widget allowing operators to activate or deactivate any of the 6 reference fault scenarios directly from the UI.

---

## 22. Configuration Reference

### 22.1 Environment Configuration (`.env`)
```ini
# Database Persistence
POSTGRES_USER=nexus_user
POSTGRES_PASSWORD=production_secure_password_replace_in_prod
POSTGRES_DB=nexus_db
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# Application Settings
ENVIRONMENT=production
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO
NEXUS_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Observability Credentials
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=production_grafana_password_replace_in_prod

# Host Interface Binding (Security Hardening)
BACKEND_BIND_IP=127.0.0.1
FRONTEND_BIND_IP=127.0.0.1
GRAFANA_BIND_IP=127.0.0.1
PROMETHEUS_BIND_IP=127.0.0.1
```

### 22.2 Reverse Proxy Configuration (`frontend/nginx.conf`)
```nginx
server {
    listen 80;
    server_name localhost;

    # Host static frontend single-page application
    location / {
        root /usr/share/nginx/html;
        index index.html index.htm;
        try_files $uri $uri/ /index.html;
    }

    # Proxy REST API requests to backend container
    location /api/ {
        proxy_pass http://backend:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Proxy real-time WebSocket connections with protocol upgrade
    location /ws/ {
        proxy_pass http://backend:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    # Health probe endpoint
    location /health {
        access_log off;
        return 200 "healthy\n";
    }
}
```

---

# PART V — EXECUTION AND ENGINEERING VALIDATION

## 23. Complete End-to-End Workflows

### Workflow A: Application Startup & Lifespan Initialization
1. **Entry Point**: ASGI server (Uvicorn) executes `nexus.main:create_app()` and enters the `lifespan` context manager.
2. **Database Verification**: `docker-entrypoint.sh` executes `alembic upgrade head`. In SQLite development mode, `Base.metadata.create_all()` runs if tables do not exist.
3. **Singleton Instantiation**: `get_broadcaster()`, `get_topology_registry()`, `get_telemetry_store()`, `get_alarm_service()`, and `get_fault_service()` instantiate singleton instances.
4. **Subsystem Wiring**:
   - `store.set_event_publisher(broadcaster.publish)`
   - `alarm_service.set_event_publisher(broadcaster.publish)`
   - `fault_service.set_event_publisher(broadcaster.publish)`
   - `topo.add_status_listener(on_topology_status_change)`
5. **Readiness Probe**: Probes `GET /ready` test all 6 subsystems (`topology`, `broadcaster`, `telemetry_store`, `alarm_service`, `fault_service`, `database`). When all report ready, HTTP 200 is returned.

### Workflow B: Network Topology Initialization
1. **Builder Execution**: `build_simulated_network()` constructs a new `Topology` instance.
2. **Tier-by-Tier Insertion**:
   - Registers root node `CORE-01` (`NodeType.CORE`, `parent_id=None`).
   - Registers distribution routers `AGG-01`, `AGG-02` (`parent_id="CORE-01"`).
   - Registers site base stations `SITE-01..03` under `AGG-01` and `SITE-04..06` under `AGG-02`.
   - Registers 18 cell sectors (`CELL-01..18`), allocating 3 sectors per site.
3. **Transport Allocation**: `build_reference_transport_network(topology)` validates all non-root nodes and constructs 26 bidirectional transport links (`LINK-CORE-AGG-01..02`, `LINK-AGG-SITE-01..06`, `LINK-SITE-CELL-01..18`).

### Workflow C: Telemetry Generation Step
1. **Trigger**: Operator clicks "Generate Step" in web console or test script posts to `POST /api/v1/telemetry/generate-step`.
2. **Lock Acquisition**: `_step_generation_lock` acquires non-blocking lock; rejects concurrent calls with HTTP 409.
3. **Synthesis Loop**: `TelemetryPipeline.generate_step()` iterates across all 27 nodes. For each node, `SyntheticTelemetryGenerator` samples metrics from the tier's `NodeOperatingProfile`, applies first-order exponential smoothing ($\alpha = 0.65$), and modulates cross-KPI RF dependencies.
4. **Fault Modulation**: If a fault scenario is active, `FaultScenarioEngine.apply_faults()` transforms the base snapshots non-destructively.
5. **Memory Ingestion**: Snapshots are appended to `TelemetryStore` deques ($O(1)$ amortized append).
6. **Broadcasting**: `EventBroadcaster.publish("TELEMETRY_SNAPSHOT", payload)` streams snapshots to connected clients.

### Workflow D: Normal KPI Processing (No Faults)
1. **Detection Pass**: `AnomalyDetectionEngine.evaluate_snapshot()` evaluates clean snapshots against threshold rules and statistical baselines.
2. **Baseline Update**: Clean samples satisfy bounds; the Evaluate-Then-Commit policy commits them to rolling median deques and updates recursive EWMA mean and variance states.
3. **Zero Alarms**: With zero anomalies flagged, `AlarmManager.active_alarms_count` remains 0.
4. **Correlation & Incident Bypass**: `TelemetryPipeline` observes 0 active alarms, skipping downstream graph traversal and incident creation.

### Workflow E: Anomaly Detection Under Injected Fault
1. **Fault Injection**: Scenario `backhaul_failure` targeting `LINK-AGG-01-SITE-01` is active.
2. **Telemetry Degradation**: Downstream nodes (`SITE-01`, `CELL-01..03`) receive 0.0 Mbps throughput, 0.0% availability, 100% connection drop rate, and elevated transit latency (timeout penalty).
3. **Static Threshold Trigger**: Snapshots breach `RULE-AVAIL-CRIT` ($< 95.0\%$) and `RULE-TP-WARN` ($< 5.0\text{ Mbps}$).
4. **Statistical Anomaly Trigger**: Outage values deviate drastically from historical medians ($Z_{\text{MAD}} \gg 3.0$).
5. **Baseline Protection**: Both anomalous observations trigger contamination rejection; the outage values are discarded from baseline updates, preserving pre-fault historical baselines.

### Workflow F: Alarm Creation & Deduplication
1. **Anomaly Ingestion**: `AnomalyEvent` instances enter `AlarmManager.process_anomaly()`.
2. **Key Resolution**: Computes composite key `(node_id, metric_name, rule_id, source)`.
3. **Active Insertion**: If new, assigns `ALARM-<node>-<rule>-<counter>`, sets `observation_count = 1`, and emits `ALARM_CREATED`.
4. **Update Transition**: On subsequent simulation steps, existing active alarms update `last_seen`, increment `observation_count`, and emit `ALARM_UPDATED` without creating duplicate ticket IDs.

### Workflow G: Topology-Aware Alarm Correlation
1. **Query Active**: `TelemetryPipeline` retrieves all active alarms from `AlarmManager`.
2. **Deduplication & Sorting**: Unique alarms are sorted by `(first_seen, node_id, alarm_id)`.
3. **Pairwise Evaluation**: `AlarmCorrelationEngine._can_correlate()` checks temporal proximity ($\le 300\text{s}$), same-node affinity, LCA hierarchy distance ($\le 2$ hops), distant core protection, and symptom compatibility.
4. **Graph BFS Traversal**: Connected components are traversed with the maximum onset span constraint.
5. **Anchor Assignment**: `_find_group_lca()` identifies `SITE-01` as the group anchor node.
6. **Output**: An immutable `CorrelationGroup` (`CORR-SITE-01-...`) containing 20 alarms across 4 nodes is formed.

### Workflow H: Root Cause Analysis Evaluation
1. **Telemetry Selection**: Snapshots are filtered to include only observations prior to or at incident onset within staleness limits.
2. **Rule Evaluation**: Diagnostic rules run against the correlation group:
   - `evaluate_backhaul_failure()` detects anchor at `SITE-01`, confirmed transport degradation, and identifies incoming link `LINK-AGG-01-SITE-01`, scoring confidence $0.85$.
   - `evaluate_site_power_failure()` notes elevated latency, penalizing the power outage hypothesis.
3. **Ranking**: The backhaul hypothesis is ranked #1. Target is identified as `TRANSPORT_LINK` (`LINK-AGG-01-SITE-01`).
4. **Recommended Action**: Sets action: *"Inspect physical transport link and verify optical transceivers / fiber continuity."*

### Workflow I: Incident Creation & Deduplication
1. **Service Ingestion**: `IncidentService.create_or_update_incident()` receives the correlation group and RCA result.
2. **Deduplication Check**: Queries active incidents in PostgreSQL. Matches against active correlation group ID or intersecting alarm IDs.
3. **Severity & Priority Assignment**: `OperationalSeverityPolicy` evaluates the 4 affected nodes and access-tier critical alarms, assigning `CRITICAL` severity and `P1` priority.
4. **SLA Deadline Calculation**: `SLACalculator` calculates deadlines ($t_{\text{created}} + 15\text{m}$ for Ack, $+ 60\text{m}$ for Resolve).
5. **Persistence**: Persists `incidents` record and appends `CREATED` timeline event in a single atomic transaction.
6. **Broadcasting**: Publishes `INCIDENT_CREATED` frame over WebSocket.

### Workflow J: SLA Tracking & Deadline Monitoring
1. **Active Evaluation**: Periodic API requests or dashboard refreshes invoke `incident.get_sla_status()`.
2. **Clock Evaluation**: If $t_{\text{now}} > t_{\text{ack\_deadline}}$ and unacknowledged, `ack_breached` evaluates to `true`.
3. **Prometheus Exposition**: `nexus_incidents_sla_breaches_total{sla_type="acknowledgement"}` increments.

### Workflow K: Real-Time Frontend Updates
1. **Frame Ingress**: React web console receives `INCIDENT_CREATED` frame via native WebSocket client.
2. **Event Routing**: `useWebSocketSubscription` hook triggers registered callback handlers.
3. **Selective Refresh**: `OverviewPage` reconciles metrics and incident tables silently without full page reloads. Top bar flashes red P1 alert badge.

### Workflow L: Incident Resolution & SLA Freezing
1. **Operator Action**: NOC operator resolves issue and posts to `POST /api/v1/incidents/{id}/resolve` with resolution notes.
2. **State Transition**: `IncidentService` validates transition from `ACKNOWLEDGED` to `RESOLVED`, sets `resolved_at` and `resolved_by`, and appends `RESOLVED` timeline event.
3. **SLA Permanent Freeze**: Both `ack_breached` and `resolve_breached` flags permanently freeze based on actual historical timestamps.
4. **Broadcasting**: Emits `INCIDENT_RESOLVED` event over WebSocket. Dashboard clears active ticket alerts.

---

## 24. Testing Architecture

### 24.1 Test Suites Summary

| Test Suite | Framework | Location | Test Count | Pass Count | Failure Count | Verified Scope |
|:---|:---|:---|:---:|:---:|:---:|:---|
| **Backend Suite** | Pytest 9.2.0 | `tests/` | **597** | **597** | **0** | Domain models, LCA algorithms, RCA heuristics, PostgreSQL ORM, WebSocket concurrency, Prometheus cardinality, directional KPI detection, 2-sample recovery hysteresis |
| **Frontend Suite** | Vitest 2.1.8 | `frontend/tests/` | **69** | **69** | **0** | React page rendering, navigation redirects, typed API client timeouts, WebSocket client exponential backoff |
| **Acceptance Harness** | Python 3 | `scripts/verify_e2e_acceptance.py` | **25** | **25** | **0** | Live end-to-end multi-container runtime verification across all 6 scenarios, PromQL queries, Grafana dashboards |

### 24.2 Ground-Truth Isolation Verification (`test_ground_truth_isolation.py`)
To prevent "cheating" where diagnostic engines peek at simulation answers:
- Uses Python `ast` (Abstract Syntax Tree) static analysis to parse all source files in `src/nexus/detection/`, `src/nexus/correlation/`, `src/nexus/rca/`, and `src/nexus/incidents/`.
- Asserts that no source file imports from `nexus.fault`, references `GroundTruthRecord`, or accesses simulation ground truth.

### 24.3 Executing Tests
```bash
# Backend pytest suite:
pytest -v --tb=short

# Frontend vitest suite:
cd frontend && pnpm run test

# Live end-to-end acceptance harness:
python scripts/verify_e2e_acceptance.py
```

### 24.4 Automated Pipeline Benchmark Results (`scripts/run_benchmark.py`)
The benchmark harness evaluates platform detection, correlation, and RCA diagnostic accuracy across all 6 reference telecom failure scenarios under standardized conditions (`--seed 42 --steps 30`).

#### Global Benchmark Performance Summary
| Metric Category | Performance Indicator | Benchmark Result | Operational Impact |
|:---|:---|:---:|:---|
| **Fault Detection** | Scenario Fault Recall | **100.0%** (6/6 detected, 0 undetected) | Zero missed network outages across all reference failure topologies. |
| **Alarm Precision** | Micro Alarm Precision | **94.46%** (665 TP / 39 FP / 704 total) | Eliminates false-positive noise via directional KPI filtering and profile-spread floors. |
| **Detection Quality** | Micro Hybrid F1 Score | **0.9715** | Harmonized balance of rapid alarm activation and noise rejection. |
| **Response Latency** | Mean Time to Detect (MTTD) | **0.0 s** | Immediate detection upon fault step onset under synthetic step evaluation. |
| **Alarm Storm Suppression**| Alarm Reduction Ratio | **94.60%** (704 raw alarms -> 38 groups) | Condenses massive alarm storms into concise, actionable incident clusters. |
| **Root Cause Accuracy** | Top-1 Cause Accuracy | **100.0%** (6/6 scenarios) | Correctly identifies exact failure mode across all scenarios. |
| **Entity Localization** | Target Entity Accuracy | **100.0%** (6/6 scenarios) | Pinpoints the exact degraded link, facility, or sector cell. |

#### Scenario Breakdown
| Scenario ID | Fault Type | Target Node / Link | Alarms Raised | TP Alarms | FP Alarms | Precision | Top-1 RCA Result | Target Match |
|:---|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| `backhaul_failure` | `BACKHAUL_FAILURE` | `LINK-AGG-01-SITE-01` | 108 | 108 | 0 | 100.0% | `BACKHAUL_FAILURE` | PASS |
| `site_power_failure` | `SITE_POWER_FAILURE` | `SITE-02` | 108 | 108 | 0 | 100.0% | `SITE_POWER_FAILURE` | PASS |
| `cell_degradation` | `CELL_DEGRADATION` | `CELL-01` | 40 | 40 | 0 | 100.0% | `CELL_DEGRADATION` | PASS |
| `correlated_cascade` | `CASCADE_FAILURE` | `AGG-01` | 316 | 316 | 0 | 100.0% | `CASCADE_FAILURE` | PASS |
| `transient_flap` | `TRANSIENT_FLAP` | `CELL-03` | 18 | 17 | 1 | 94.44% | `TRANSIENT_FLAP` | PASS |
| `silent_drop` | `SILENT_PACKET_LOSS`| `LINK-AGG-02-SITE-04` | 114 | 76 | 38 | 66.67% | `SILENT_PACKET_LOSS` | PASS |

---

## 25. Performance and Scalability

### 25.1 Computational Complexity Breakdown
- **LCA Alarm Correlation**: Evaluates pairwise edges in $O(N^2)$ time where $N$ is active alarm count. For typical telecom fault blast radii ($N \le 60$), execution completes in $< 0.5\text{ ms}$.
- **Root Cause Analysis**: Evaluates 6 diagnostic rules against $M$ candidate nodes in $O(M)$ linear time ($< 0.2\text{ ms}$).
- **In-Memory Telemetry Buffer**: Bounded `collections.deque(maxlen=60)` ensures $O(1)$ append time and strictly $O(1)$ bounded memory.
- **Incident Metrics Calculation**: Uses streaming cursor pagination ($B = 100$) to guarantee $O(1)$ memory consumption across arbitrary database ticket volumes.

### 25.2 Concurrency & Thread Safety
- **FastAPI ASGI Server**: High-concurrency async I/O handling hundreds of simultaneous HTTP and WebSocket connections.
- **Step Generation Lock**: `_step_generation_lock` prevents race conditions during discrete simulation cycles.
- **Cross-Thread Event Dispatch**: `EventBroadcaster` uses `loop.call_soon_threadsafe()` to marshal events from synchronous worker threads to async subscriber queues safely.

---

## 26. Security Architecture

### 26.1 Implemented Security Hardening
1. **Unprivileged Container Execution**: Backend container runs as user `nexus` (UID 1000). Frontend runs as user `nginx`. `security_opt: ["no-new-privileges:true"]` enforced across all services.
2. **Host Port Loopback Binding**: Published ports (`3000`, `8000`, `3001`, `9090`) bind exclusively to host loopback interface (`127.0.0.1`), preventing exposure to external LAN or public interfaces.
3. **Mandatory Secrets Enforcement**: Docker Compose uses `:?` syntax to abort startup if `POSTGRES_PASSWORD` or `GRAFANA_ADMIN_PASSWORD` are missing.
4. **CORS Restriction**: Whitelists configured frontend origins (`NEXUS_CORS_ORIGINS`).
5. **SQL Injection Prevention**: All persistence operations utilize SQLAlchemy parameterized ORM queries; no raw SQL concatenation exists.

### 26.2 Identified Production Gaps & Recommendations
- **Authentication**: REST API and WebSocket endpoints lack JWT/OAuth2 authentication. Recommend deploying an API Gateway (Kong/Envoy) or OAuth2 reverse proxy.
- **WebSocket Access Control**: Connect requests to `/ws/live` should validate authentication tokens during the initial HTTP upgrade handshake.

---

## 27. Deployment and CI/CD

### 27.1 Production Docker Compose Architecture
NEXUS deploys as a multi-container stack defined in `docker-compose.yml`:
- `nexus-postgres`: PostgreSQL 15 Alpine with persistent volume `postgres_data`.
- `nexus-backend`: FastAPI Python 3.11-slim application server with curl healthcheck.
- `nexus-frontend`: React SPA hosted on Nginx Alpine gateway with reverse proxying.
- `nexus-prometheus`: Prometheus v2.51.0 polling `/metrics` every 5 seconds.
- `nexus-grafana`: Grafana 10.4.0 with provisioned dashboards and Prometheus datasource.

### 27.2 Continuous Integration Pipeline (`.github/workflows/ci.yml`)
The GitHub Actions workflow triggers on push and pull requests to `main`:
1. **Backend Job**: Sets up Python 3.11, installs editable dependencies, runs flake8 linting, and executes the complete 597-test pytest suite.
2. **Frontend Job**: Sets up Node.js 20, enables Corepack with pnpm 9.15.4, executes TypeScript typecheck (`tsc --noEmit`), runs 69 Vitest tests, and compiles the production Vite bundle.
3. **E2E Acceptance Job**: Builds Docker containers, spins up the multi-container stack, verifies healthchecks, and executes `scripts/verify_e2e_acceptance.py`.

---

## 28. Troubleshooting and Operational Runbook

### 28.1 Subsystem Diagnostics

| Issue | Symptoms | Probable Cause | Diagnostic Command | Resolution |
|:---|:---|:---|:---|:---|
| **Database Connection Failure** | Backend container logs show `Could not connect to database within timeout limit` | PostgreSQL container slow to start or invalid credentials | `docker compose logs postgres` | Verify `POSTGRES_PASSWORD` in `.env`; check PostgreSQL container health status. |
| **Alembic Migration Error** | Backend logs show `RuntimeError: Database schema is not migrated` | Application started without running migrations | `docker compose exec backend alembic current` | Execute `docker compose exec backend alembic upgrade head`. |
| **WebSocket Disconnects** | Web console shows amber `RECONNECTING` badge | Network interruption or backend container restart | Inspect browser console for WebSocket close codes (e.g. 1006) | Native client will automatically reconnect via exponential backoff. Check backend logs for unhandled exceptions. |
| **Telemetry Step 409 Conflict** | API returns `409 Conflict: Telemetry step generation already in progress` | Operator triggered multiple simulation steps concurrently | Check access logs for rapid repeated `POST /generate-step` calls | Ensure automated scripts await previous response before initiating subsequent steps. |
| **Empty Grafana Panels** | Grafana displays "No Data" for specific panels | Discrepancy between dashboard PromQL queries and `/metrics` labels | Execute PromQL query directly in Prometheus (`http://localhost:9090`) | Verify that metric names and labels match `nexus.metrics` exporter definitions. |

---

# PART VI — ENGINEERING ANALYSIS

## 29. Design Decisions and Trade-offs

NEXUS reflects deliberate architectural trade-offs balancing deterministic repeatability, explainability, developer velocity, and operational reliability:

1. **In-Memory Sliding Buffer vs. Distributed Time-Series Database**:
   - *Rationale*: Storing recent snapshots (maxlen=60) in-memory provides sub-millisecond graph query latencies and enables zero-infrastructure local test execution.
   - *Trade-off*: History resets across container restarts. Production carrier deployment would introduce ClickHouse or TimescaleDB for multi-year historical analytics.
2. **Deterministic LCA Graph Traversal vs. Deep Learning Clustering**:
   - *Rationale*: Telecommunications infrastructure operations demand 100% explainability. Tree-based LCA traversal guarantees clear causal paths that can be audited by tier-3 engineers.
   - *Trade-off*: Assumes tree-structured or DAG hierarchy; dynamic mesh routing requires upstream preprocessing.
3. **Decoupled Operational Severity vs. Algorithmic Confidence**:
   - *Rationale*: A regional core router failure affecting 500,000 subscribers must be classified as P1 Critical immediately, even if automated diagnosis is uncertain.
   - *Trade-off*: Low-confidence core alarms still page on-call engineers.
4. **Evaluate-Then-Commit Baseline Protection**:
   - *Rationale*: Excludes anomalous observations from updating historical rolling baselines, preventing outages from corrupting normal references.
   - *Trade-off*: Requires an initial clean warmup period (minimum 5 samples) before faults can be evaluated.
5. **Serialized Single Outbound WebSocket Sender**:
   - *Rationale*: Eliminates frame collisions and Starlette concurrency exceptions over active WebSockets while guaranteeing bounded memory through FIFO backpressure.
   - *Trade-off*: Extremely slow clients may lose intermediate state snapshots during rapid bursts.

---

## 30. Known Limitations

- **Volatile Telemetry History**: In-memory telemetry buffer is lost when the backend container restarts. (Persistent incident and audit records in PostgreSQL are unaffected).
- **Static Topology Hierarchy**: Topology graph is constructed at initialization time. Dynamically re-parenting or modifying nodes requires reconstructing the `Topology` instance.
- **Single-Process CPU Bound**: Telemetry throughput is bounded by single-process Python execution (~3,000 snapshots/sec).
- **Authentication Absence**: REST and WebSocket endpoints lack token-based (JWT) authentication, relying on reverse proxy perimeter security.
- **Tree-Oriented Correlation**: Designed for hierarchical telecom backhaul. Non-hierarchical mesh topologies require pre-computed path trees.
- **Synthetic Data Generation**: Evaluation uses synthetic telemetry data generated from the project's own generator (`SyntheticTelemetryGenerator`).
- **Instantaneous Fault Injections (MTTD = 0.0 s)**: Simulated MTTD is 0.0 s because fault injection is applied instantaneously at simulation step $t=0$, causing immediate step threshold and statistical breaches.
- **Detector Seed Coupling**: Detector baseline seeds come from the same nominal profiles (`DEFAULT_PROFILES`) that the generator uses.

---

## 31. Future Engineering Roadmap

### Short-Term (1-3 Months)
- **JWT / OAuth2 Authentication**: Implement FastAPI Bearer token authentication and role-based access controls (`NOC_OPERATOR`, `NOC_ENGINEER`, `ADMIN`).
- **Dynamic Topology Modification API**: Add REST endpoints allowing runtime node provisioning, de-provisioning, and parent link re-routing.
- **Grafana Alerting Webhooks**: Provision automated notification channels dispatching P1/P2 incidents to Slack and PagerDuty.

### Medium-Term (3-6 Months)
- **ClickHouse / TimescaleDB Persistence**: Integrate persistent time-series storage for long-term historical telemetry archiving.
- **Kafka / OpenTelemetry Ingestion**: Develop streaming adapters ingesting authentic 3GPP PM XML/JSON or OpenTelemetry gRPC telemetry.
- **Multi-Path Mesh LCA Correlation**: Extend LCA graph algorithms to support redundant, multi-homed ring topologies.

### Long-Term (6-12 Months)
- **Closed-Loop Automated Remediation**: Integrate optional webhook orchestrators (ONAP / Open RAN SMO) for automated traffic offloading upon verified congestion.

---

## 32. Glossary

- **Blast Radius**: The set of subordinate network nodes impacted by an upstream node or link failure.
- **Distant Core Protection**: Correlation policy preventing unrelated aggregation branch alarms from merging at `CORE-01` unless a direct core alarm exists.
- **EWMA (Exponentially Weighted Moving Average)**: Statistical baseline tracking moving mean and variance with exponential decay weighting.
- **FIFO Backpressure**: Queue eviction strategy discarding the oldest unconsumed message when subscriber queues reach capacity.
- **Hysteresis**: Dual-threshold technique enforcing different boundary values for alarm triggering vs. clearing to eliminate flapping.
- **LCA (Lowest Common Ancestor)**: Graph-theoretic algorithm finding the deepest shared ancestor node of two or more vertices in a tree.
- **MAD (Median Absolute Deviation)**: Robust statistical measure of variability less sensitive to extreme outliers than standard deviation.
- **MTTA (Mean Time to Acknowledge)**: Elapsed time from incident creation to operator acknowledgement.
- **MTTD (Mean Time to Detect)**: Elapsed time from fault onset to initial alarm detection.
- **MTTR (Mean Time to Resolve)**: Elapsed time from incident creation to verified operational resolution.
- **PRB (Physical Resource Block)**: Fundamental cellular radio frequency and time allocation resource unit in LTE and 5G NR.
- **RSRP (Reference Signal Received Power)**: Primary measurement of cellular signal power in dBm.
- **SINR (Signal-to-Interference-plus-Noise Ratio)**: Ratio of wanted radio signal power to unwanted interference and background noise in dB.
- **SLA (Service Level Agreement)**: Contractual operational commitment specifying maximum allowable MTTA and MTTR durations.

---

## 33. Comprehensive Interview Preparation Appendix

### 33.1 Technical Questions & Answers (Implementation Deep-Dive)

#### Q1: How does NEXUS prevent alarm flapping when a metric oscillates near a threshold boundary?
**Answer**: NEXUS implements an explicit hysteresis recovery threshold (`clear_threshold`) on every `ThresholdRule`. For an upper-bound trigger (e.g. latency $> 80\text{ ms}$), an alarm triggers at 80 ms but does not clear until latency drops below $60\text{ ms}$. This gap prevents rapid alarm creation and clearing cycles when metric values fluctuate between 79 and 81 ms (`src/nexus/detection/rules.py`).

#### Q2: What is the Evaluate-Then-Commit policy in the statistical detector, and why is it necessary?
**Answer**: If a telemetry observation violates either the Rolling Median or EWMA anomaly detector, it is flagged as an anomaly and immediately excluded from updating both baseline states (`src/nexus/detection/statistical_detector.py`). This prevents severe sustained faults (e.g. throughput dropping to 0 Mbps during an outage) from corrupting the baseline and permanently freezing alarms upon recovery.

#### Q3: Why does the Rolling Median detector scale MAD by 1.4826?
**Answer**: For normally distributed data, the expected value of MAD is $\approx 0.6745 \cdot \sigma$. Multiplying MAD by $1 / 0.6745 \approx 1.4826$ yields an asymptotically unbiased estimator of standard deviation ($\hat{\sigma}$) that remains resilient to extreme outliers.

#### Q4: How does NEXUS handle constant zero-variance baselines in statistical detection?
**Answer**: When a metric remains completely constant across the sliding window, raw MAD equals zero, which would cause division-by-zero errors. NEXUS enforces a minimum scale floor: $\sigma_{\text{floor}} = 0.05 \cdot \max(|\tilde{\mu}|, 1.0)$. The effective scale is $\max(\hat{\sigma}_{\text{raw}}, \sigma_{\text{floor}})$, guaranteeing a finite, stable denominator.

#### Q5: What is Distant Core Protection in the correlation engine?
**Answer**: In a hierarchical topology, all nodes ultimately share `CORE-01` as their common ancestor. Without protection, an independent failure in the West aggregation branch and an unrelated failure in the East aggregation branch would calculate `CORE-01` as their LCA and merge into a false global cluster. NEXUS rejects merges at `CORE-01` unless an alarm exists directly on `CORE-01` itself (`src/nexus/correlation/engine.py`).

#### Q6: How does the correlation engine prevent transitive time-window chaining?
**Answer**: When traversing connected components via BFS, an edge is accepted only if the total onset span of the resulting group ($\max(\text{first\_seen}) - \min(\text{first\_seen})$) remains $\le \Delta T_{\text{window}}$ (default: 300s). If an edge would extend the group's span beyond 300s, the candidate alarm is deferred to a subsequent group, preventing chain reactions from spanning hours.

#### Q7: Why are localized metrics forbidden from correlating across different nodes?
**Answer**: Physical RF parameters (`sinr_db`, `rsrp_dbm`) and radio scheduler metrics (`prb_utilization_pct`) represent localized cell-sector phenomena. Correlating poor SINR on one sector with an alarm on an adjacent site would create false causal clusters. Only systemic branch metrics (`availability_pct`, `latency_ms`, `throughput_mbps`) correlate across parent-child links.

#### Q8: How does the RCA engine distinguish a Backhaul Link Failure from a Site Power Failure?
**Answer**: A physical backhaul cut elevates transit latency (timeout penalty on unreachable downstream nodes) while dropping throughput and availability. A site facility power failure drops throughput and availability to zero across all site cells while leaving baseline network latency unamplified (`src/nexus/fault/engine.py`). Furthermore, `evaluate_backhaul_failure` identifies incoming transport links, whereas `evaluate_site_power_failure` targets the facility node directly.

#### Q9: How is incident duplication prevented during prolonged faults?
**Answer**: In `src/nexus/incidents/service.py`, `create_or_update_incident()` queries existing active incidents in PostgreSQL before creating a new ticket. It matches on three criteria: identical correlation group ID, shared anchor node, or intersecting alarm IDs. If an active match is found, it updates the existing ticket in place, updating RCA confidence and merging new alarms without creating duplicate ticket IDs.

#### Q10: Why does operational incident severity ignore RCA confidence scores?
**Answer**: Operational severity dictates field technician dispatch priority. If an optical backbone connecting an entire region fails, the operational severity is `CRITICAL (P1)` regardless of whether automated diagnostic rules have 95% confidence or 20% confidence. Demoting a core failure because automated diagnosis is uncertain would cause severe SLA breaches.

#### Q11: How does NEXUS prevent retroactive SLA breaches after an incident is resolved?
**Answer**: In `src/nexus/incidents/sla.py`, when an incident transitions to `RESOLVED`, the SLA compliance status permanently freezes based on historical timestamps (`acknowledged_at` vs. `ack_deadline`, `resolved_at` vs. `resolve_deadline`). Future clock advances or API evaluations evaluate against these frozen historical timestamps.

#### Q12: How does the WebSocket architecture prevent frame corruption from concurrent writes?
**Answer**: In `src/nexus/events/api.py`, all outbound writes over the socket are channeled strictly through a single `sender_task`. Concurrent async tasks and worker threads enqueue messages into bounded priority queues rather than calling `websocket.send_text()` directly, completely preventing Starlette socket collision exceptions.

#### Q13: What happens when a WebSocket client is too slow to consume broadcast events?
**Answer**: Each subscriber queue is bounded to `maxsize=100`. When a slow consumer's queue fills, `EventBroadcaster` applies FIFO backpressure: it pops and discards the oldest unconsumed message (`queue.get_nowait()`), increments `dropped_events_count`, and enqueues the latest frame. This bounds memory and protects the backend process from OOM crashes.

#### Q14: How does the WebSocket server prevent heartbeat PING/PONG floods from starving domain events?
**Answer**: The outbound `sender_task` implements priority gating: it allows at most 3 consecutive PONG frames to be dispatched before forcing a yield to pending domain events in `event_queue`, guaranteeing that client ping floods cannot starve critical incident or alarm alerts.

#### Q15: How does NEXUS enforce low-cardinality in Prometheus metrics?
**Answer**: The metrics manager strictly forbids dynamic identifiers (`node_id`, `alarm_id`, `incident_id`), timestamps, and operator notes in Prometheus labels. HTTP requests are normalized against route templates (`/api/v1/incidents/{incident_id}`). Domain telemetry is aggregated across the 4 static node tiers (`CORE`, `AGGREGATION`, `SITE`, `CELL`).

#### Q16: Why is the `/metrics` endpoint excluded from Prometheus HTTP request tracking?
**Answer**: Including `/metrics` would cause the scraper's own polling requests to distort request rates and latency histograms, creating artificial scrape traffic spikes.

#### Q17: What guarantees that diagnostic code does not inspect simulation ground truth?
**Answer**: Architectural boundary isolation is enforced and statically verified via `tests/test_ground_truth_isolation.py`. The test uses Python's `ast` module to inspect all production diagnostic source files, asserting zero imports of `nexus.fault` or references to `GroundTruthRecord`.

#### Q18: What is the time complexity of the LCA alarm correlation algorithm?
**Answer**: Constructing the compatibility graph takes $O(N^2)$ pairwise checks where $N$ is the active alarm count. Lineage lookup takes $O(H) = O(1)$ where $H \le 4$. BFS component traversal takes $O(N + E) \le O(N^2)$. For typical blast radii ($N \le 60$), execution takes $< 0.5\text{ ms}$.

#### Q19: How does `MetricsCalculator` prevent OOM failures during MTTA/MTTR calculations?
**Answer**: It queries the database repository using streaming cursor pagination with fixed batch sizes ($B = 100$), processing resolved incidents in $O(1)$ memory rather than loading the entire historical table into Python memory.

#### Q20: What database indexes exist on the `incidents` table?
**Answer**: Indexes are established on `correlation_group_id` (Unique), `status`, `severity`, and `created_at` (`migrations/versions/0001_initial_incident_schema.py`).

#### Q21: What database indexes exist on `incident_timeline_events`?
**Answer**: Indexes are established on `incident_id` (Foreign Key), `event_type`, and `timestamp`.

#### Q22: What happens if an operator attempts to reopen a resolved incident?
**Answer**: The domain state machine in `src/nexus/incidents/service.py` rejects modifications to resolved incidents, raising `InvalidStateTransitionError` and returning HTTP 400.

#### Q23: What are the 6 reference telecom failure scenarios implemented in NEXUS?
**Answer**: `cell_outage`, `backhaul_failure`, `radio_interference`, `cell_congestion`, `site_power_failure`, and `core_router_failure` (`src/nexus/fault/scenarios.py`).

#### Q24: What is the blast radius of a `core_router_failure`?
**Answer**: A core router failure on `CORE-01` impacts the entire topology (all 27 nodes) as the central regional routing hub collapses.

#### Q25: What is the blast radius of a `backhaul_failure` on `LINK-AGG-01-SITE-01`?
**Answer**: It isolates 4 nodes: downstream facility `SITE-01` and its 3 subordinate cell sectors `CELL-01`, `CELL-02`, and `CELL-03`.

#### Q26: How does `SyntheticTelemetryGenerator` model temporal continuity?
**Answer**: It uses first-order exponential smoothing with weight $\alpha = 0.65$: $S_t = 0.65 \cdot S_{t-1} + 0.35 \cdot X_{\text{target}}$, ensuring that successive steps fluctuate smoothly without unnatural discontinuous jumps.

#### Q27: How does `FaultScenarioEngine` calculate downstream blast radius?
**Answer**: It uses Breadth-First Search (BFS) starting from the failure target: for a transport link, it BFS-traverses from the downstream node; for a site node, it BFS-traverses all child cell nodes.

#### Q28: How does the frontend REST client handle request timeouts and cancellations?
**Answer**: In `frontend/src/api/client.ts`, each request initializes an `AbortController` with a configurable timer (default: 15,000ms). If the timer fires or the caller aborts, `controller.abort()` is called, throwing a typed `ApiError(408)` or `ApiError(499)`.

#### Q29: What is the purpose of the `/sw.js` endpoint in `src/nexus/main.py`?
**Answer**: It is a self-unregistering migration script that cleanly unregisters stale service workers previously installed on port 8000 by unrelated development applications, preventing operator browsers from caching dynamic API routes.

#### Q30: How is database migration automated inside the Docker backend container?
**Answer**: The container `docker-entrypoint.sh` executes a Python script that polls PostgreSQL until connectivity is confirmed (up to 30 retries), runs `alembic upgrade head`, and then launches Uvicorn.

#### Q31: How do directional KPI filters prevent false-positive alarms during service improvements?
**Answer**: Telecom metrics have explicit operational semantics. For `HIGHER_IS_BETTER_KPIS` (throughput, availability, SINR, RSRP), increases above baseline represent superior conditions and are suppressed from alarming unless throughput exceeds the surge ratio threshold. For `LOWER_IS_BETTER_KPIS` (latency, drop rate, packet loss), drops below baseline represent performance gains and are similarly filtered out (`src/nexus/detection/statistical_detector.py`).

#### Q32: What is the purpose of the profile-spread scale floor in statistical detection?
**Answer**: When a metric experiences zero or minimal variance, raw MAD and sample standard deviation collapse toward zero. Dividing by near-zero scale creates hypersensitivity to tiny, harmless noise fluctuations. NEXUS enforces a scale floor based on the metric's nominal profile range: $\sigma_{\text{floor}} = \max\left(\frac{\text{range\_max} - \text{range\_min}}{6.0}, 0.05 \cdot \max(|\mu|, 1.0)\right)$, guaranteeing robust and physically grounded denominators.

#### Q33: Why does the statistical detector implement 2-sample recovery hysteresis?
**Answer**: During network restoration, fluctuating telemetry can occasionally produce a single transient clean sample before settling. A naive detector would immediately clear the alarm, only to re-trigger it on the next step. Requiring two consecutive healthy observations (`consecutive_recovery_count = 2`) and resetting the counter on any unhealthy observation eliminates recovery flapping.

#### Q34: What is the surge ratio threshold and why is it set to 2.0x?
**Answer**: Legitimate cellular traffic frequently exhibits brief bursts (e.g. streaming start or speed tests). Setting `surge_ratio_threshold = 2.0` allows throughput to expand up to twice its nominal baseline before flagging an anomalous surge event.

---

### 33.2 Architecture & Design Interview Questions
1. **Explain the end-to-end data flow from synthetic metric generation to real-time UI rendering.**  
   *Discuss: `SyntheticTelemetryGenerator` $\to$ `FaultScenarioEngine` $\to$ `TelemetryStore` $\to$ `AnomalyDetectionEngine` $\to$ `AlarmManager` $\to$ `AlarmCorrelationEngine` $\to$ `RootCauseAnalysisEngine` $\to$ `IncidentService` $\to$ `PostgreSQL` $\to$ `EventBroadcaster` $\to$ WebSocket `/ws/live` $\to$ React `useWebSocketSubscription`.*
2. **How would you scale NEXUS from 27 nodes to 100,000 nodes?**  
   *Discuss: Replace in-memory sliding store with distributed TSDB (ClickHouse); ingest telemetry via Kafka partitions sharded by site/region; partition correlation graphs by aggregation hub; run correlation workers horizontally.*
3. **Why choose an explicit graph traversal algorithm (LCA) over an unsupervised clustering algorithm like DBSCAN?**  
   *Discuss: Determinism, 100% explainability, zero training burden, strict adherence to physical network tree topology, and compliance requirements in carrier NOCs.*
4. **How would you adapt the correlation engine for a non-hierarchical mesh topology with dynamic routing (e.g. SRv6)?**  
   *Discuss: Precompute active shortest-path forwarding trees using telemetry path tracing; map dynamic directed trees to LCA; evaluate link cut probability.*
5. **How does the Evaluate-Then-Commit baseline policy compare to robust Kalman filtering?**  
   *Discuss: Simple, deterministic, computationally inexpensive $O(1)$ rejection vs. state-space covariance tracking; prevents filter divergence under step-function outages.*

---

### 33.3 Five-Minute Project Pitch
"NEXUS is a telecom network intelligence and incident management platform designed to solve cascading alarm storms in carrier operations. In cellular networks, when an upstream transport link or facility power grid fails, dozens of downstream sites and hundreds of sector cells trigger alerts simultaneously, burying operators in symptom tickets. NEXUS embeds an authoritative 4-tier network graph directly into the telemetry ingestion pipeline. Telemetry is monitored via static thresholds with hysteresis and dual rolling statistical baselines (Median/MAD and EWMA). When alarms fire, our Lowest Common Ancestor graph traversal algorithm groups related symptoms under shared physical infrastructure, suppressing alarm storms. An explainable multi-hypothesis RCA engine diagnoses the exact failure type and target—distinguishing fiber cuts from site blackouts—and scores hypotheses with empirical evidence. Incidents persist in PostgreSQL with strict SLA deadlines, while real-time updates stream over WebSockets to a dark-mode React NOC console. The entire stack is fully tested with 597 backend tests, 69 frontend tests, and automated multi-container Docker deployment."

---

### 33.4 Fifteen-Minute Deep Technical Walkthrough
1. **The Telecommunications Operational Dilemma (2 mins)**: Explain alert fatigue, MTTA/MTTR inflation, and the failure of symptom-blind ticketing systems.
2. **Network Model & Telemetry Generation (3 mins)**: Detail the 27-node 4-tier hierarchy, 26 transport links, operating profiles, Gaussian sampling with exponential smoothing ($\alpha = 0.65$), and cross-KPI dependencies.
3. **Decoupled Detection & Baseline Protection (3 mins)**: Walk through static threshold hysteresis, Rolling Median/MAD scaled by 1.4826, recursive EWMA, and the Evaluate-Then-Commit baseline protection policy.
4. **Topology-Aware LCA Correlation & RCA (4 mins)**: Explain the pairwise compatibility conditions, LCA hierarchy distance bounds, Distant Core Protection, symptom compatibility, multi-hypothesis scoring heuristics, and UNKNOWN fallback.
5. **Incident Persistence, WebSockets & Observability (3 mins)**: Detail PostgreSQL Alembic models, SLA deadline freezing, thread-safe WebSocket broadcasting with FIFO backpressure, and low-cardinality Prometheus metrics with provisioned Grafana dashboards.

---

## 34. Source Code Traceability Appendix

| Engineering Subsystem | Primary Implementation Source Files | Domain Models & Schemas | Authoritative Test Files |
|:---|:---|:---|:---|
| **Topology Graph** | `src/nexus/topology/topology.py`<br/>`src/nexus/topology/builder.py` | `src/nexus/topology/models.py`<br/>`src/nexus/topology/schemas.py`<br/>`src/nexus/topology/enums.py` | `tests/test_topology.py`<br/>`tests/test_backend_read_api.py` |
| **Transport Network** | `src/nexus/transport/network.py`<br/>`src/nexus/transport/builder.py` | `src/nexus/transport/models.py` | `tests/test_transport.py` |
| **Telemetry Simulation** | `src/nexus/telemetry/generator.py`<br/>`src/nexus/telemetry/profiles.py`<br/>`src/nexus/telemetry/store.py`<br/>`src/nexus/telemetry/orchestrator.py` | `src/nexus/telemetry/models.py`<br/>`src/nexus/telemetry/schemas.py` | `tests/test_telemetry.py`<br/>`tests/test_backend_read_api.py` |
| **Fault Simulation** | `src/nexus/fault/engine.py`<br/>`src/nexus/fault/scenarios.py`<br/>`src/nexus/fault/service.py` | `src/nexus/fault/models.py`<br/>`src/nexus/fault/schemas.py` | `tests/test_fault.py`<br/>`tests/test_fault_integration.py` |
| **Anomaly Detection** | `src/nexus/detection/threshold_detector.py`<br/>`src/nexus/detection/statistical_detector.py`<br/>`src/nexus/detection/engine.py`<br/>`src/nexus/detection/rules.py` | `src/nexus/detection/models.py`<br/>`src/nexus/detection/schemas.py` | `tests/test_detection.py` |
| **Alarm Management** | `src/nexus/detection/alarm_manager.py`<br/>`src/nexus/detection/service.py` | `src/nexus/detection/models.py`<br/>`src/nexus/detection/schemas.py` | `tests/test_detection.py`<br/>`tests/test_backend_read_api.py` |
| **Alarm Correlation** | `src/nexus/correlation/engine.py` | `src/nexus/correlation/models.py` | `tests/test_correlation.py` |
| **Root Cause Analysis** | `src/nexus/rca/engine.py`<br/>`src/nexus/rca/rules.py` | `src/nexus/rca/models.py` | `tests/test_rca.py`<br/>`tests/test_rca_evaluation.py` |
| **Incident Management** | `src/nexus/incidents/service.py`<br/>`src/nexus/incidents/repository.py`<br/>`src/nexus/incidents/severity.py`<br/>`src/nexus/incidents/sla.py` | `src/nexus/incidents/models.py`<br/>`src/nexus/incidents/schemas.py`<br/>`src/nexus/incidents/enums.py` | `tests/test_incidents_domain.py`<br/>`tests/test_incidents_persistence.py`<br/>`tests/test_incidents_api.py` |
| **Real-Time Events & WS** | `src/nexus/events/broadcaster.py`<br/>`src/nexus/events/api.py` | `src/nexus/events/models.py` | `tests/test_websocket_events.py` |
| **Prometheus Metrics** | `src/nexus/metrics.py` | Bounded Prometheus Labels | `tests/test_prometheus_metrics.py` |
| **Evaluation Harness** | `src/nexus/evaluation/evaluator.py`<br/>`src/nexus/evaluation/scenario_replay.py` | `src/nexus/evaluation/models.py` | `tests/test_evaluation.py`<br/>`tests/test_ground_truth_isolation.py` |
| **Frontend Application** | `frontend/src/App.tsx`<br/>`frontend/src/api/client.ts`<br/>`frontend/src/websocket/client.ts`<br/>`frontend/src/pages/*` | `frontend/src/types/*` | `frontend/tests/api_client.test.ts`<br/>`frontend/tests/components.test.tsx`<br/>`frontend/tests/navigation.test.tsx`<br/>`frontend/tests/m7_end_to_end.test.tsx` |
| **Live Acceptance Script** | `scripts/verify_e2e_acceptance.py` | 25 Live Assertion Steps | `scripts/verify_e2e_acceptance.py` |
