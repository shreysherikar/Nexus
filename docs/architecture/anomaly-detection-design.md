# NEXUS Anomaly Detection & Alarm Generation Specification

## 1. Overview and Architectural Boundary

The `nexus.detection` package introduces deterministic, real-time anomaly detection and alarm lifecycle management over NEXUS synthetic telemetry.

### Ground-Truth Separation Principle

A core architectural invariant of NEXUS is the strict decoupling between detection and fault simulation:
- **`nexus.detection`**: Consumes only telemetry snapshots (`KPISnapshot`) and optional node metadata (`NodeType`). It has **zero knowledge** of whether faults exist, which nodes are affected, what fault types are active, or what ground-truth records were generated. It has no import dependency on `nexus.fault`.
- **`nexus.evaluation`**: A standalone evaluation package that consumes both generated alarms and `GroundTruthRecord` objects **exclusively for post-hoc benchmarking**.

```
+------------------------------------+
|  Synthetic Telemetry (KPISnapshot) |
+------------------+-----------------+
                   |
                   v
+------------------+-----------------+       +------------------------------------+
|       nexus.detection Subsystem    | ----> | Alarms (Active & Cleared Log)      |
|  - ThresholdDetector               |       +-----------------+------------------+
|  - StatisticalDetector (Med, EWMA) |                         |
|  - AlarmManager & Deduplication    |                         |
+------------------------------------+                         v
                                             +-----------------+------------------+
+------------------------------------+       |        nexus.evaluation Subsystem  |
|  Ground Truth (GroundTruthRecord)  | ----> |  - Matcher & Grace Period          |
+------------------------------------+       |  - Precision, Recall, F1, MTTD     |
                                             +------------------------------------+
```

---

## 2. Threshold-Based Detection

Threshold detection evaluates point-in-time metrics against configurable operational bounds defined in [`src/nexus/detection/rules.py`](../../src/nexus/detection/rules.py).

### Rule Specification

| Field | Type | Description |
| :--- | :--- | :--- |
| `rule_id` | `str` | Unique non-empty string identifier. |
| `metric_name` | `str` | Valid KPI name (`throughput_mbps`, `latency_ms`, `sinr_db`, etc.). |
| `operator` | `ComparisonOperator` | Comparison operator (`>`, `>=`, `<`, `<=`). |
| `threshold` | `float` | Finite real threshold value (booleans rejected). |
| `severity` | `Severity` | Assigned alarm severity (`WARNING`, `MAJOR`, `CRITICAL`). |
| `node_types` | `Optional[frozenset[NodeType]]` | Applicable node tiers (e.g. `CELL` only for radio metrics). |
| `clear_threshold` | `Optional[float]` | Recovery threshold defining the hysteresis clearing boundary. |
| `enabled` | `bool` | Toggle state for active rule evaluation. |
| `description` | `str` | Human-readable diagnostic description. |

### Hysteresis and Anti-Flapping Policy

To prevent alarm flapping when a metric oscillates near the trigger boundary, rules support a recovery threshold:
- **Upper-bound triggers (`>`, `>=`)**: Violation occurs when $\text{val} > \text{threshold}$. Recovery requires $\text{val} \le \text{clear\_threshold}$, where $\text{clear\_threshold} \le \text{threshold}$.
- **Lower-bound triggers (`<`, `<=`)**: Violation occurs when $\text{val} < \text{threshold}$. Recovery requires $\text{val} \ge \text{clear\_threshold}$, where $\text{clear\_threshold} \ge \text{threshold}$.
- Values between the recovery threshold and trigger threshold remain in their current alarm state.
- Missing metrics (e.g. non-cell nodes lacking radio metrics) are skipped; missing values are **never fabricated** or treated as recovery.

### Standard Telecom Baseline Rules

