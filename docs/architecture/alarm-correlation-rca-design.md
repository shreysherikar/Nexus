# NEXUS Alarm Correlation & Root Cause Analysis (RCA) Specification

## 1. Overview and Architectural Boundaries

Milestone 5 introduces two independent domain subsystems to NEXUS:
- **`nexus.correlation`**: Clusters disparate point-in-time alarm records into coherent, immutable correlation groups based on temporal proximity, topological hierarchy, and symptom compatibility.
- **`nexus.rca`**: Evaluates correlation groups against explainable diagnostic rules to determine ranked root-cause hypotheses, suspect targets (nodes or transport links), confidence scores, and actionable operational recommendations.
- **`nexus.evaluation`** (extension): Benchmarks both correlation grouping effectiveness (noise reduction ratio) and RCA diagnostic accuracy (top-1 cause accuracy, target accuracy, coverage) against injected ground-truth fault events.

```
+-------------------------------------------------------------+
|                 nexus.detection Subsystem                   |
|  - AnomalyDetectionEngine / AlarmManager                    |
+------------------------------+------------------------------+
                               |
                               | Sequence[Alarm]
                               v
+-------------------------------------------------------------+
|                nexus.correlation Subsystem                  |
|  - AlarmCorrelationEngine                                   |
|  - LCA & Near-Ancestor Preference                           |
|  - Distant CORE Rejection & Symptom Compatibility           |
|  - Noise Reduction & Singleton Preservation                 |
+------------------------------+------------------------------+
                               |
                               | CorrelationResult (CorrelationGroup)
                               v
+-------------------------------------------------------------+
|                     nexus.rca Subsystem                     |
|  - RootCauseAnalysisEngine                                  |
|  - Rule Evaluators (Backhaul, Power, RF, Congestion, Outage) |
|  - Deterministic Ranking, Tie-Breakers, UNKNOWN Fallback    |
|  - Actionable Remediation Guidance                          |
+------------------------------+------------------------------+
                               |
                               | Sequence[RCAResult]
                               v
+-------------------------------------------------------------+
|                nexus.evaluation Subsystem                   |
|  - evaluate_rca()                                           |
|  - Benchmarking against GroundTruthRecord Sequence          |
|  - Metrics: Top-1 Accuracy, Target Accuracy, Coverage, NRR   |
+-------------------------------------------------------------+
```

### Ground-Truth Separation Principle

Strict architectural isolation is enforced at import and runtime boundaries:
- `nexus.correlation` and `nexus.rca` **never** import, inspect, or depend upon `nexus.fault`, `GroundTruthRecord`, or scenario definitions.
- All correlation and root-cause decisions are derived exclusively from observable signals: alarm timestamps, node locations, metric names, current values, static topology/transport graph relationships, and observed telemetry snapshots.
- `nexus.evaluation` is the only component that accesses both ground truth and engine outputs, performing post-hoc verification.

---

## 2. Alarm Correlation Architecture (`nexus.correlation`)

### 2.1 Configuration (`CorrelationConfig`)

| Field | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `time_window_seconds` | `float` | `300.0` | Maximum time difference between alarm onsets to consider correlation. |
| `max_ancestor_distance` | `int` | `2` | Maximum hierarchy levels to search for shared dependency (Cell -> Site = 1, Cell -> Aggregation = 2). |
| `group_singletons` | `bool` | `True` | Whether isolated alarms form independent singleton `CorrelationGroup` instances. |

### 2.2 Correlation Grouping Policy

The `AlarmCorrelationEngine` correlates alarms based strictly on topological hierarchy (lineage, Lowest Common Ancestor, and parent-child/sibling relationships) and symptom compatibility. Transport link dependencies and routing paths are intentionally resolved downstream during Root Cause Analysis (RCA), where link-level targets are identified; the correlation engine relies on the topology hierarchy rather than transport routing.

To prevent uncontrolled transitive time-window chaining, the engine enforces a strict **maximum onset-time span invariant**:
For every formed correlation group, $\max(a.\text{first\_seen}) - \min(a.\text{first\_seen}) \le \text{time\_window\_seconds}$.

