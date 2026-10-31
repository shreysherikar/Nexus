"""Initial incident and timeline schema.

Revision ID: 0001_initial_incident_schema
Revises:
Create Date: 2026-10-31 11:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_initial_incident_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create incidents table
    op.create_table(
        "incidents",
        sa.Column("incident_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_group_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("alarm_ids", sa.JSON(), nullable=False),
        sa.Column("affected_node_ids", sa.JSON(), nullable=False),
        sa.Column("suspected_cause_type", sa.String(length=64), nullable=True),
        sa.Column("suspected_target_id", sa.String(length=128), nullable=True),
        sa.Column("suspected_target_type", sa.String(length=32), nullable=True),
        sa.Column("rca_confidence_score", sa.Float(), nullable=True),
        sa.Column("rca_hypotheses", sa.JSON(), nullable=False),
        sa.Column("rca_evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ack_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolve_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("incident_id"),
        sa.UniqueConstraint("correlation_group_id", name="uq_incidents_correlation_group_id"),
    )

    op.create_index("ix_incidents_correlation_group_id", "incidents", ["correlation_group_id"], unique=True)
    op.create_index("ix_incidents_status", "incidents", ["status"], unique=False)
    op.create_index("ix_incidents_severity", "incidents", ["severity"], unique=False)
    op.create_index("ix_incidents_created_at", "incidents", ["created_at"], unique=False)

    # 2. Create incident_timeline_events table
    op.create_table(
        "incident_timeline_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("incident_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.incident_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )

    op.create_index("ix_incident_timeline_events_incident_id", "incident_timeline_events", ["incident_id"], unique=False)
    op.create_index("ix_incident_timeline_events_event_type", "incident_timeline_events", ["event_type"], unique=False)
    op.create_index("ix_incident_timeline_events_timestamp", "incident_timeline_events", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_incident_timeline_events_timestamp", table_name="incident_timeline_events")
    op.drop_index("ix_incident_timeline_events_event_type", table_name="incident_timeline_events")
    op.drop_index("ix_incident_timeline_events_incident_id", table_name="incident_timeline_events")
    op.drop_table("incident_timeline_events")

    op.drop_index("ix_incidents_created_at", table_name="incidents")
    op.drop_index("ix_incidents_severity", table_name="incidents")
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_index("ix_incidents_correlation_group_id", table_name="incidents")
    op.drop_table("incidents")