| Rule ID | Metric | Operator | Trigger | Clear | Severity | Target Tier |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `RULE-AVAIL-CRIT` | `availability_pct` | `<` | 95.0% | 98.0% | `CRITICAL` | All nodes |
| `RULE-DROP-CRIT` | `connection_drop_rate_pct` | `>` | 5.0% | 2.0% | `CRITICAL` | All nodes |
| `RULE-LAT-MAJOR` | `latency_ms` | `>` | 80.0 ms | 60.0 ms | `MAJOR` | All nodes |
| `RULE-PRB-MAJOR` | `prb_utilization_pct` | `>` | 85.0% | 75.0% | `MAJOR` | `CELL` nodes |
| `RULE-SINR-MAJOR` | `sinr_db` | `<` | 5.0 dB | 8.0 dB | `MAJOR` | `CELL` nodes |
| `RULE-RSRP-WARN` | `rsrp_dbm` | `<` | -115.0 dBm | -110.0 dBm | `WARNING` | `CELL` nodes |
| `RULE-TP-WARN` | `throughput_mbps` | `<` | 5.0 Mbps | 10.0 Mbps | `WARNING` | `CELL` nodes |
| `RULE-HOSR-MAJOR` | `handover_success_rate_pct` | `<` | 90.0% | 95.0% | `MAJOR` | `CELL` nodes |

---

## 3. Statistical Anomaly Detection

Statistical detection runs independently per `(node_id, metric_name)` tuple using two complementary time-series algorithms implemented in [`src/nexus/detection/statistical_detector.py`](../../src/nexus/detection/statistical_detector.py).

### A. Rolling Median & MAD

Maintains a fixed-size ring buffer of recent observations ($W \le \text{window\_size}$).

1. **Median ($M$)**:
   $$M = \text{median}(H)$$
2. **Median Absolute Deviation ($\text{MAD}$)**:
   $$\text{MAD} = \text{median}(\{|x_i - M| : x_i \in H\})$$
3. **Raw Scale & Effective Scale**:
   $$\text{raw\_scale} = 1.4826 \cdot \text{MAD}$$
   $$\text{effective\_scale} = \max\left(\text{raw\_scale},\; 0.05 \cdot \max(|M|, 1.0)\right)$$
4. **Deviation Score**:
   $$\text{score} = \frac{|x_t - M|}{\text{effective\_scale}}$$
5. **Anomaly Condition**:
   $$\text{score} \ge \text{median\_deviation\_threshold}$$

Both $\text{raw\_scale}$ and $\text{effective\_scale}$ are preserved in the `AnomalyEvent` evidence so that $\text{score} = \text{deviation} / \text{effective\_scale}$ is independently verifiable.

The $0.05 \cdot \max(|M|, 1.0)$ minimum scale floor ensures that completely constant historical baselines with zero variance handle sudden shifts gracefully without division by zero.

### B. Exponentially Weighted Moving Average (EWMA)

Tracks recursive exponential baselines and sample variance:

1. **Recursive Formulation**:
   $$\text{EWMA}_t = \alpha \cdot X_t + (1 - \alpha) \cdot \text{EWMA}_{t-1}$$
   $$\sigma^2_t = \alpha \cdot (X_t - \text{EWMA}_{t-1})^2 + (1 - \alpha) \cdot \sigma^2_{t-1}$$
2. **Raw Spread & Effective Spread**:
   $$\text{raw\_spread} = \sqrt{\max(0.0, \sigma^2_{t-1})}$$
   $$\text{effective\_spread} = \max\left(\text{raw\_spread},\; 0.05 \cdot \max(|\text{EWMA}_{t-1}|, 1.0)\right)$$
3. **Z-Score Deviation**:
   $$Z_t = \frac{|X_t - \text{EWMA}_{t-1}|}{\text{effective\_spread}}$$
4. **Anomaly Condition**:
   $$Z_t \ge \text{ewma\_sensitivity}$$

Both $\text{raw\_spread}$ and $\text{effective\_spread}$ are preserved in the `AnomalyEvent` evidence so that $Z_t = \text{diff} / \text{effective\_spread}$ is independently verifiable.

### Warmup and Shared Contamination Policy

- **Warmup Period**: Anomalies are suppressed during the initial $N$ observations ($\text{warmup\_count}$) per `(node_id, metric_name)` to allow baselines and variance to stabilize.
- **Shared Contamination Prevention (Evaluate-Then-Commit)**:
  When both statistical detectors (Rolling Median and EWMA) are enabled:
  1. Both detectors independently evaluate the incoming observation against their **pre-observation baseline states** in read-only mode without mutating history.
  2. If **either** enabled method flags the sample as anomalous, the sample is excluded from **BOTH** rolling median and EWMA baseline updates.
  3. If **neither** enabled method flags the sample, the sample updates both enabled baselines.
  4. If both flag, both emit independent `AnomalyEvent` instances, preserving diagnostic clarity while protecting all baselines from contamination.
  5. Disabled detectors do not participate in anomaly decisions or baseline updates.
