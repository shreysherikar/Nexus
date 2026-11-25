# NEXUS — Complete System Architecture & Diagrams

**Document Identifier**: `NEXUS-ARCH-2026-V1`  
**Target Repository**: `https://github.com/shreysherikar/Nexus`  
**Classification**: Engineering Architecture Specification & Diagram Reference  
**Platform Version**: `1.0.0`  

---

## Table of Contents

1. [High-Level Platform Architecture](#1-high-level-platform-architecture)
2. [Backend Subsystem & Service Architecture](#2-backend-subsystem--service-architecture)
3. [Database Entity-Relationship (ER) Architecture](#3-database-entity-relationship-er-architecture)
4. [27-Node Hierarchical Network Topology & Transport Map](#4-27-node-hierarchical-network-topology--transport-map)
5. [Telemetry Generation & Orchestration Pipeline](#5-telemetry-generation--orchestration-pipeline)
6. [Anomaly Detection & Baseline Protection Flow](#6-anomaly-detection--baseline-protection-flow)
7. [Alarm State Machine & Lifecycle Transitions](#7-alarm-state-machine--lifecycle-transitions)
8. [Topology-Aware Lowest Common Ancestor (LCA) Correlation Algorithm](#8-topology-aware-lowest-common-ancestor-lca-correlation-algorithm)
9. [Root Cause Analysis (RCA) Multi-Hypothesis Diagnostic Flow](#9-root-cause-analysis-rca-multi-hypothesis-diagnostic-flow)
10. [Incident Lifecycle & State Machine Transitions](#10-incident-lifecycle--state-machine-transitions)
11. [Real-Time WebSocket Stream & Concurrency Sequence](#11-real-time-websocket-stream--concurrency-sequence)
12. [Application Lifespan & Subsystem Startup Sequence](#12-application-lifespan--subsystem-startup-sequence)
13. [Full End-to-End Operational Incident Lifecycle Sequence](#13-full-end-to-end-operational-incident-lifecycle-sequence)
14. [Docker Multi-Container Deployment Architecture](#14-docker-multi-container-deployment-architecture)
15. [Automated CI/CD Workflow Pipeline](#15-automated-cicd-workflow-pipeline)

---

## 1. High-Level Platform Architecture

The following diagram represents the end-to-end distributed topology of the NEXUS platform, spanning the simulation engine, diagnostic layer, persistence tier, real-time dispatch, frontend single-page application (SPA), and Prometheus/Grafana observability stack.

```mermaid
flowchart TD
    subgraph Client_Tier ["Operational Presentation Tier"]
        UI["NOC Web Console<br/>(React 18 / TypeScript / Vite / Tailwind)"]
        GRAF["Grafana Observability<br/>(v10.4.0 / 5 Dashboards)"]
    end

    subgraph Ingress_Tier ["Ingress & Reverse Proxy Tier"]
        NGINX["Nginx Alpine Gateway<br/>(Port 80 / Reverse Proxy)"]
        UI -.->|"HTTP Static Bundle"| NGINX
    end

    subgraph Backend_Tier ["NEXUS Application Server (FastAPI / ASGI)"]
        API["FastAPI REST Routing & Middlewares<br/>(/api/v1, /health, /ready, /metrics)"]
        WS_HUB["WebSocket Ingress Controller<br/>(/ws/live)"]
        BROADCAST["Event Broadcaster<br/>(nexus.events.broadcaster)"]
        PIPELINE["Telemetry Pipeline Orchestrator<br/>(nexus.telemetry.orchestrator)"]
        SIM["Synthetic Telemetry Generator<br/>(nexus.telemetry.generator)"]
        STORE["In-Memory TelemetryStore<br/>(Sliding Window Buffer - 60 samples/node)"]
        FAULT["Fault Scenario Engine<br/>(nexus.fault.engine)"]
        DET["Anomaly Detection Engine<br/>(Thresholds, Median/MAD, EWMA)"]
        ALARM_MGR["Alarm Manager<br/>(nexus.detection.alarm_manager)"]
        CORR["Topology-Aware Correlation Engine<br/>(nexus.correlation.engine - LCA)"]
        RCA["Root Cause Analysis Engine<br/>(nexus.rca.engine)"]
        INC_SVC["Incident Domain Service<br/>(nexus.incidents.service)"]
        PROM_METRICS["Prometheus Metrics Manager<br/>(nexus.metrics)"]
    end

    subgraph Persistence_Tier ["Durable Storage Tier"]
        PG[(PostgreSQL 15 Alpine<br/>nexus_db / SQLAlchemy 2.x / Alembic)]
    end

    subgraph Observability_Tier ["Telemetry & Metrics Tier"]
        PROM["Prometheus TSDB Scraper<br/>(v2.51.0 / Scrape Interval: 5s)"]
    end

    %% Client Interactions
    UI -->|"HTTP API Queries (/api/v1)"| API
    UI -->|"WebSocket Connection (/ws/live)"| WS_HUB
    GRAF -->|"PromQL Scrapes"| PROM
    PROM -->|"GET /metrics (Interval: 5s)"| API

    %% Internal Data Flow
    PIPELINE -->|"Trigger Step"| SIM
    SIM -->|"Raw Metrics"| FAULT
    FAULT -->|"Transformed Snapshots"| STORE
    STORE -->|"New Snapshots"| DET
    STORE -->|"Broadcast Event"| BROADCAST
    DET -->|"Violations & Recoveries"| ALARM_MGR
    ALARM_MGR -->|"Active Alarms"| CORR
    ALARM_MGR -->|"Alarm Lifecycle Events"| BROADCAST
    CORR -->|"Correlation Groups"| RCA
    RCA -->|"Ranked Hypotheses"| INC_SVC
    INC_SVC -->|"Durable Transactions"| PG
    INC_SVC -->|"Incident Lifecycle Events"| BROADCAST
    BROADCAST -->|"Thread-Safe Queue Fan-Out"| WS_HUB
    WS_HUB -->|"JSON Frame Delivery"| UI
    API -->|"Prometheus Instrumentation"| PROM_METRICS
```

---

## 2. Backend Subsystem & Service Architecture

The NEXUS backend is structured as a decoupled, modular monolith where subsystems communicate via typed domain contracts.

```mermaid
classDiagram
    direction TB

    class TopologyRegistry {
        +Topology _topology
        +all_nodes() list[Node]
        +get_node(node_id) Node
        +get_children(node_id) list[Node]
        +add_status_listener(callback)
    }

    class TransportNetwork {
        +dict links
        +get_link(link_id) TransportLink
        +get_link_between(u, v) TransportLink
        +get_downstream_nodes(link_id) list[str]
    }

    class TelemetryStore {
        +deque buffer
        +record(snapshot)
        +query(filters) tuple
        +get_latest_for_node(node_id) KPISnapshot
    }

    class AnomalyDetectionEngine {
        +ThresholdDetector threshold_detector
        +StatisticalDetector statistical_detector
        +evaluate_snapshot(snapshot) list[AnomalyEvent]
        +check_recovery(snapshot) list[Alarm]
    }

    class AlarmManager {
        +dict active_alarms
        +list cleared_history
        +process_anomaly(event) tuple[Alarm, bool]
        +clear_alarm(key, timestamp) Alarm
    }

    class AlarmCorrelationEngine {
        +correlate_alarms(alarms, topology) CorrelationResult
        -_find_lca(node_a, node_b)
        -_are_symptoms_compatible(a1, a2)
    }

    class RootCauseAnalysisEngine {
        +analyze_group(group, topology, transport, snapshots) RCAResult
        +evaluate_backhaul_failure()
        +evaluate_site_power_failure()
        +evaluate_core_router_failure()
        +evaluate_radio_interference()
        +evaluate_cell_congestion()
        +evaluate_cell_outage()
    }

    class IncidentService {
        +IncidentRepository repository
        +OperationalSeverityPolicy severity_policy
        +SLACalculator sla_calculator
        +create_or_update_incident(group, rca) Incident
        +acknowledge_incident(id, actor) Incident
        +resolve_incident(id, actor, notes) Incident
    }

    class EventBroadcaster {
        +dict subscribers
        +register(connection) asyncio.Queue
        +unregister(connection)
        +broadcast(event) int
    }

    TopologyRegistry <-- TransportNetwork : validates endpoints against
    TopologyRegistry <-- TelemetryStore : enriches tier data
    TelemetryStore --> AnomalyDetectionEngine : feeds snapshots
    AnomalyDetectionEngine --> AlarmManager : submits anomalies
    AlarmManager --> AlarmCorrelationEngine : provides active alarms
    TopologyRegistry <-- AlarmCorrelationEngine : traverses tree hierarchy
    AlarmCorrelationEngine --> RootCauseAnalysisEngine : delivers clusters
    TransportNetwork <-- RootCauseAnalysisEngine : queries link dependencies
    RootCauseAnalysisEngine --> IncidentService : provides diagnoses
    IncidentService --> EventBroadcaster : publishes incident events
    AlarmManager --> EventBroadcaster : publishes alarm events
    TelemetryStore --> EventBroadcaster : publishes telemetry events
```

---

## 3. Database Entity-Relationship (ER) Architecture

The persistent storage tier models operational incident state, RCA findings, and an append-only immutable audit history in PostgreSQL.

```mermaid
erDiagram
    incidents ||--o{ incident_timeline_events : "has audit history (1:N)"

    incidents {
        VARCHAR(64) incident_id PK "Unique identifier (INC-xxxxxxxxxxxx)"
        VARCHAR(128) correlation_group_id UK "Unique correlation group reference"
        VARCHAR(32) status "OPEN | ACKNOWLEDGED | RESOLVED (Indexed)"
        VARCHAR(32) severity "CRITICAL | MAJOR | WARNING | MINOR (Indexed)"
        VARCHAR(16) priority "P1 | P2 | P3 | P4"
        VARCHAR(256) title "Human-readable operational summary"
        TEXT description "Detailed diagnostic explanation"
        JSON alarm_ids "List of contributing alarm IDs"
        JSON affected_node_ids "List of impacted topology node IDs"
        VARCHAR(64) suspected_cause_type "RootCauseType enum string"
        VARCHAR(128) suspected_target_id "Identifier of root cause node/link"
        VARCHAR(32) suspected_target_type "NODE | TRANSPORT_LINK | UNKNOWN"
        FLOAT rca_confidence_score "Diagnostic confidence score [0.0, 1.0]"
        JSON rca_hypotheses "Ranked candidate hypotheses array"
        JSON rca_evidence "Attributed diagnostic evidence items array"
        TIMESTAMP_TZ created_at "Creation timestamp UTC (Indexed)"
        TIMESTAMP_TZ ack_deadline "Calculated acknowledgement deadline UTC"
        TIMESTAMP_TZ resolve_deadline "Calculated resolution deadline UTC"
        TIMESTAMP_TZ acknowledged_at "Timestamp of acknowledgement UTC"
        VARCHAR(128) acknowledged_by "Username or agent identifier"
        TIMESTAMP_TZ resolved_at "Timestamp of resolution UTC"
        VARCHAR(128) resolved_by "Username or agent identifier"
    }

    incident_timeline_events {
        VARCHAR(64) event_id PK "Unique event identifier (EVT-xxxxxxxxxxxx)"
        VARCHAR(64) incident_id FK "Parent incident reference (ON DELETE CASCADE)"
        VARCHAR(32) event_type "CREATED | ACKNOWLEDGED | RESOLVED | NOTE_ADDED (Indexed)"
        TIMESTAMP_TZ timestamp "Event occurrence timestamp UTC (Indexed)"
        VARCHAR(128) actor "Username or service identifier"
        VARCHAR(32) actor_type "SYSTEM | OPERATOR | AUTOMATION"
        JSON details "Structured contextual details payload"
    }
```

---

## 4. 27-Node Hierarchical Network Topology & Transport Map

The reference telecommunications infrastructure models 27 nodes organized in a 4-tier hierarchy interconnected by 26 bidirectional transport dependencies.

```mermaid
flowchart TD
    subgraph Tier1 ["Tier 1: Core Routing (1 Node)"]
        CORE01["CORE-01<br/>(Regional Gateway)"]
    end

    subgraph Tier2 ["Tier 2: Aggregation Distribution (2 Nodes)"]
        AGG01["AGG-01<br/>(Distribution Hub West)"]
        AGG02["AGG-02<br/>(Distribution Hub East)"]
    end

    subgraph Tier3 ["Tier 3: Facility Base Station Sites (6 Nodes)"]
        SITE01["SITE-01"]
        SITE02["SITE-02"]
        SITE03["SITE-03"]
        SITE04["SITE-04"]
        SITE05["SITE-05"]
        SITE06["SITE-06"]
    end

    subgraph Tier4 ["Tier 4: Radio Sector Access Cells (18 Nodes)"]
        subgraph S1_Cells ["SITE-01 Sectors"]
            C01["CELL-01"]
            C02["CELL-02"]
            C03["CELL-03"]
        end
        subgraph S2_Cells ["SITE-02 Sectors"]
            C04["CELL-04"]
            C05["CELL-05"]
            C06["CELL-06"]
        end
        subgraph S3_Cells ["SITE-03 Sectors"]
            C07["CELL-07"]
            C08["CELL-08"]
            C09["CELL-09"]
        end
        subgraph S4_Cells ["SITE-04 Sectors"]
            C10["CELL-10"]
            C11["CELL-11"]
            C12["CELL-12"]
        end
        subgraph S5_Cells ["SITE-05 Sectors"]
            C13["CELL-13"]
            C14["CELL-14"]
            C15["CELL-15"]
        end
        subgraph S6_Cells ["SITE-06 Sectors"]
            C16["CELL-16"]
            C17["CELL-17"]
            C18["CELL-18"]
        end
    end

    %% Transport Links
    CORE01 == "LINK-CORE-AGG-01<br/>(10 Gbps, 1.5ms)" ==> AGG01
    CORE01 == "LINK-CORE-AGG-02<br/>(10 Gbps, 1.5ms)" ==> AGG02

    AGG01 == "LINK-AGG-01-SITE-01<br/>(2.5 Gbps, 5.0ms)" ==> SITE01
    AGG01 == "LINK-AGG-01-SITE-02<br/>(2.5 Gbps, 5.0ms)" ==> SITE02
    AGG01 == "LINK-AGG-01-SITE-03<br/>(2.5 Gbps, 5.0ms)" ==> SITE03

    AGG02 == "LINK-AGG-02-SITE-04<br/>(2.5 Gbps, 5.0ms)" ==> SITE04
    AGG02 == "LINK-AGG-02-SITE-05<br/>(2.5 Gbps, 5.0ms)" ==> SITE05
    AGG02 == "LINK-AGG-02-SITE-06<br/>(2.5 Gbps, 5.0ms)" ==> SITE06

    SITE01 --> C01 & C02 & C03
    SITE02 --> C04 & C05 & C06
    SITE03 --> C07 & C08 & C09
    SITE04 --> C10 & C11 & C12
    SITE05 --> C13 & C14 & C15
    SITE06 --> C16 & C17 & C18
```

---

## 5. Telemetry Generation & Orchestration Pipeline

Execution trace during an operator or automated simulation step (`POST /api/v1/telemetry/generate-step`).

```mermaid
flowchart TD
    START([POST /api/v1/telemetry/generate-step]) --> LOCK{Acquire Non-Blocking<br/>Step Lock}
    LOCK -->|Failure: Contention| ERR409[Return HTTP 409 Conflict]
    LOCK -->|Success| LOOP_NODES[Iterate All 27 Nodes in Topology]

    subgraph Synthesis ["Synthetic Generation Phase"]
        LOOP_NODES --> PROF[Load NodeOperatingProfile for NodeType]
        PROF --> RNG[Gaussian Sampling from MetricRange]
        RNG --> SMOOTH[Exponential Smoothing: alpha=0.65<br/>smoothed = 0.65*prev + 0.35*target]
        SMOOTH --> CELL_CHECK{NodeType == CELL?}
        CELL_CHECK -->|Yes| CORR_RADIO[Synthesize Radio KPIs<br/>SINR, RSRP, PRB Congestion]
        CELL_CHECK -->|No| BASE_SNAP[Synthesize Transport KPIs<br/>Throughput, Latency, Availability]
        CORR_RADIO --> BASE_SNAP
    end

    BASE_SNAP --> FAULT_CHECK{Active Fault Scenario?}
    FAULT_CHECK -->|No Active Faults| STORE_REC[Record Snapshots in TelemetryStore]
    FAULT_CHECK -->|Active Fault Active| INJECT_FAULT[Apply Deterministic Impairments<br/>_apply_outage, _apply_interference, _apply_congestion]
    INJECT_FAULT --> STORE_REC

    subgraph Evaluation ["Detection & Diagnosis Phase"]
        STORE_REC --> DET_EVAL[Evaluate Against Thresholds & Baselines]
        DET_EVAL --> ALARM_PROC[AlarmManager.process_anomaly<br/>Update/Create Active Alarms]
        DET_EVAL --> RECOV_CHECK[Check Clear Thresholds & Baselines<br/>Clear Resolved Alarms]
        ALARM_PROC & RECOV_CHECK --> ACTIVE_QRY[Query Active Alarms]
        ACTIVE_QRY --> CORR_ENGINE[AlarmCorrelationEngine.correlate<br/>Group Alarms via LCA Traversal]
        CORR_ENGINE --> RCA_EVAL[RootCauseAnalysisEngine.analyze_group<br/>Evaluate Hypotheses & Evidence]
        RCA_EVAL --> INC_DISPATCH[IncidentService.create_or_update_incident<br/>Deduplicate & Persist to PostgreSQL]
    end

    INC_DISPATCH --> BCAST[EventBroadcaster.publish<br/>Broadcast TELEMETRY_SNAPSHOT, ALARM_*, INCIDENT_*]
    BCAST --> UNLOCK[Release Step Lock]
    UNLOCK --> RESP([Return HTTP 200 JSON Response])
```

---

## 6. Anomaly Detection & Baseline Protection Flow

The Evaluate-Then-Commit policy protecting rolling statistical baselines from contamination during active faults.

```mermaid
flowchart TD
    SNAP[Incoming KPISnapshot] --> EXTRACT[Extract Metric Values]

    subgraph Static_Threshold ["Static Threshold Pipeline"]
        EXTRACT --> THRESH_RULES[Evaluate Configured ThresholdRule Set]
        THRESH_RULES --> HYST_CHECK{Breaches Threshold?}
        HYST_CHECK -->|Yes| THRESH_ANOM[Emit AnomalyEvent<br/>Source: THRESHOLD]
        HYST_CHECK -->|No| THRESH_REC{Matches Active Alarm<br/>and <= clear_threshold?}
        THRESH_REC -->|Yes| CLEAR_ALARM[Clear Alarm via AlarmManager]
        THRESH_REC -->|No| NOOP1[No Action]
    end

    subgraph Statistical_Pipeline ["Statistical Baseline Pipeline"]
        EXTRACT --> STAT_EVAL[Read-Only Baseline Evaluation]
        STAT_EVAL --> MED_CALC[Calculate Rolling Median & MAD<br/>Scale = 1.4826 * MAD<br/>EffectiveScale = max(Scale, 0.05*Median, 1.0)<br/>Score = |Value - Median| / EffectiveScale]
        STAT_EVAL --> EWMA_CALC[Calculate EWMA Residual<br/>Diff = |Value - EWMA_Mean|<br/>Spread = sqrt(EWMA_Variance)<br/>Score = Diff / max(Spread, 0.05*Mean, 1.0)]

        MED_CALC --> MED_GATE{Score >= 3.0?}
        EWMA_CALC --> EWMA_GATE{Score >= 3.0?}

        MED_GATE -->|Yes| MED_ANOM[Emit AnomalyEvent<br/>Source: STATISTICAL_MEDIAN]
        EWMA_GATE -->|Yes| EWMA_ANOM[Emit AnomalyEvent<br/>Source: STATISTICAL_EWMA]

        MED_GATE -->|No| CLEAN_MED[Clean Median Sample]
        EWMA_GATE -->|No| CLEAN_EWMA[Clean EWMA Sample]
    end

    MED_ANOM & EWMA_ANOM --> CONTAM_PREVENT{Either Detector Flagged Anomaly?}
    CONTAM_PREVENT -->|Yes: Anomaly Detected| DISCARD_UPDATE[CONTAMINATION REJECTION:<br/>Exclude Sample from BOTH Baseline Updates]
    CONTAM_PREVENT -->|No: Clean Sample| UPDATE_BASELINES[COMMIT STEP:<br/>Append to Median Deque (maxlen=20)<br/>Update Recursive EWMA Mean & Variance]
```

---

## 7. Alarm State Machine & Lifecycle Transitions

Alarms follow an explicit deterministic lifecycle state machine indexed by composite deduplication key `(node_id, metric_name, rule_id, source)`.

```mermaid
stateDiagram-v2
    [*] --> Inactive : No Prior Alarm

    Inactive --> Active : Anomaly Detected\n(process_anomaly)\nAssign ALARM-{node}-{rule}-{counter}\nobservation_count = 1\nEmit ALARM_CREATED

    state Active {
        [*] --> Unacknowledged
        Unacknowledged --> Updated : Subsequent Anomaly Violation\n(process_anomaly)\nobservation_count++\nlast_seen = now\nEmit ALARM_UPDATED
        Updated --> Updated : Repeated Breaches
    }

    Active --> Cleared : Recovery Threshold Satisfied\n(clear_threshold or Baseline Normalization)\ncleared_at = now\nArchive to cleared_history\nEmit ALARM_CLEARED

    Cleared --> [*] : Persisted in Audit Memory
```

---

## 8. Topology-Aware Lowest Common Ancestor (LCA) Correlation Algorithm

Graph clustering algorithm grouping multi-node symptomatic alarms under shared physical infrastructure dependencies.

```mermaid
flowchart TD
    INPUT[Batch of Raw Alarms from AlarmManager] --> DEDUP[Deduplicate by Unique alarm_id]
    DEDUP --> SORT[Sort Deterministically:<br/>(first_seen, node_id, alarm_id)]
    SORT --> GRAPH_INIT[Initialize Adjacency Graph: N Alarm Nodes]

    subgraph Pairwise_Compatibility ["Pairwise Compatibility Evaluation"]
        GRAPH_INIT --> PAIR_LOOP[Iterate All Pairs (a1, a2)]
        PAIR_LOOP --> TIME_CHECK{abs(first_seen_1 - first_seen_2)<br/><= time_window_seconds (300s)?}
        TIME_CHECK -->|No| REJECT_EDGE[Reject Edge]
        TIME_CHECK -->|Yes| SAME_NODE{a1.node_id == a2.node_id?}
        SAME_NODE -->|Yes| ACCEPT_EDGE[Add Undirected Edge (i, j)]
        SAME_NODE -->|No| LCA_CALC[Traverse Hierarchy Bottom-Up<br/>Find Lowest Common Ancestor LCA]
        LCA_CALC --> DIST_CHECK{max(hop_dist_1, hop_dist_2)<br/><= max_ancestor_distance (2)?}
        DIST_CHECK -->|No| REJECT_EDGE
        DIST_CHECK -->|Yes| CORE_CHECK{LCA.node_type == CORE?}
        CORE_CHECK -->|Yes: Distant Ancestor| CORE_GUARD{Direct Alarm Exists on CORE?}
        CORE_GUARD -->|No| REJECT_EDGE
        CORE_GUARD -->|Yes| SYMPTOM_CHECK
        CORE_CHECK -->|No: Local Ancestor| SYMPTOM_CHECK{Are Symptoms Compatible?<br/>Exclude Localized Radio/Congestion<br/>Across Different Nodes}
        SYMPTOM_CHECK -->|Incompatible| REJECT_EDGE
        SYMPTOM_CHECK -->|Compatible| ACCEPT_EDGE
    end

    ACCEPT_EDGE --> BFS_COMPONENTS[Traverse Connected Components via BFS/Queue]

    subgraph Chaining_Protection ["Time-Window Chaining Prevention Policy"]
        BFS_COMPONENTS --> SPAN_CHECK{Candidate Group Span<br/>max(first_seen) - min(first_seen)<br/><= time_window_seconds (300s)?}
        SPAN_CHECK -->|Yes| MERGE_NODE[Include Alarm in Current Group]
        SPAN_CHECK -->|No: Exceeds Onset Span| DEFER_NODE[Defer Alarm to Subsequent Group]
    end

    MERGE_NODE --> ANCHOR_ASSIGN[Identify Group Anchor Node via _find_group_lca]
    ANCHOR_ASSIGN --> FORM_GROUP[Instantiate Immutable CorrelationGroup<br/>Assign CORR-{anchor}-{timestamp}-{index}]
    FORM_GROUP --> RESULT([Return CorrelationResult Envelope])
```

---

## 9. Root Cause Analysis (RCA) Multi-Hypothesis Diagnostic Flow

Deterministic evaluation of correlation groups against pattern matching heuristics to rank hypotheses.

```mermaid
flowchart TD
    GROUP[CorrelationGroup from CorrelationEngine] --> TEL_FILTER[Filter Telemetry Snapshots:<br/>Discard Future Information (ts > analysis_ts)<br/>Discard Stale Observations (ts < analysis_ts - max_staleness)]

    subgraph Rule_Evaluators ["Deterministic Hypothesis Evaluators"]
        TEL_FILTER --> EVAL_CORE[evaluate_core_router_failure<br/>Anchor: CORE-01, Systemic Degradation]
        TEL_FILTER --> EVAL_POWER[evaluate_site_power_failure<br/>Anchor: SITE, 0 Throughput, 0 Availability, Base Latency]
        TEL_FILTER --> EVAL_BACKHAUL[evaluate_backhaul_failure<br/>Anchor: SITE/AGG, Transport Link ID, Elevated Latency > 50ms]
        TEL_FILTER --> EVAL_INTERF[evaluate_radio_interference<br/>Target: CELL, SINR < 5dB, Drop Rate > 3%]
        TEL_FILTER --> EVAL_CONGEST[evaluate_cell_congestion<br/>Target: CELL, PRB >= 80%, Latency > 60ms]
        TEL_FILTER --> EVAL_OUTAGE[evaluate_cell_outage<br/>Target: CELL, Isolated Outage, 0 Availability]
    end

    EVAL_CORE & EVAL_POWER & EVAL_BACKHAUL & EVAL_INTERF & EVAL_CONGEST & EVAL_OUTAGE --> COLLECT[Collect Candidate RootCauseHypothesis Instances]
    COLLECT --> DEDUP_HYP[Deduplicate Candidates by (cause_type, target_id)<br/>Retain Maximum Confidence Score]
    DEDUP_HYP --> RANK[Deterministic Sorting:<br/>1. confidence_score DESC<br/>2. len(evidence_items) DESC<br/>3. target_id ASC<br/>4. cause_type.value ASC]
    RANK --> THRESH_CHECK{Highest Score >= min_confidence_threshold (0.3)?}

    THRESH_CHECK -->|Yes| PRIMARY[Select Top Candidate as Primary Hypothesis]
    THRESH_CHECK -->|No: Insufficient Evidence| UNKNOWN_FALLBACK[Instantiate Fallback Hypothesis:<br/>RootCauseType.UNKNOWN<br/>TargetType.UNKNOWN<br/>Confidence: 0.0]

    PRIMARY & UNKNOWN_FALLBACK --> REC_ACTION[Lookup Operational Recommended Action<br/>Dispatch Operations / Fiber Inspection / Grid Power]
    REC_ACTION --> RCA_OUT([Return RCAResult Record])
```

---

## 10. Incident Lifecycle & State Machine Transitions

Operational incidents enforce valid transitions, deadline freezing, and mandatory operator audit trails.

```mermaid
stateDiagram-v2
    [*] --> OPEN : Automatic Creation from RCA Cluster\nOr Manual Creation via REST API\nSet ack_deadline & resolve_deadline\nAppend CREATED Timeline Event

    state OPEN {
        [*] --> Unassigned
    }

    OPEN --> ACKNOWLEDGED : Operator Acknowledges Incident\nPOST /api/v1/incidents/{id}/acknowledge\nSet acknowledged_at & acknowledged_by\nFreeze ack_breached Evaluation\nAppend ACKNOWLEDGED Timeline Event

    OPEN --> RESOLVED : Fast-Path Direct Resolution\nPOST /api/v1/incidents/{id}/resolve\nSet resolved_at & resolved_by\nFreeze Both SLA Breach Evaluations\nAppend RESOLVED Timeline Event

    ACKNOWLEDGED --> RESOLVED : Standard Resolution\nPOST /api/v1/incidents/{id}/resolve\nSet resolved_at & resolved_by\nFreeze Both SLA Breach Evaluations\nAppend RESOLVED Timeline Event

    state RESOLVED {
        [*] --> ImmutableArchive : SLA Status Permanently Frozen\nSubsequent Modifications Rejected (HTTP 400)
    }

    RESOLVED --> [*]
```

---

## 11. Real-Time WebSocket Stream & Concurrency Sequence

Asynchronous fan-out architecture across publisher worker threads, event queues, and WebSocket connections.

```mermaid
sequenceDiagram
    autonumber
    actor Operator as NOC Operator Browser
    participant WS as WebSocket Ingress (/ws/live)
    participant Receiver as WebSocket Receiver Task
    participant Sender as Outbound Sender Task
    participant Broadcaster as EventBroadcaster (nexus.events)
    participant Worker as Backend Service (Telemetry/Incident)

    Operator->>WS: HTTP GET /ws/live (Upgrade: websocket)
    WS-->>Operator: HTTP 101 Switching Protocols
    WS->>Broadcaster: register(websocket) -> Dedicated Queue (maxsize=100)
    Broadcaster-->>WS: Return Queue Instance
    WS->>Sender: Spawn Single Outbound Writer Task
    WS->>Receiver: Spawn Inbound Reader Task

    loop Operational Dispatch
        Worker->>Broadcaster: publish(event_type, payload)
        Broadcaster->>Broadcaster: loop.call_soon_threadsafe(enqueue_on_loop)
        alt Queue Full (Slow Consumer)
            Broadcaster->>Broadcaster: Evict Oldest Event (FIFO Backpressure)
        end
        Broadcaster->>Sender: put_nowait(LiveEvent.to_dict())
        Sender->>Operator: JSON WebSocket Frame ({"type": "...", "payload": ...})
    end

    opt Heartbeat Flow (Starvation Prevention)
        Operator->>Receiver: WebSocket Text Frame ("PING")
        Receiver->>Sender: Enqueue PONG Response (pong_queue)
        Sender->>Sender: Priority Gate: Max 3 Consecutive PONGs Before Yielding
        Sender->>Operator: WebSocket Text Frame ("PONG")
    end

    opt Disconnection Flow
        Operator->>WS: TCP Close / Network Interruption
        Receiver->>WS: WebSocketDisconnect Caught
        WS->>Broadcaster: unregister(websocket)
        Broadcaster->>Broadcaster: Clean up Subscriber Record & Drain Queue
        Sender->>Sender: Cancel and Await Outbound Task
    end
```

---

## 12. Application Lifespan & Subsystem Startup Sequence

Deterministic startup, dependency wiring, probe readiness, and shutdown cleanup sequence.

```mermaid
sequenceDiagram
    autonumber
    participant Engine as ASGI Lifespan Runner (Uvicorn)
    participant Main as nexus.main:lifespan
    participant DB as PostgreSQL Database
    participant Alembic as Alembic Schema Migrations
    participant Topo as TopologyRegistry
    participant Broadcaster as EventBroadcaster
    participant Store as TelemetryStore
    participant AlarmSvc as AlarmService
    participant FaultSvc as FaultService
    participant Pipeline as TelemetryPipeline

    Engine->>Main: Startup Lifespan Context Triggered
    Main->>Alembic: Verify / Run Migrations (alembic upgrade head)
    Alembic->>DB: Execute DDL (incidents, incident_timeline_events)
    DB-->>Alembic: DDL Completed
    Main->>Broadcaster: Instantiate EventBroadcaster()
    Main->>Topo: Initialize TopologyRegistry (27 nodes)
    Main->>Store: Initialize TelemetryStore()
    Main->>Store: set_event_publisher(Broadcaster.publish)
    Main->>Store: set_topology(Topo)
    Main->>AlarmSvc: set_event_publisher(Broadcaster.publish)
    Main->>FaultSvc: set_event_publisher(Broadcaster.publish)
    Main->>Pipeline: Initialize TelemetryPipeline (Wiring Engine, Detection, RCA)
    Main->>Topo: add_status_listener(on_topology_status_change)
    Main-->>Engine: Application Ready (GET /ready returns HTTP 200)

    Note over Engine,DB: Operational Execution Serving REST & WebSocket Traffic

    Engine->>Main: Shutdown Lifespan Context Triggered
    Main->>Topo: remove_status_listener(on_topology_status_change)
    Main-->>Engine: Subsystems Detached & Process Exits Cleanly
```

---

## 13. Full End-to-End Operational Incident Lifecycle Sequence

Step-by-step trace of a live telecom fault from injection to recovery and operator resolution.

```mermaid
sequenceDiagram
    autonumber
    actor Admin as Network Operator / QA Script
    participant API as FastAPI REST Gateway
    participant Fault as FaultScenarioEngine
    participant Pipeline as TelemetryPipeline
    participant Det as AnomalyDetectionEngine
    participant Corr as AlarmCorrelationEngine
    participant RCA as RootCauseAnalysisEngine
    participant Inc as IncidentService
    participant DB as PostgreSQL
    participant Broadcaster as EventBroadcaster
    actor NOC as NOC Operations Console

    Admin->>API: POST /api/v1/faults/scenarios/backhaul_failure/activate
    API->>Fault: Activate Scenario on LINK-AGG-01-SITE-01
    Fault-->>API: Scenario Activated (Status: Active)

    Admin->>API: POST /api/v1/telemetry/generate-step
    API->>Pipeline: generate_step()
    Pipeline->>Fault: apply_faults(base_snapshots)
    Fault-->>Pipeline: Return Degraded Snapshots (SITE-01 & CELL-01..03 offline)
    Pipeline->>Det: evaluate_snapshot()
    Det-->>Pipeline: 20 AnomalyEvents Flagged (Availability < 95%, Throughput < 5M)
    Pipeline->>Corr: correlate_alarms(active_alarms)
    Corr-->>Pipeline: Group Formed: CORR-SITE-01-... (LCA: SITE-01)
    Pipeline->>RCA: analyze_group(group, topology, transport)
    RCA-->>Pipeline: Primary: BACKHAUL_FAILURE on LINK-AGG-01-SITE-01 (Confidence: 0.85)
    Pipeline->>Inc: create_or_update_incident(group, rca_res)
    Inc->>DB: INSERT INTO incidents & incident_timeline_events
    DB-->>Inc: Persisted INC-0da172cac7f0
    Inc->>Broadcaster: publish("INCIDENT_CREATED", incident_payload)
    Broadcaster->>NOC: WS Push INCIDENT_CREATED Frame
    NOC->>NOC: Render P1 Red Alert Banner & Link Degradation

    NOC->>API: POST /api/v1/incidents/INC-0da172cac7f0/acknowledge
    API->>Inc: acknowledge_incident(INC-0da172cac7f0, actor="OPERATOR_1")
    Inc->>DB: UPDATE incidents SET status='ACKNOWLEDGED'
    Inc->>Broadcaster: publish("INCIDENT_ACKNOWLEDGED", ...)
    Broadcaster->>NOC: WS Push INCIDENT_ACKNOWLEDGED Frame

    Admin->>API: POST /api/v1/faults/scenarios/deactivate
    API->>Fault: Deactivate Scenario (Nominal Telemetry Restored)

    Admin->>API: POST /api/v1/telemetry/generate-step (Recovery Step)
    API->>Pipeline: generate_step() (Clean Telemetry)
    Pipeline->>Det: check_recovery()
    Det-->>Pipeline: All 20 Alarms Clear via Hysteresis
    Pipeline->>Broadcaster: publish("ALARM_CLEARED", ...)

    NOC->>API: POST /api/v1/incidents/INC-0da172cac7f0/resolve (Notes: "Fiber link spliced")
    API->>Inc: resolve_incident(INC-0da172cac7f0, actor="OPERATOR_1")
    Inc->>DB: UPDATE incidents SET status='RESOLVED' (Freeze SLA Breach Flags)
    Inc->>Broadcaster: publish("INCIDENT_RESOLVED", ...)
    Broadcaster->>NOC: WS Push INCIDENT_RESOLVED Frame
```

---

## 14. Docker Multi-Container Deployment Architecture

Container topology, isolation networks, volume mappings, and ingress bindings.

```mermaid
flowchart TD
    subgraph Host_Environment ["Host Machine (Windows 11 / Linux VM)"]
        subgraph Port_Bindings ["Host Loopback Interface (127.0.0.1)"]
            P3000["127.0.0.1:3000 (HTTP)"]
            P8000["127.0.0.1:8000 (HTTP/WS)"]
            P3001["127.0.0.1:3001 (HTTP)"]
            P9090["127.0.0.1:9090 (HTTP)"]
        end

        subgraph Docker_Engine ["Docker Engine Virtual Network: nexus-network (Bridge)"]
            subgraph C_Frontend ["nexus-frontend Container"]
                NGINX_SRV["Nginx 1.25 Alpine<br/>User: nginx<br/>Port 80"]
            end

            subgraph C_Backend ["nexus-backend Container"]
                APP_SRV["FastAPI Backend (Python 3.11-slim)<br/>User: nexus (UID 1000)<br/>Port 8000<br/>Healthcheck: curl /ready"]
            end

            subgraph C_Postgres ["nexus-postgres Container"]
                PG_SRV["PostgreSQL 15 Alpine<br/>Database: nexus_db<br/>Port 5432<br/>Healthcheck: pg_isready"]
            end

            subgraph C_Prometheus ["nexus-prometheus Container"]
                PROM_SRV["Prometheus TSDB v2.51.0<br/>Port 9090<br/>Scrape: backend:8000/metrics"]
            end

            subgraph C_Grafana ["nexus-grafana Container"]
                GRAF_SRV["Grafana v10.4.0<br/>Port 3000<br/>Datasource: prometheus:9090"]
            end
        end

        subgraph Docker_Volumes ["Persistent Docker Volumes"]
            V_PG[(postgres_data<br/>/var/lib/postgresql/data)]
            V_PROM[(prometheus_data<br/>/prometheus)]
            V_GRAF[(grafana_data<br/>/var/lib/grafana)]
        end
    end

    %% Port Forwarding
    P3000 --> NGINX_SRV
    P8000 --> APP_SRV
    P3001 --> GRAF_SRV
    P9090 --> PROM_SRV

    %% Inter-Container Bridge Networking
    NGINX_SRV -->|"Proxy /api & /ws"| APP_SRV
    APP_SRV -->|"TCP 5432 (psycopg)"| PG_SRV
    PROM_SRV -->|"TCP 8000 Scrape /metrics"| APP_SRV
    GRAF_SRV -->|"TCP 9090 PromQL Queries"| PROM_SRV

    %% Volume Mounts
    PG_SRV --- V_PG
    PROM_SRV --- V_PROM
    GRAF_SRV --- V_GRAF
```

---

## 15. Automated CI/CD Workflow Pipeline

Continuous Integration and Verification pipeline implemented in `.github/workflows/ci.yml`.

```mermaid
flowchart LR
    PUSH([Git Push / PR to main]) --> CI_JOB[GitHub Actions Runner: ubuntu-latest]

    subgraph Backend_Matrix ["Backend Verification Matrix"]
        PY_ENV[Setup Python 3.11] --> PIP_CACHE[Cache Pip Dependencies]
        PIP_CACHE --> PIP_INSTALL[Install Package with Test Dependencies<br/>pip install -e .[test]]
        PIP_INSTALL --> FLAKE[Linting & Code Style<br/>flake8 / black check]
        FLAKE --> PYTEST[Execute Pytest Test Suite<br/>pytest -v --cov=src/nexus]
        PYTEST --> PYTEST_REPORT[Validate 571 Passing Tests & Coverage]
    end

    subgraph Frontend_Matrix ["Frontend Verification Matrix"]
        NODE_ENV[Setup Node.js 20] --> PNPM_SETUP[Enable Corepack & Pnpm 9.15.4]
        PNPM_SETUP --> PNPM_INSTALL[Install Frozen Dependencies<br/>pnpm install --frozen-lockfile]
        PNPM_INSTALL --> TYPE_CHECK[TypeScript Type Check<br/>pnpm run typecheck]
        TYPE_CHECK --> VITEST[Execute Vitest Component Tests<br/>pnpm run test]
        VITEST --> VITE_BUILD[Execute Production Vite Build<br/>pnpm run build]
    end

    subgraph E2E_Docker_Verification ["Live Container & Acceptance Gate"]
        DOCKER_BUILD[Docker Compose Build<br/>docker compose build]
        DOCKER_UP[Spin Up Multi-Container Stack<br/>docker compose up -d]
        HEALTH_WAIT[Wait for Healthchecks: 5/5 Healthy]
        E2E_SCRIPT[Execute Acceptance Script<br/>python scripts/verify_e2e_acceptance.py]
    end

    CI_JOB --> Backend_Matrix & Frontend_Matrix
    PYTEST_REPORT & VITE_BUILD --> E2E_Docker_Verification
    E2E_SCRIPT --> VERDICT([Success: Build & Tests Passed])
```
