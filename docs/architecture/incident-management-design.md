# NEXUS Architecture: Incident Management & SLA Tracking (Milestone 6)

## 1. Executive Summary

Milestone 6 introduces the persistent Incident Management & SLA Tracking subsystem for NEXUS (Network Intelligence & Incident Management Platform). Building upon the alarm correlation and Root Cause Analysis (RCA) engine delivered in Milestone 5, this subsystem converts correlated alarm clusters and explainable diagnostic hypotheses into durable, auditable, and actionable operational incidents.

The subsystem exposes a REST API powered by FastAPI, transactional persistence via SQLAlchemy 2.x and Alembic schema migrations targeting PostgreSQL, timezone-safe SLA calculation, an append-only audit timeline, and operational incident metrics (MTTD, MTTA, MTTR).

---

## 2. Incident Domain Model

The core incident domain entity is implemented as a validated, immutable-friendly Python domain model independent of the database and web framework:

```
+------------------------------------------------------------------------------------+
|                                      Incident                                      |
+------------------------------------------------------------------------------------+
| incident_id: str                      (Unique stable ID, e.g. INC-a1b2c3d4)        |
| correlation_group_id: str             (Unique correlation group identifier)        |
| status: IncidentStatus                (OPEN, ACKNOWLEDGED, RESOLVED)               |
| severity: IncidentSeverity            (CRITICAL, MAJOR, WARNING, MINOR)            |
| priority: IncidentPriority            (P1, P2, P3, P4)                             |
| title: str                            (Human-readable summary headline)            |
| description: str                      (Diagnostic summary / RCA explanation)       |
| alarm_ids: tuple[str, ...]            (Associated correlated alarms)               |
| affected_node_ids: tuple[str, ...]    (Topology nodes experiencing degradation)    |
| suspected_cause_type: Optional[RootCauseType] (BACKHAUL_FAILURE, CELL_OUTAGE, ...) |
| suspected_target_id: Optional[str]    (Target node or link identifier)             |
| suspected_target_type: Optional[TargetType]   (NODE, TRANSPORT_LINK)               |
| rca_confidence_score: Optional[float] (Diagnostic heuristic score in [0.0, 1.0])  |
| rca_hypotheses: tuple[dict, ...]      (Structured, ranked diagnostic hypotheses)   |
| rca_evidence: tuple[dict, ...]        (Granular symptom / snapshot evidence items) |
| created_at: datetime                  (UTC creation timestamp)                     |
| ack_deadline: datetime                (UTC acknowledgement deadline)               |
| resolve_deadline: datetime            (UTC resolution deadline)                    |
| acknowledged_at: Optional[datetime]   (UTC acknowledgement timestamp)              |
| acknowledged_by: Optional[str]        (Operator or automation actor)               |
| resolved_at: Optional[datetime]       (UTC resolution timestamp)                   |
| resolved_by: Optional[str]            (Operator or automation actor)               |
| timeline: tuple[TimelineEvent, ...]   (Append-only chronological audit log)        |
+------------------------------------------------------------------------------------+
```

### Key Domain Principles:
- **Zero Ground-Truth Leakage**: Incidents are generated strictly from observable correlation groups and RCA results, without accessing fault injection ground truth.
- **Handling UNKNOWN RCA Results**: If the diagnostic engine yields `UNKNOWN` or no primary hypothesis, the incident is successfully created with `suspected_cause_type = RootCauseType.UNKNOWN` and unverified root cause description.
- **Timezone Normalization**: All timestamps are converted to and stored in UTC.

---

## 3. Incident Lifecycle & State Transitions

The incident lifecycle follows an explicit state machine:

```
        +-------------------+
        |       OPEN        |
        +---------+---------+
                  |
         +--------+--------+
         |                 |
  (acknowledge)        (resolve)
         |                 |
         v                 |
+------------------+       |
|   ACKNOWLEDGED   |       |
+--------+---------+       |
         |                 |
     (resolve)             |
         |                 |
         +--------+--------+
                  |
                  v
        +-------------------+
        |     RESOLVED      |
        +-------------------+
```