- **Known Limitation**: If a permanent structural improvement or capacity change occurs (e.g. throughput doubling from a hardware upgrade), the detector will treat the persistent shift as anomalous until the detector's state is reset (`reset_node()` or `reset()`).

---

## 4. Alarm Identity and Lifecycle Management

Defined in [`src/nexus/detection/models.py`](../../src/nexus/detection/models.py) and [`src/nexus/detection/alarm_manager.py`](../../src/nexus/detection/alarm_manager.py).

### Deduplication Identity

Each alarm has a deterministic deduplication composite key:
$$\text{key} = (\text{node\_id}, \text{metric\_name}, \text{rule\_id}, \text{source})$$
This guarantees that two different rules monitoring the same metric (e.g. Warning vs Critical, or Threshold vs Statistical) maintain independent lifecycle states.

### Lifecycle State Machine

```
      +-------------+
      |  No Alarm   |
      +------+------+
             |
             | Anomaly detected (is_new = True)
             v
      +-------------+  Anomaly recurs
      |   ACTIVE    | ------------+
      +------+------+             |
             |       <------------+ (last_seen updated, count += 1)
             |
             | Recovery condition satisfied (is_cleared = True)
             v
      +-------------+
      |   CLEARED   | (Preserved in audit history)
      +------+------+
             |
             | Same condition recurs later
             v
      (New Alarm created with new alarm_id)
```

1. **Raise**: On first observation, a unique `alarm_id` is assigned, `status = ACTIVE`, and `observation_count = 1`.
2. **Update**: On subsequent contiguous observations, `first_seen` is preserved, `last_seen` is updated to the current timestamp, and `observation_count` increments.
3. **Clear**: When a subsequent snapshot contains the metric and meets the clear threshold, `status = CLEARED`, `cleared_at` is set, and the alarm is archived into historical logs.
4. **Reappearance**: If the anomaly recurs after clearing, a new alarm is generated with a fresh `alarm_id`, preserving full historical traceability.

### Evidence Immutability

Both `AnomalyEvent` and `Alarm` defensively freeze diagnostic evidence structures upon construction using `_freeze_evidence`:
- Nested mappings are converted recursively into `types.MappingProxyType`.
- Collections (lists, sets) are recursively converted into immutable `tuple` and `frozenset` structures.
- Direct mutations (e.g. `event.evidence['k'] = v` or `alarm.evidence['nested']['k'] = v`) raise `TypeError`.
- Mutating the caller's source dictionary after passing it to an event or alarm has zero effect on the stored object.
- Queries such as `AlarmManager.get_active_alarms()`, `get_cleared_alarms()`, and `get_all_alarms()` return alarms whose evidence cannot be mutated.

### Transactional Alarm Clearing

`AlarmManager.clear_alarm()` enforces transactional state mutation:
- The clearing timestamp is validated first: it must be a valid datetime and cannot be earlier than `active.last_seen`.
- The cleared `Alarm` instance is fully constructed and validated prior to mutating any internal collection.
- Only upon successful creation is the alarm removed from `_active_alarms` and appended to `_cleared_history`.
- On any validation failure, the active alarm remains unchanged in `_active_alarms`, and history remains unmodified.

---

## 5. Detection Engine Coordinator

Implemented in [`src/nexus/detection/engine.py`](../../src/nexus/detection/engine.py), the `AnomalyDetectionEngine` coordinates all detectors and enforces batch safety.

### Ingestion Requirements & Transactional Atomicity Guarantee

1. **Input Pre-Validation**: Prior to processing any snapshot in a batch:
   - The sequence of snapshots is validated for type integrity and strictly monotonic chronological order per node.
   - The optional `node_types` mapping is validated: all keys must be non-empty strings, and values must be valid `NodeType` enum instances or valid case-insensitive string names (e.g. `"cell"` -> `NodeType.CELL`). Invalid types immediately raise `DetectionError`.
2. **Duplicate Rejection**: Duplicate observations for the same node and timestamp within a batch or stream raise `DuplicateObservationError`.
3. **Transactional Batch Rollback**:
   - Before executing the batch loop, the engine creates an in-memory snapshot of its state: `_last_node_timestamps`, `_statistical_detector` internal baselines, and `_alarm_manager` active alarms/history.
   - If an unexpected error occurs during processing of any snapshot, the engine restores all states to their pre-batch snapshot and re-raises the error.
   - A failed batch leaves zero partial detector baselines, partial alarms, or corrupted timestamps behind.