Pairwise alarms `(a1, a2)` are evaluated for compatibility:
1. **Temporal Proximity**: `|a1.first_seen - a2.first_seen| <= time_window_seconds`.
2. **Same Node Affinity**: If `a1.node_id == a2.node_id`, alarms within the time window always correlate.
3. **Lowest Common Ancestor (LCA)**:
   - Evaluates the nearest shared ancestor in the topology hierarchy (`_find_lca`).
   - The maximum distance from either node to the LCA must not exceed `max_ancestor_distance`.
4. **Distant Ancestor (CORE) Protection**:
   - If the LCA is `NodeType.CORE`, alarms are **rejected** from merging unless at least one alarm is directly on the `CORE` node itself. This prevents unrelated failures on independent aggregation branches from erroneously collapsing into a monolithic group.
5. **Symptom Compatibility**:
   - Localized RF metrics (`sinr_db`, `rsrp_dbm`) and radio resource metrics (`prb_utilization_pct`) represent strictly local sector phenomena. Across different nodes, localized metrics **never** correlate with another node.
   - Across different nodes, correlation requires both alarms to exhibit systemic network degradation metrics (`availability_pct`, `latency_ms`, `throughput_mbps`, `connection_drop_rate_pct`, `handover_success_rate_pct`).

Graph components are formed such that expanding a component to include an alarm is allowed only if adding the alarm does not cause the group's total onset span to exceed `time_window_seconds`. If adding an edge would exceed this span, the alarm is deferred to a subsequent group.

### 2.3 Group Structure and Immutability (`CorrelationGroup`)

Each `CorrelationGroup` is an immutable, frozen dataclass containing:
- `group_id`: Deterministic identifier formatted as `CORR-<anchor>-<timestamp>-<index>`.
- `anchor_node_id`: Nearest common ancestor node in the topology hierarchy.
- `root_cause_tier`: Topology tier of the anchor (`NodeType.SITE`, `NodeType.AGGREGATION`, `NodeType.CORE`, or `None`).
- `alarms`: Ordered tuple of immutable `Alarm` instances.
- `alarm_ids` and `node_ids`: Sorted tuples of unique alarm and node identifiers.
- `time_window_start` and `time_window_end`: Span covering all constituent alarms.
- `correlation_reason`: Human-readable summary of the correlation rationale.
- `evidence`: Read-only mapping proxy capturing alarm counts, impacted nodes, and metric sets.

---

## 3. Root Cause Analysis Architecture (`nexus.rca`)

### 3.1 Diagnostic Rule Evaluators & Telemetry Freshness Policy

Observed telemetry (`KPISnapshot`) actively participates in root-cause diagnosis.
The `RootCauseAnalysisEngine` deterministically selects relevant snapshots per node using the following freshness and past-observation policy:
- **Reference Timestamp**: All telemetry freshness is evaluated strictly relative to `analysis_timestamp` (or `group.time_window_end` if unspecified).
- **Strict Past/Present Constraint (No Future Look-Ahead)**: Historical replay and online triage must never benefit from unobservable future information. Any snapshot with `timestamp > analysis_timestamp` is strictly discarded.
- **Maximum Staleness Floor**: A snapshot is fresh if and only if its timestamp satisfies: `analysis_timestamp - max_staleness_seconds <= snapshot.timestamp <= analysis_timestamp`. Snapshots older than this window are discarded as stale. If the latest past observation for a node is stale, it is discarded even if older observations exist.
- **Deterministic Selection**: For each node with one or more eligible fresh snapshots, the snapshot with the largest timestamp (latest observation) is selected. Ties are broken by earlier index.
- Each piece of evidence generated by rules is explicitly tagged with `evidence_source`: `"ALARM"`, `"SNAPSHOT"`, or `"TOPOLOGY"`.

The RCA subsystem implements five explainable, deterministic rule evaluators with strict diagnostic thresholds:

