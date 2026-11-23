# NEXUS — Database Schema & Alembic Migrations

This document specifies the database persistence layer, relational schema, indexes, and Alembic migration workflows for the **NEXUS Network Intelligence & Incident Management Platform**.

---

## Storage Architecture Overview

NEXUS employs SQLAlchemy 2.x with an asynchronous-ready declarative mapping layer backed by PostgreSQL 15 in containerized production and automated CI/CD environments.

```
                           ┌─────────────────────────────────────────┐
                           │          IncidentService / API          │
                           └────────────────────┬────────────────────┘
                                                │
                                                ▼
                           ┌─────────────────────────────────────────┐
                           │           IncidentRepository            │
                           │       (SQLAlchemy 2.x Engine)           │
                           └────────────────────┬────────────────────┘
                                                │
                     ┌──────────────────────────┴──────────────────────────┐
                     │                                                     │
                     ▼                                                     ▼
        ┌─────────────────────────┐                           ┌─────────────────────────┐
        │       PostgreSQL        │                           │     SQLite (Dev Only)   │
        │   (Mandatory Alembic)   │                           │  (Auto-init if dev mode)│
        └─────────────────────────┘                           └─────────────────────────┘
```

### Dual Backend Support Policy
1. **Production & Staging (PostgreSQL 15+)**:
   - Schema enforcement is strict: running `alembic upgrade head` is mandatory.
   - If tables are missing at application startup, the application raises a `RuntimeError` and halts to prevent unversioned schema drift.
2. **Local Development (SQLite)**:
   - When `ENVIRONMENT=development` is active or `:memory:` is configured, tables are automatically initialized via `Base.metadata.create_all()` if not present, enabling zero-configuration development without external Docker services.

---

## Relational Schema Specification

### 1. `incidents` Table
The primary entity table storing operational incidents generated from correlated alarms and RCA hypotheses.

| Column | Type | Nullable | Default / Constraints | Description |
| :--- | :--- | :---: | :--- | :--- |
| `incident_id` | `VARCHAR(64)` | No | `PRIMARY KEY` | Unique incident identifier (e.g. `INC-20261122-001`) |
| `correlation_group_id` | `VARCHAR(128)` | No | `UNIQUE` | Originating correlation group identity |
| `status` | `VARCHAR(32)` | No | None | Lifecycle state: `OPEN`, `ACKNOWLEDGED`, `RESOLVED` |
| `severity` | `VARCHAR(32)` | No | None | Severity level: `CRITICAL`, `MAJOR`, `WARNING`, `MINOR` |
| `priority` | `VARCHAR(16)` | No | None | Operational priority: `P1`, `P2`, `P3`, `P4` |
| `title` | `VARCHAR(256)` | No | None | Incident summary title |
| `description` | `TEXT` | No | None | Detailed diagnostic description |
| `alarm_ids` | `JSON` | No | None | Array of correlated alarm identifier strings |
| `affected_node_ids` | `JSON` | No | None | Array of affected topology node identifier strings |
| `suspected_cause_type` | `VARCHAR(64)` | Yes | None | RCA diagnostic classification (e.g. `CELL_OUTAGE`) |
| `suspected_target_id` | `VARCHAR(128)` | Yes | None | Target node or link identifier (e.g. `CELL-01`) |
| `suspected_target_type`| `VARCHAR(32)` | Yes | None | Classification of target: `NODE` or `TRANSPORT_LINK` |
| `rca_confidence_score` | `FLOAT` | Yes | None | Diagnostic confidence $[0.0, 1.0]$ (`NULL` if unavailable) |
| `rca_hypotheses` | `JSON` | No | `[]` | Ranked list of evaluated root-cause hypotheses |
| `rca_evidence` | `JSON` | No | `[]` | Preserved diagnostic evidence items supporting RCA |
| `created_at` | `TIMESTAMP WITH TZ` | No | None | Timezone-aware UTC timestamp of incident creation |
| `ack_deadline` | `TIMESTAMP WITH TZ` | No | None | SLA target deadline for operational acknowledgement |
| `resolve_deadline` | `TIMESTAMP WITH TZ` | No | None | SLA target deadline for incident resolution |
| `acknowledged_at` | `TIMESTAMP WITH TZ` | Yes | `NULL` | Timestamp of operator acknowledgement |
| `acknowledged_by` | `VARCHAR(128)` | Yes | `NULL` | Operator identity who acknowledged incident |
| `resolved_at` | `TIMESTAMP WITH TZ` | Yes | `NULL` | Timestamp of incident resolution |
| `resolved_by` | `VARCHAR(128)` | Yes | `NULL` | Operator identity who resolved incident |