### Transition Invariants:
1. **`OPEN -> ACKNOWLEDGED`**: Permitted with actor and timestamp. Recorded in timeline.
2. **`OPEN -> RESOLVED`**: Permitted for rapid fixes or auto-cleared anomalies.
3. **`ACKNOWLEDGED -> RESOLVED`**: Permitted with actor, timestamp, and optional resolution notes.
4. **Duplicate Acknowledgement Rejection**: Attempting to acknowledge an already `ACKNOWLEDGED` incident raises `InvalidStateTransitionError`.
5. **No Acknowledgement After Resolution**: Attempting to acknowledge an already `RESOLVED` incident raises `InvalidStateTransitionError`.
6. **No Duplicate Resolution**: Attempting to resolve an already `RESOLVED` incident raises `InvalidStateTransitionError`.
7. **Temporal Consistency**: Acknowledgement and resolution timestamps cannot precede incident `created_at`.
8. **Failed Transitions Produce Zero Side Effects**: If an invalid transition is rejected, no timeline event is created or stored.

---

## 4. Operational Severity Policy

Incident severity is governed by an explicit, configurable **Operational Impact Policy** (`OperationalSeverityPolicy`), rather than diagnostic confidence:

```
+-------------------------------------------------------------------------------+
| Criteria                                                          | Severity  | Priority |
+-------------------------------------------------------------------------------+
| CRITICAL alarm on CORE or AGGREGATION node, OR >= 5 affected nodes| CRITICAL  |    P1    |
| CRITICAL alarm on SITE or CELL, OR MAJOR alarm on CORE/AGGREGATION| MAJOR     |    P2    |
| MAJOR alarm on SITE or CELL, OR >= 2 affected nodes with WARNING  | WARNING   |    P3    |
| Isolated single-node WARNING alarm                                | MINOR     |    P4    |
+-------------------------------------------------------------------------------+
```

### Assumptions & Rationales:
- **Independence from Diagnostic Confidence**: A low-confidence or unconfirmed root cause on a core trunk carrying traffic for thousands of cells is an urgent operational emergency (CRITICAL / P1). Conversely, a high-confidence single cell sector issue remains low-impact (WARNING / P3).
- **Blast Radius & Topology Awareness**: Backbone tiers (CORE, AGGREGATION) multiply blast radius; impact escalates accordingly.

---

## 5. SLA Calculation & Management

SLA targets dictate operational response windows from incident creation (`created_at`).

### Default SLA Configuration:

| Severity | Priority | Acknowledgement Target | Resolution Target |
|:---|:---:|:---:|:---:|
| **CRITICAL** | P1 | 15 minutes | 60 minutes (1 hour) |
| **MAJOR** | P2 | 30 minutes | 240 minutes (4 hours) |
| **WARNING** | P3 | 60 minutes (1 hour) | 720 minutes (12 hours) |
| **MINOR** | P4 | 120 minutes (2 hours) | 1440 minutes (24 hours) |

### Deadlines and Breach Logic:
- **Acknowledgement Deadline**: `ack_deadline = created_at + ack_target`
- **Resolution Deadline**: `resolve_deadline = created_at + resolve_target`
- **Acknowledgement Breach Evaluation**:
  - If acknowledged: breached when `acknowledged_at > ack_deadline`.
  - If unacknowledged: breached when `current_time > ack_deadline`.
- **Resolution Breach Evaluation**:
  - If resolved: breached when `resolved_at > resolve_deadline`.
  - If unresolved: breached when `current_time > resolve_deadline`.
- **Deadline Invariance**: SLA deadlines are never reset or postponed when an incident is acknowledged.
- **Freezing on Resolution**: Once an incident is resolved, its SLA compliance status freezes permanently based on actual historical completion timestamps; future clock advances do not induce retroactive breaches.

---

## 6. Append-Only Incident Timeline & Audit History

All operational events are captured as append-only records in `incident_timeline_events`:

```
+-----------------------------------------------------------------------+
| Field       | Type                     | Purpose                      |
+-----------------------------------------------------------------------+
| event_id    | String(64) [PK]          | Unique event identifier      |
| incident_id | String(64) [FK]          | Target incident reference    |
| event_type  | String(32)               | CREATED, ACKNOWLEDGED, ...   |
| timestamp   | DateTime(timezone=True)  | Event UTC occurrence time    |
| actor       | String(128)              | System or operator name      |
| actor_type  | String(32)               | SYSTEM or OPERATOR           |
| details     | JSON                     | Structured contextual payload|
+-----------------------------------------------------------------------+
```