| Pattern | Rule Evaluator | Suspected Cause | Suspected Target | Target Type | Diagnostic Thresholds & Evidence Requirements |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Backhaul Failure** | `evaluate_backhaul_failure` | `BACKHAUL_FAILURE` | Transport link ID (e.g. `LINK-AGG-01-SITE-01`) | `TRANSPORT_LINK` | Requires observed transport degradation: elevated latency (> 50 ms) and/or collapsed throughput (< 20 Mbps) or severe availability collapse (<= 10%). Multi-node branch impact strictly requires at least two distinct affected nodes in the relevant branch supported by qualifying transport alarms or telemetry; unrelated alarms (e.g. SINR) do not count. Anchor tier alone never awards multi-node credit. Link structural existence awards strong support (+0.20) only when observed multi-node branch impact exists; single-cell conditions receive minimal structural score (+0.05). |
| **Site Power Failure** | `evaluate_site_power_failure` | `SITE_POWER_FAILURE` | Site node ID (e.g. `SITE-04`) | `NODE` | Requires severe availability collapse (<= 10%) across multiple descendant child cells under the site. Mild availability reduction (> 10%) does not qualify. Blackout (0%) adds confidence. |
| **Radio Interference** | `evaluate_radio_interference` | `RADIO_INTERFERENCE` | Cell node ID (e.g. `CELL-05`) | `NODE` | Requires genuine SINR degradation (alarm on sinr_db with current_value < 10 dB or snapshot sinr_db < 10 dB). Normal-valued SINR alarms (>= 10 dB) and RSRP degradation alone do NOT qualify. Telemetry showing severe availability collapse (<= 10%) contradicts interference and causes rejection. High PRB (>= 80%) cancels PRB counter-indicator credit. Sibling health is verified via telemetry or marked unverified. |
| **Cell Congestion** | `evaluate_cell_congestion` | `CELL_CONGESTION` | Cell node ID (e.g. `CELL-10`) | `NODE` | Requires actual PRB utilization >= 80% AND independently observed performance degradation: latency_ms > 30 ms or throughput_mbps < 50 Mbps (via alarm or snapshot). If performance is normal or unobserved, returns None. Radio environment verified clean via snapshot (SINR >= 10 dB) or marked unverified. |
| **Cell Outage** | `evaluate_cell_outage` | `CELL_OUTAGE` | Cell node ID (e.g. `CELL-01`) | `NODE` | Treats severe availability collapse (<= 10.0%) and near-zero throughput (< 1.0 Mbps) as separate evidence paths. Availability points (+0.40) are not awarded for throughput-only evidence (+0.35). Requires complete sibling coverage (observed == expected) for full isolation credit (+0.25); partial coverage receives partial credit (+0.10); unhealthy siblings receive zero isolation credit; no telemetry retains unverified (+0.05). Host site operational status is claimed only with direct site-level telemetry; missing site telemetry is explicitly stated as unverified; evidence of wider site outage qualifies the hypothesis rather than describing it as isolated. |

### 3.2 Additive Scoring Model

Each rule evaluator computes a heuristic confidence score strictly bounded in $[0.0, 1.0]$ based on additive evidence weights:
- **Primary symptom match** (e.g. latency spike, availability collapse, SINR drop): $+0.25$ to $+0.35$.
- **Critical severity threshold** (e.g. availability == 0.0, PRB > 90%): $+0.20$ to $+0.25$.
- **Topological branch coverage** (e.g. multiple children affected under site): $+0.25$ to $+0.30$.
- **Structural dependency verification** (e.g. upstream transport link identified, sibling health confirmed): $+0.15$ to $+0.25$.
- **Absence of contradictory symptoms** (e.g. clean radio RF during congestion): $+0.10$.

### 3.3 Deterministic Ranking and UNKNOWN Policy

For each correlation group:
1. All candidate hypotheses scoring $\ge 0.35$ are deduplicated by `(cause_type, target_id)`.
2. Hypotheses are sorted deterministically using the following composite key:
   - Primary: `confidence_score` descending (`-h.confidence_score`).
   - Secondary: `evidence_items` count descending (`-len(h.evidence_items)`).
   - Tertiary: `target_id` ascending alphabetical.
   - Quaternary: `cause_type.value` ascending alphabetical.
3. **UNKNOWN Fallback**: If no rule scores $\ge min\_confidence\_threshold$ (default `0.35`), the engine emits an explicit `RootCauseHypothesis` with:
   - `cause_type = RootCauseType.UNKNOWN`
   - `target_type = TargetType.UNKNOWN`
   - `confidence_score = 0.0`
   - `explanation = "Insufficient diagnostic evidence to establish a definitive root cause hypothesis."`
   - Recommended action directing tier-2 manual triage.

### 3.4 Operational Remediation Guidance