#### Indexes on `incidents`:
- `ix_incidents_correlation_group_id`: Unique index on `correlation_group_id` guaranteeing idempotency against duplicate alarm correlations.
- `ix_incidents_status`: B-tree index optimizing queries filtering by lifecycle state (`status`).
- `ix_incidents_severity`: B-tree index optimizing severity distribution analytics.
- `ix_incidents_created_at`: B-tree index supporting chronological ordering and SLA window calculations.

---

### 2. `incident_timeline_events` Table
An append-only audit trail capturing all operational state changes and actor annotations for compliance and review.

| Column | Type | Nullable | Default / Constraints | Description |
| :--- | :--- | :---: | :--- | :--- |
| `event_id` | `VARCHAR(64)` | No | `PRIMARY KEY` | Unique event identifier (e.g. `EVT-001`) |
| `incident_id` | `VARCHAR(64)` | No | `FOREIGN KEY` (`ON DELETE CASCADE`) | Reference to parent incident in `incidents` |
| `event_type` | `VARCHAR(32)` | No | None | Classification: `CREATED`, `ACKNOWLEDGED`, `RESOLVED`, `NOTE` |
| `timestamp` | `TIMESTAMP WITH TZ` | No | None | Timezone-aware UTC timestamp of event |
| `actor` | `VARCHAR(128)` | No | None | Human operator or automated system identity |
| `actor_type` | `VARCHAR(32)` | No | None | Actor classification: `OPERATOR`, `SYSTEM` |
| `details` | `JSON` | No | `{}` | Contextual payload (e.g. resolution notes, previous status) |

#### Indexes on `incident_timeline_events`:
- `ix_incident_timeline_events_incident_id`: B-tree index accelerating timeline retrieval for specific incidents.
- `ix_incident_timeline_events_event_type`: B-tree index supporting audit queries across event categories.
- `ix_incident_timeline_events_timestamp`: B-tree index enforcing deterministic chronological playback.

---

## Alembic Migration Architecture

Alembic manages database schema evolution. Migration files reside in `migrations/versions/`.

### Directory Layout
```
nexus-network-intelligence/
├── alembic.ini                                # Alembic configuration
└── migrations/
    ├── env.py                                 # Environment runner script
    ├── script.py.mako                         # Migration template
    └── versions/
        └── 0001_initial_incident_schema.py   # Baseline incident & timeline schema
```

### Safe Database Connection Configuration
In `migrations/env.py` and `src/nexus/incidents/api.py`, the database connection string is built dynamically using SQLAlchemy's `URL.create`:
```python
from sqlalchemy.engine import URL

db_url = URL.create(
    "postgresql+psycopg",
    username=os.getenv("POSTGRES_USER", "nexus_user"),
    password=os.getenv("POSTGRES_PASSWORD"),
    host=os.getenv("POSTGRES_HOST", "postgres"),
    port=int(os.getenv("POSTGRES_PORT", "5432")),
    database=os.getenv("POSTGRES_DB", "nexus_db"),
).render_as_string(hide_password=False)
```

**Security Advantages**:
- Passwords containing special reserved characters (e.g. `@`, `:`, `/`, `%`) are automatically percent-encoded.
- No plaintext credentials or hardcoded passwords exist in `alembic.ini`.

---

## Operational Migration Commands

### 1. Applying Migrations (Upgrade)
Apply all pending schema migrations to the latest revision:
```bash
python -m alembic upgrade head
```

Within Docker Compose, this step executes automatically during backend container initialization via `docker-entrypoint.sh`.

### 2. Checking Current Revision
Inspect current schema revision against database state:
```bash
python -m alembic current
```

### 3. Viewing Migration History
List all migration revisions and dependency chains:
```bash
python -m alembic history --verbose
```

### 4. Creating a New Migration
Generate a new auto-detected migration script after modifying declarative models:
```bash
python -m alembic revision --autogenerate -m "add_remediation_actions_table"
```

### 5. Rolling Back Migrations (Downgrade)
Roll back by one revision:
```bash
python -m alembic downgrade -1
```

Roll back completely to a clean database:
```bash
python -m alembic downgrade base
```

---

## Verification & Integrity Safeguards

1. **Foreign Key Integrity**:
   - `incident_timeline_events` enforces foreign keys with `ON DELETE CASCADE`. Deleting an incident removes all associated audit events atomically.
2. **Deterministic Timestamps**:
   - All datetime columns specify `timezone=True`. The application enforces UTC conversion at runtime before persisting records.
3. **Bounded Memory Streaming**:
   - Analytics aggregations compute MTTA, MTTR, and SLA compliance using chunked iteration (`yield_per(100)`), preventing memory exhaustion even with large historical datasets.