### Guarantees & Lifecycle Semantics:
- **Application-Level Append-Only Guarantee**: In the domain and application service layers, the timeline is strictly append-only. Lifecycle transitions (`CREATED`, `ACKNOWLEDGED`, `RESOLVED`) only insert new immutable `TimelineEvent` records. No API or service methods exist to modify, update, or delete individual historical timeline events.
- **Database-Level Cascade-Delete Behavior**: The database foreign key on `incident_timeline_events.incident_id` references `incidents.incident_id` with `ondelete="CASCADE"`. Deleting a parent incident record cascades to remove its associated timeline events, maintaining relational hygiene and preventing orphaned audit records.
- **Database-Level Immutability Boundary**: Immutability is enforced at the application service and transaction boundary; database-level SQL triggers (e.g., `BEFORE UPDATE OR DELETE` disallowing row modification) are not implemented, leaving cascade-delete and administrative maintenance viable.
- **Atomicity**: Changes to incident state and corresponding timeline events are committed within the same database transaction.
- **Deterministic Ordering**: Timeline history is ordered chronologically by `timestamp ASC`.

---

## 7. Database Persistence & Migrations

Persistence is implemented using SQLAlchemy 2.x declarative models and Alembic database migrations.

### Database Schema:
- Table `incidents`:
  - `incident_id` (VARCHAR(64), Primary Key)
  - `correlation_group_id` (VARCHAR(128), Unique Constraint & Index)
  - `status`, `severity`, `priority` (Indexed)
  - `created_at` (Indexed), `ack_deadline`, `resolve_deadline`
  - `acknowledged_at`, `acknowledged_by`, `resolved_at`, `resolved_by`
  - JSON columns: `alarm_ids`, `affected_node_ids`, `rca_hypotheses`, `rca_evidence`
- Table `incident_timeline_events`:
  - `event_id` (VARCHAR(64), Primary Key)
  - `incident_id` (Foreign Key -> `incidents.incident_id`, CASCADE)
  - `event_type`, `timestamp`, `actor`, `actor_type`, `details` (JSON)

### Database Compatibility & Runtime Behavior:
- **PostgreSQL (Production & CI)**:
  - Production database engine using `postgresql+psycopg`.
  - Strictly requires schema management via Alembic (`alembic upgrade head`).
  - At runtime, the service layer inspects the schema and raises a descriptive `RuntimeError` if the database is unmigrated, preventing silent failures or inconsistent states.
  - Enforces database-level uniqueness on `correlation_group_id` and relational foreign-key integrity.
- **SQLite (Development & Offline Testing)**:
  - Fully supported for local unit testing and zero-setup offline development with `StaticPool` and JSON compatibility.
  - Development mode supports automatic schema creation (`metadata.create_all`) when using SQLite, allowing instant local testing without manual database bootstrapping.
- **Idempotency**: A database-level unique constraint on `correlation_group_id` prevents duplicate incidents even under concurrent creation attempts.

---

## 7.1 Data Ingestion & Streaming Metrics Architecture

### Actual Alarm Ingestion Model:
Incidents are created from actual correlation and RCA results using validated `CorrelatedAlarmDTO` structures rather than fabricated placeholder data:
- Every alarm retains its actual `alarm_id`, `node_id`, `rule_id`, `metric_name`, `source`, `severity`, `current_value`, `threshold`, `first_seen`, `last_seen`, `observation_count`, and `status`.
- The `OperationalSeverityPolicy` evaluates genuine alarm severities (`CRITICAL`, `MAJOR`, `WARNING`) and affected node counts, ensuring accurate operational prioritization.
- Requests with incomplete or missing alarm data are rejected with HTTP 422 rather than synthesized.
- Diagnostic confidence scores are strictly validated as finite floats in $[0.0, 1.0]$ (rejecting booleans, NaN, and infinity) and are preserved as `None` when unavailable, completely avoiding invented confidence defaults.

