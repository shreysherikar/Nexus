"""Persistence and integration tests for NEXUS Incident Management repository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence
import os
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config
from nexus.incidents.enums import (
    ActorType,
    IncidentPriority,
    IncidentSeverity,
    IncidentStatus,
    TimelineEventType,
)
from nexus.incidents.exceptions import (
    DuplicateIncidentError,
    IncidentNotFoundError,
)
from nexus.incidents.models import Incident, TimelineEvent
from nexus.incidents.repository import (
    Base,
    IncidentModel,
    IncidentRepository,
    TimelineEventModel,
)
from nexus.rca.models import RootCauseType, TargetType


def make_sample_incident(
    incident_id: str = "INC-TEST-1",
    correlation_group_id: str = "GRP-TEST-1",
    status: IncidentStatus = IncidentStatus.OPEN,
    severity: IncidentSeverity = IncidentSeverity.MAJOR,
) -> Incident:
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    evt = TimelineEvent(
        event_id=f"EVT-{incident_id}-1",
        incident_id=incident_id,
        event_type=TimelineEventType.CREATED,
        timestamp=t0,
        actor="SYSTEM",
        actor_type=ActorType.SYSTEM,
        details={"reason": "test creation"},
    )
    return Incident(
        incident_id=incident_id,
        correlation_group_id=correlation_group_id,
        status=status,
        severity=severity,
        priority=IncidentPriority.P2,
        title=f"Test Incident {incident_id}",
        description="Detailed description for testing",
        alarm_ids=("alm-1", "alm-2"),
        affected_node_ids=("SITE-01", "CELL-01"),
        suspected_cause_type=RootCauseType.SITE_POWER_FAILURE,
        suspected_target_id="SITE-01",
        suspected_target_type=TargetType.NODE,
        rca_confidence_score=0.92,
        rca_hypotheses=(
            {
                "hypothesis_id": "HYP-1",
                "cause_type": "SITE_POWER_FAILURE",
                "target_id": "SITE-01",
                "target_type": "NODE",
                "confidence_score": 0.92,
                "explanation": "Power outage",
            },
        ),
        rca_evidence=(
            {
                "source_node_id": "SITE-01",
                "metric_name": "availability_pct",
                "observed_value": 0.0,
                "threshold_or_baseline": 10.0,
                "reasoning": "Zero availability",
                "severity": "CRITICAL",
                "evidence_source": "ALARM",
            },
        ),
        created_at=t0,
        ack_deadline=t0 + timedelta(minutes=30),
        resolve_deadline=t0 + timedelta(hours=4),
        timeline=(evt,),
    )


@pytest.fixture
def sqlite_engine():
    """Create in-memory SQLite engine with tables initialized."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def repo(sqlite_engine) -> IncidentRepository:
    return IncidentRepository.from_engine(sqlite_engine)