4. **Missing Metric Safety**: If a snapshot lacks certain metrics (e.g. non-cell nodes lacking radio metrics), detectors evaluate only the metrics present and never fabricate zeros or clear existing alarms.

---

## 6. Post-Detection Ground Truth Evaluation

The evaluation subsystem in [`src/nexus/evaluation/`](../../src/nexus/evaluation/) compares generated alarms against `GroundTruthRecord` objects produced by the fault engine.

### Alarm Deduplication

Alarms are deduplicated by `alarm_id` prior to evaluation. Passing duplicate alarm objects or copies does not inflate alarm counts.

### Matching Policy & Overlapping Faults

An alarm $A$ is eligible to match an injected fault $G$ iff:
1. $A.\text{node\_id} \in G.\text{affected\_node\_ids}$.
2. $G.\text{start\_time} \le A.\text{first\_seen} \le G.\text{end\_time} + \Delta_{\text{grace}}$, where $\Delta_{\text{grace}}$ is the configured detection grace period (default 60s).

**Overlapping Faults**: When two or more ground-truth faults overlap in time and share impacted nodes (e.g. a backhaul cut and cell outage both impacting the same cell), an alarm on that shared node within the overlap window matches all overlapping faults it is eligible for (each fault is marked detected). In alarm precision counting, the unique alarm is counted **once** as a True Positive, avoiding double-counting or alarm inflation.

### Metric Definitions

Evaluation explicitly distinguishes alarm-level precision from fault-level recall:
- **Fault-Level Recall (`fault_recall`, alias `recall`)**:
  $$\text{fault\_recall} = \frac{\text{detected\_faults}}{\text{total\_faults}}$$
  Proportion of injected ground-truth fault events that generated at least one eligible alarm.
- **Alarm-Level Precision (`alarm_precision`, alias `precision`)**:
  $$\text{alarm\_precision} = \frac{\text{unique\_true\_positive\_alarms}}{\text{total\_unique\_alarms}}$$
  Proportion of unique alarms that corresponded to real injected faults.
- **Hybrid F1 Score (`hybrid_f1_score`, alias `f1_score`)**:
  $$\text{hybrid\_f1\_score} = 2 \cdot \frac{\text{alarm\_precision} \cdot \text{fault\_recall}}{\text{alarm\_precision} + \text{fault\_recall}}$$
  Calculated as the harmonic mean of alarm-level precision and fault-level recall. Note: This combines two different counting units (alarms vs faults) and is explicitly documented as a hybrid tradeoff score rather than a conventional single-unit F1 score.
- **Fault-Level Mean Time to Detect (MTTD)**:
  For each detected fault $i$, $\text{TTD}_i = \max\left(0.0, (A_{\text{earliest}}.\text{first\_seen} - G_i.\text{start\_time}).\text{total\_seconds}()\right)$.
  $$\text{MTTD} = \frac{1}{K} \sum_{i=1}^K \text{TTD}_i$$
  Calculated using the earliest matching alarm for each detected fault, averaged across all detected faults.

### Replay Evaluator Helper

The `ScenarioReplayEvaluator` coordinates benchmark runs:
1. Feeds synthetic telemetry snapshots (normal or fault-adjusted) into the engine.
2. Retrieves all active and cleared alarms.
3. Compares alarms against ground truth.
4. Returns both the batch result and the comprehensive `EvaluationReport`.

---

## 7. Limitations & Telecommunication Assumptions

1. **Symptom vs Root Cause**: Node and time matching proves anomaly detection on an affected node, but does not identify the underlying root-cause fault. For instance, a backhaul cut produces availability anomalies on downstream cells; detecting the cell outage confirms detection sensitivity but does not isolate the broken backhaul link. Root-cause correlation and alarm topology graph analysis are addressed in Milestone 5.
2. **Single-Node Detection**: Detectors analyze nodes individually. Cross-node correlation across the topology tree occurs downstream.
3. **Contamination Tradeoff**: Excluding anomalies from baseline updates prevents baseline contamination during acute faults, but requires explicit resets if the network undergoes permanent structural improvements.