Each hypothesis provides standard operational next-step guidance:
- `BACKHAUL_FAILURE`: "Inspect physical transport link and verify optical transceivers / fiber continuity."
- `SITE_POWER_FAILURE`: "Verify facility grid power supply, backup battery voltage, and generator transfer switch."
- `RADIO_INTERFERENCE`: "Initiate spectrum analysis sweep to identify and locate external RF interference sources."
- `CELL_CONGESTION`: "Activate carrier aggregation and dynamic traffic offload to mitigate PRB saturation."
- `CELL_OUTAGE`: "Power-cycle radio unit / baseband module and verify antenna feeder connections."
- `UNKNOWN`: "Gather detailed diagnostic traces and assign to Tier-2 operations for triage."

---

## 4. Evaluation Framework (`nexus.evaluation`)

### 4.1 Benchmark Evaluation Function (`evaluate_rca`)

```python
def evaluate_rca(
    ground_truth: Sequence[GroundTruthRecord],
    rca_results: Sequence[RCAResult],
    correlation_result: Optional[CorrelationResult] = None,
    grace_period_seconds: float = 60.0,
    transport: Optional[TransportNetwork] = None,
) -> RCAEvaluationReport:
```

### 4.2 Ground-Truth-Independent Matching & Target Semantics Policy

Candidates are matched using pure spatio-temporal affinity without inspecting diagnostic correctness or ground truth:
1. **Spatial Overlap**: Number of group nodes intersecting the fault's affected node set (higher is better).
2. **Temporal Proximity**: Minimal absolute time delta between group onset and fault start time (`-abs(group_start - fault_start)`).
3. **Symptom Density**: Total alarm count within the candidate group (higher is better).
4. **Deterministic Tie-Breakers**: Group onset timestamp and unique group identifier.

Ground-truth correctness is strictly evaluated **after** candidate selection:
- `cause_correct`: Diagnosed primary cause matches `fault.fault_type.value` and is not `UNKNOWN`.
- `target_correct`: Evaluated with explicit node vs. transport link semantics:
  - If diagnosed target and expected target match identically: `target_correct = True`.
  - If diagnosis targets a transport link and ground truth targets a node:
    - If `transport` is provided: `target_correct = (link.downstream_node_id == expected_target)`.
    - If `transport` is omitted: `target_correct = None`, `target_verifiable = False`, and `report.unevaluable_target_count` increments.
  - If diagnosis targets a node and ground truth targets a transport link:
    - If `transport` is provided: `target_correct = False` (node != link).
    - If `transport` is omitted: `target_correct = None`, `target_verifiable = False`.
  - If targets are of the same type but differ: `target_correct = False`.
- `both_correct`: `True` if and only if `cause_correct is True` and `target_correct is True`.
- `is_unknown`: `True` if diagnosis concluded `UNKNOWN` or no matching group was found.
- `target_verifiable`: `False` when target verification cannot be determined due to missing transport topology.

### 4.3 Metrics Summary (`RCAEvaluationReport`)

- `top_1_cause_accuracy`: `correct_cause_count / total_faults` (1.0 if `total_faults == 0`).
- `target_accuracy`: `correct_target_count / total_faults`.
- `both_accuracy`: `correct_both_count / total_faults`.
- `diagnosis_coverage`: `diagnosed_faults / total_faults` (proportion receiving non-UNKNOWN diagnosis).
- `alarm_reduction_ratio`: `(total_alarms - total_groups) / total_alarms`.
- `unevaluable_target_count`: Number of fault matches where target correctness could not be evaluated due to omitted transport topology.

---

## 5. Known Assumptions and Limitations

1. **Static Transport Mapping**: Transport link correlation relies on static link endpoints defined in `TransportNetwork`. Dynamic routing changes or multi-path rerouting are out of scope.
2. **Simultaneous Power vs. Backhaul Disambiguation**: In scenarios where a physical link cut causes downstream nodes to become completely unresponsive, telemetry snapshots reflect total availability loss identical to power blackout. In such dual-symptom situations, both hypotheses score highly as co-primary diagnostic candidates.
3. **Batch-Oriented Processing**: Correlation and RCA operate on supplied batches of alarms and snapshots. Streaming sliding-window correlation across indefinite continuous streams is deferred to future telemetry pipeline milestones.