class TestIncidentRepositoryPersistence:
    """Test repository CRUD operations, transactions, constraints, and audit trail."""

    def test_create_and_retrieve_incident(self, repo: IncidentRepository) -> None:
        inc = make_sample_incident("INC-101", "GRP-101")
        repo.create(inc)

        fetched = repo.get_by_id("INC-101")
        assert fetched is not None
        assert fetched.incident_id == "INC-101"
        assert fetched.correlation_group_id == "GRP-101"
        assert fetched.status == IncidentStatus.OPEN
        assert fetched.severity == IncidentSeverity.MAJOR
        assert fetched.suspected_cause_type == RootCauseType.SITE_POWER_FAILURE
        assert fetched.suspected_target_id == "SITE-01"
        assert fetched.suspected_target_type == TargetType.NODE
        assert fetched.rca_confidence_score == 0.92
        assert len(fetched.alarm_ids) == 2
        assert len(fetched.affected_node_ids) == 2
        assert len(fetched.rca_hypotheses) == 1
        assert len(fetched.rca_evidence) == 1

        # Check timeline retrieval
        assert len(fetched.timeline) == 1
        assert fetched.timeline[0].event_type == TimelineEventType.CREATED
        assert fetched.timeline[0].actor == "SYSTEM"

    def test_get_by_correlation_group_id(self, repo: IncidentRepository) -> None:
        inc = make_sample_incident("INC-102", "GRP-102")
        repo.create(inc)

        fetched = repo.get_by_correlation_group_id("GRP-102")
        assert fetched is not None
        assert fetched.incident_id == "INC-102"

        assert repo.get_by_correlation_group_id("NONEXISTENT") is None

    def test_unique_correlation_group_constraint_raises_duplicate_error(
        self, repo: IncidentRepository
    ) -> None:
        inc1 = make_sample_incident("INC-103A", "GRP-SAME")
        inc2 = make_sample_incident("INC-103B", "GRP-SAME")

        repo.create(inc1)
        with pytest.raises(DuplicateIncidentError) as exc_info:
            repo.create(inc2)
        assert "GRP-SAME" in str(exc_info.value)

    def test_update_lifecycle_and_timeline_atomicity(self, repo: IncidentRepository) -> None:
        inc = make_sample_incident("INC-104", "GRP-104")
        repo.create(inc)

        t_ack = inc.created_at + timedelta(minutes=10)
        acked = inc.acknowledge(actor="operator_1", timestamp=t_ack)
        repo.update(acked)

        # Retrieve and verify update
        reloaded = repo.get_by_id("INC-104")
        assert reloaded is not None
        assert reloaded.status == IncidentStatus.ACKNOWLEDGED
        assert reloaded.acknowledged_by == "operator_1"
        assert reloaded.acknowledged_at == t_ack
        assert len(reloaded.timeline) == 2
        assert reloaded.timeline[1].event_type == TimelineEventType.ACKNOWLEDGED

        # Resolve
        t_res = inc.created_at + timedelta(minutes=45)
        resolved = reloaded.resolve(actor="operator_2", timestamp=t_res, notes="Power restored")
        repo.update(resolved)

        final = repo.get_by_id("INC-104")
        assert final is not None
        assert final.status == IncidentStatus.RESOLVED
        assert final.resolved_by == "operator_2"
        assert final.resolved_at == t_res
        assert len(final.timeline) == 3
        assert final.timeline[2].event_type == TimelineEventType.RESOLVED

    def test_list_incidents_filtering_and_pagination(self, repo: IncidentRepository) -> None:
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(1, 6):
            inc = make_sample_incident(
                incident_id=f"INC-LIST-{i}",
                correlation_group_id=f"GRP-LIST-{i}",
                status=IncidentStatus.OPEN if i <= 3 else IncidentStatus.RESOLVED,
                severity=IncidentSeverity.CRITICAL if i % 2 == 1 else IncidentSeverity.MAJOR,
            )
            # Stagger timestamps
            inc = Incident(
                incident_id=inc.incident_id,
                correlation_group_id=inc.correlation_group_id,
                status=inc.status,
                severity=inc.severity,
                priority=inc.priority,
                title=inc.title,
                description=inc.description,
                alarm_ids=inc.alarm_ids,
                affected_node_ids=inc.affected_node_ids,
                suspected_cause_type=inc.suspected_cause_type,
                suspected_target_id=inc.suspected_target_id,
                suspected_target_type=inc.suspected_target_type,
                rca_confidence_score=inc.rca_confidence_score,
                rca_hypotheses=inc.rca_hypotheses,
                rca_evidence=inc.rca_evidence,
                created_at=t0 + timedelta(minutes=i),
                ack_deadline=inc.ack_deadline,
                resolve_deadline=inc.resolve_deadline,
                timeline=inc.timeline,
            )
            repo.create(inc)

        # Total list
        all_items, total = repo.list_incidents(limit=10, offset=0)
        assert total == 5
        assert len(all_items) == 5

        # Filter by status OPEN
        open_items, open_total = repo.list_incidents(status=IncidentStatus.OPEN)
        assert open_total == 3
        assert len(open_items) == 3

        # Filter by severity CRITICAL
        crit_items, crit_total = repo.list_incidents(severity=IncidentSeverity.CRITICAL)
        assert crit_total == 3
        assert len(crit_items) == 3

        # Pagination: limit 2, offset 1
        page, _ = repo.list_incidents(limit=2, offset=1)
        assert len(page) == 2