### Streaming Metrics Beyond 10,000 Incidents:
To support large-scale operational environments without memory exhaustion or data truncation:
- Metrics computation utilizes streaming batched pagination (`iter_all_incidents(batch_size=2000)`).
- The `MetricsCalculator` consumes an `Iterable[Incident]` and computes running sums and counts in $O(1)$ memory.
- There is zero artificial truncation (removing the previous 10,000-incident limit), ensuring all persisted historical records accurately contribute to MTTA, MTTR, open counts, and SLA breach tallies.

---

## 8. REST API Architecture

A FastAPI application exposes versioned REST endpoints under `/api/v1`:

```
POST   /api/v1/incidents                 -> Create incident from correlation & RCA (201 Created)
GET    /api/v1/incidents                 -> List incidents with status, severity, pagination (200 OK)
GET    /api/v1/incidents/{incident_id}   -> Retrieve incident details and SLA compliance (200 OK)
POST   /api/v1/incidents/{incident_id}/acknowledge -> Acknowledge incident (200 OK)
POST   /api/v1/incidents/{incident_id}/resolve     -> Resolve incident with notes (200 OK)
GET    /api/v1/incidents/{incident_id}/timeline    -> Retrieve chronological audit log (200 OK)
GET    /api/v1/incidents/metrics         -> Retrieve operational incident & SLA metrics (200 OK)
```

### Standardized Status Codes & Responses:
- `200 OK`: Successful retrieval or lifecycle update.
- `201 Created`: Incident successfully created.
- `400 Bad Request`: Illegal lifecycle transition (e.g. resolving twice).
- `404 Not Found`: Incident ID does not exist.
- `409 Conflict`: Duplicate incident for correlation group.
- `422 Unprocessable Entity`: Request validation failure.

---

## 9. Operational Metrics Definitions

The `MetricsCalculator` computes operational KPIs across incidents:

1. **MTTA (Mean Time To Acknowledge)**:
   $$\text{MTTA} = \frac{1}{N_{\text{acked}}} \sum_{i=1}^{N_{\text{acked}}} (\text{acknowledged\_at}_i - \text{created\_at}_i)$$
   Strictly calculated across acknowledged incidents. Returns `None` if zero incidents have been acknowledged.
2. **MTTR (Mean Time To Resolve)**:
   $$\text{MTTR} = \frac{1}{N_{\text{resolved}}} \sum_{i=1}^{N_{\text{resolved}}} (\text{resolved\_at}_i - \text{created\_at}_i)$$
   Strictly calculated across resolved incidents. Active/unresolved incidents are excluded to avoid skewing completion averages.
3. **MTTD (Mean Time To Detect)**:
   $$\text{MTTD} = \frac{1}{N_{\text{detected}}} \sum_{i=1}^{N_{\text{detected}}} (\text{first\_detection\_time}_i - \text{fault\_onset}_i)$$
   Derived strictly from detection evaluation data. Reported as `None` when detection onset data is absent, avoiding arbitrary heuristics.
4. **Open Incident Count**: Total incidents in `OPEN` or `ACKNOWLEDGED` status.
5. **Breach Counts**: Separate counters for acknowledgement SLA breaches and resolution SLA breaches.

---

## 10. Security & Operational Limitations

- **Authentication & Authorization**: The API does not enforce token-based authentication (OAuth2 / JWT) or role-based access control (RBAC). In a production environment, API gateway authentication or reverse-proxy mutual TLS must front `/api/v1`.
- **Concurrency & Locking**: 
  - Service and database uniqueness constraints guard against duplicate creation for the same correlation group.
  - Updates to existing incidents follow a transactional atomic model but operate on a last-write-wins basis; optimistic concurrency locking (such as version tokens or HTTP ETags) is deferred to future multi-operator collaboration milestones.
- **Timeline Immutability Guarantees**:
  - The append-only behavior is guaranteed at the application domain and service layer through validated state transitions that insert new events without modifying or overwriting past events.
  - At the database level, timeline events are protected by foreign-key relationships and cascade policies; database-level immutability triggers (disallowing `UPDATE` and `DELETE` on `incident_timeline_events` via SQL triggers) are deferred for enterprise hardening.
- **MTTD Availability**:
  - Mean Time to Detect (MTTD) is derived strictly from benchmark detection evaluation records correlating injected fault onset to first alert. When metrics are requested without detection evaluation records (e.g. standalone incident tracking), MTTD is explicitly returned as `None` rather than inventing an arbitrary baseline.