class TestAlembicMigration:
    """Test Alembic schema migration upgrade and downgrade cycle."""

    def test_migration_upgrade_and_downgrade(self, tmp_path) -> None:
        db_file = tmp_path / "test_alembic.db"
        test_url = f"sqlite:///{db_file}"

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", test_url)

        # Upgrade to head
        command.upgrade(alembic_cfg, "head")

        # Verify tables exist
        engine = create_engine(test_url)
        with engine.connect() as conn:
            from sqlalchemy import inspect
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            assert "incidents" in tables
            assert "incident_timeline_events" in tables

            # Verify columns on incidents
            columns = {c["name"] for c in inspector.get_columns("incidents")}
            assert "incident_id" in columns
            assert "correlation_group_id" in columns
            assert "status" in columns
            assert "severity" in columns
            assert "rca_hypotheses" in columns

        engine.dispose()

        # Downgrade to base
        command.downgrade(alembic_cfg, "base")

        engine2 = create_engine(test_url)
        with engine2.connect() as conn:
            from sqlalchemy import inspect
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            assert "incidents" not in tables
            assert "incident_timeline_events" not in tables
        engine2.dispose()

    def test_migration_respects_config_url_even_when_database_url_env_is_set(
        self, tmp_path, monkeypatch
    ) -> None:
        """Prove SQLite migration respects Config object URL even when DATABASE_URL is set in env."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nexus:nexus@localhost:5432/nexus_test_db")
        db_file = tmp_path / "test_env_override.db"
        test_url = f"sqlite:///{db_file}"

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", test_url)

        # Upgrade to head should apply to SQLite despite PostgreSQL DATABASE_URL in env
        command.upgrade(alembic_cfg, "head")

        engine = create_engine(test_url)
        with engine.connect() as conn:
            from sqlalchemy import inspect
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            assert "incidents" in tables
            assert "incident_timeline_events" in tables

            timeline_cols = {c["name"] for c in inspector.get_columns("incident_timeline_events")}
            assert "event_id" in timeline_cols
            assert "incident_id" in timeline_cols
            assert "event_type" in timeline_cols
            assert "timestamp" in timeline_cols
            assert "actor" in timeline_cols
            assert "actor_type" in timeline_cols
            assert "details" in timeline_cols
        engine.dispose()

        # Downgrade to base should clean up SQLite tables
        command.downgrade(alembic_cfg, "base")

        engine2 = create_engine(test_url)
        with engine2.connect() as conn:
            from sqlalchemy import inspect
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            assert "incidents" not in tables
            assert "incident_timeline_events" not in tables
        engine2.dispose()


# Optional: PostgreSQL live integration test if DATABASE_URL points to PostgreSQL
@pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL integration test requires active DATABASE_URL starting with postgresql",
)
class TestPostgreSQLIntegration:
    """Live PostgreSQL database integration tests exercising the Alembic-migrated schema."""

    @pytest.fixture
    def pg_engine(self):
        url = os.getenv("DATABASE_URL")
        engine = create_engine(url)
        # Verify schema exists from Alembic migration (do not bypass via ORM auto-creation)
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "incidents" in tables, "Table 'incidents' must exist via Alembic migration"
        assert "incident_timeline_events" in tables, "Table 'incident_timeline_events' must exist via Alembic migration"

        yield engine

        # Cleanup test records created during testing
        with Session(engine) as session:
            session.query(TimelineEventModel).filter(
                TimelineEventModel.incident_id.like("INC-PG-%")
            ).delete(synchronize_session=False)
            session.query(IncidentModel).filter(
                IncidentModel.incident_id.like("INC-PG-%")
            ).delete(synchronize_session=False)
            session.commit()
        engine.dispose()

    def test_pg_incident_crud_and_uniqueness(self, pg_engine) -> None:
        repo = IncidentRepository.from_engine(pg_engine)
        inc = make_sample_incident("INC-PG-1", "GRP-PG-1")
        repo.create(inc)

        fetched = repo.get_by_id("INC-PG-1")
        assert fetched is not None
        assert fetched.correlation_group_id == "GRP-PG-1"
        assert fetched.rca_confidence_score == 0.92
        assert len(fetched.timeline) == 1

        # Enforce unique correlation group constraint in Postgres
        with pytest.raises(DuplicateIncidentError):
            repo.create(make_sample_incident("INC-PG-2", "GRP-PG-1"))

    def test_pg_transactional_lifecycle_and_timeline_atomicity(self, pg_engine) -> None:
        repo = IncidentRepository.from_engine(pg_engine)
        inc = make_sample_incident("INC-PG-3", "GRP-PG-3")
        repo.create(inc)

        t_ack = inc.created_at + timedelta(minutes=10)
        acked = inc.acknowledge(actor="ops_eng", timestamp=t_ack)
        repo.update(acked)

        reloaded = repo.get_by_id("INC-PG-3")
        assert reloaded is not None
        assert reloaded.status == IncidentStatus.ACKNOWLEDGED
        assert len(reloaded.timeline) == 2

        t_res = inc.created_at + timedelta(minutes=35)
        resolved = reloaded.resolve(actor="ops_lead", timestamp=t_res, notes="Migrated fiber spliced")
        repo.update(resolved)

        final = repo.get_by_id("INC-PG-3")
        assert final is not None
        assert final.status == IncidentStatus.RESOLVED
        assert len(final.timeline) == 3
        assert final.timeline[2].details.get("resolution_notes") == "Migrated fiber spliced"
