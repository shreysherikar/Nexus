"""SQLAlchemy 2.x persistence layer and repository for NEXUS Incidents."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any, Iterator, Mapping, Optional, Sequence

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    create_engine,
    desc,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from nexus.detection.models import _normalize_utc_timestamp
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
from nexus.rca.models import RootCauseType, TargetType


class Base(DeclarativeBase):
    """Declarative base for incident persistence models."""


class IncidentModel(Base):
    """SQLAlchemy model for an operational incident."""

    __tablename__ = "incidents"

    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    correlation_group_id: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    alarm_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    affected_node_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    suspected_cause_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    suspected_target_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    suspected_target_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    rca_confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rca_hypotheses: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    rca_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    ack_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolve_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    timeline_events: Mapped[list[TimelineEventModel]] = relationship(
        "TimelineEventModel",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="TimelineEventModel.timestamp",
    )


class TimelineEventModel(Base):
    """SQLAlchemy model for append-only timeline events."""

    __tablename__ = "incident_timeline_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("incidents.incident_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    incident: Mapped[IncidentModel] = relationship(
        "IncidentModel", back_populates="timeline_events"
    )


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a datetime object is timezone-aware in UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_domain_timeline_event(record: TimelineEventModel) -> TimelineEvent:
    return TimelineEvent(
        event_id=record.event_id,
        incident_id=record.incident_id,
        event_type=TimelineEventType(record.event_type),
        timestamp=_ensure_utc(record.timestamp),  # type: ignore[arg-type]
        actor=record.actor,
        actor_type=ActorType(record.actor_type),
        details=record.details,
    )


def _to_domain_incident(
    record: IncidentModel, events: Optional[Sequence[TimelineEventModel]] = None
) -> Incident:
    if events is None:
        events = record.timeline_events or []
    domain_events = tuple(_to_domain_timeline_event(e) for e in events)

    return Incident(
        incident_id=record.incident_id,
        correlation_group_id=record.correlation_group_id,
        status=IncidentStatus(record.status),
        severity=IncidentSeverity(record.severity),
        priority=IncidentPriority(record.priority),
        title=record.title,
        description=record.description,
        alarm_ids=tuple(record.alarm_ids),
        affected_node_ids=tuple(record.affected_node_ids),
        suspected_cause_type=RootCauseType(record.suspected_cause_type)
        if record.suspected_cause_type
        else None,
        suspected_target_id=record.suspected_target_id,
        suspected_target_type=TargetType(record.suspected_target_type)
        if record.suspected_target_type
        else None,
        rca_confidence_score=record.rca_confidence_score,
        rca_hypotheses=tuple(record.rca_hypotheses),
        rca_evidence=tuple(record.rca_evidence),
        created_at=_ensure_utc(record.created_at),  # type: ignore[arg-type]
        ack_deadline=_ensure_utc(record.ack_deadline),  # type: ignore[arg-type]
        resolve_deadline=_ensure_utc(record.resolve_deadline),  # type: ignore[arg-type]
        acknowledged_at=_ensure_utc(record.acknowledged_at),
        acknowledged_by=record.acknowledged_by,
        resolved_at=_ensure_utc(record.resolved_at),
        resolved_by=record.resolved_by,
        timeline=domain_events,
    )


class IncidentRepository:
    """Repository handling SQL persistence for incidents and timeline events."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @classmethod
    def from_engine(cls, engine: Engine) -> IncidentRepository:
        """Create a repository from an existing SQLAlchemy engine."""
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        return cls(factory)

    def create(self, incident: Incident) -> Incident:
        """Persist a new incident and its initial timeline events atomically."""
        with self._session_factory() as session:
            try:
                model = IncidentModel(
                    incident_id=incident.incident_id,
                    correlation_group_id=incident.correlation_group_id,
                    status=incident.status.value,
                    severity=incident.severity.value,
                    priority=incident.priority.value,
                    title=incident.title,
                    description=incident.description,
                    alarm_ids=list(incident.alarm_ids),
                    affected_node_ids=list(incident.affected_node_ids),
                    suspected_cause_type=incident.suspected_cause_type.value
                    if incident.suspected_cause_type
                    else None,
                    suspected_target_id=incident.suspected_target_id,
                    suspected_target_type=incident.suspected_target_type.value
                    if incident.suspected_target_type
                    else None,
                    rca_confidence_score=incident.rca_confidence_score,
                    rca_hypotheses=[dict(h) for h in incident.rca_hypotheses],
                    rca_evidence=[dict(e) for e in incident.rca_evidence],
                    created_at=incident.created_at,
                    ack_deadline=incident.ack_deadline,
                    resolve_deadline=incident.resolve_deadline,
                    acknowledged_at=incident.acknowledged_at,
                    acknowledged_by=incident.acknowledged_by,
                    resolved_at=incident.resolved_at,
                    resolved_by=incident.resolved_by,
                )
                session.add(model)

                for evt in incident.timeline:
                    evt_model = TimelineEventModel(
                        event_id=evt.event_id,
                        incident_id=incident.incident_id,
                        event_type=evt.event_type.value,
                        timestamp=evt.timestamp,
                        actor=evt.actor,
                        actor_type=evt.actor_type.value,
                        details=dict(evt.details),
                    )
                    session.add(evt_model)

                session.commit()
                return incident
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateIncidentError(incident.correlation_group_id) from exc
            except Exception:
                session.rollback()
                raise

    def get_by_id(self, incident_id: str) -> Optional[Incident]:
        """Fetch incident domain entity by ID including timeline."""
        with self._session_factory() as session:
            stmt = select(IncidentModel).where(IncidentModel.incident_id == incident_id)
            record = session.scalars(stmt).first()
            if not record:
                return None
            return _to_domain_incident(record)

    def get_by_correlation_group_id(self, correlation_group_id: str) -> Optional[Incident]:
        """Fetch incident by correlation group ID."""
        with self._session_factory() as session:
            stmt = select(IncidentModel).where(
                IncidentModel.correlation_group_id == correlation_group_id
            )
            record = session.scalars(stmt).first()
            if not record:
                return None
            return _to_domain_incident(record)

    def update(self, incident: Incident) -> Incident:
        """Update incident state and persist any new timeline events atomically."""
        with self._session_factory() as session:
            try:
                stmt = select(IncidentModel).where(IncidentModel.incident_id == incident.incident_id)
                record = session.scalars(stmt).first()
                if not record:
                    raise IncidentNotFoundError(incident.incident_id)

                record.status = incident.status.value
                record.severity = incident.severity.value
                record.priority = incident.priority.value
                record.acknowledged_at = incident.acknowledged_at
                record.acknowledged_by = incident.acknowledged_by
                record.resolved_at = incident.resolved_at
                record.resolved_by = incident.resolved_by

                # Check existing events to add only new ones
                existing_event_ids = set(
                    session.scalars(
                        select(TimelineEventModel.event_id).where(
                            TimelineEventModel.incident_id == incident.incident_id
                        )
                    ).all()
                )

                for evt in incident.timeline:
                    if evt.event_id not in existing_event_ids:
                        evt_model = TimelineEventModel(
                            event_id=evt.event_id,
                            incident_id=incident.incident_id,
                            event_type=evt.event_type.value,
                            timestamp=evt.timestamp,
                            actor=evt.actor,
                            actor_type=evt.actor_type.value,
                            details=dict(evt.details),
                        )
                        session.add(evt_model)

                session.commit()
                return incident
            except Exception:
                session.rollback()
                raise

    def list_incidents(
        self,
        status: Optional[IncidentStatus] = None,
        severity: Optional[IncidentSeverity] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Incident], int]:
        """List incidents with filtering and pagination, returning (items, total_count)."""
        with self._session_factory() as session:
            query = select(IncidentModel)
            count_query = select(func.count(IncidentModel.incident_id))

            if status is not None:
                query = query.where(IncidentModel.status == status.value)
                count_query = count_query.where(IncidentModel.status == status.value)
            if severity is not None:
                query = query.where(IncidentModel.severity == severity.value)
                count_query = count_query.where(IncidentModel.severity == severity.value)

            total = session.scalar(count_query) or 0
            query = query.order_by(desc(IncidentModel.created_at)).offset(offset).limit(limit)

            records = session.scalars(query).all()
            return [_to_domain_incident(r) for r in records], total

    def get_timeline(self, incident_id: str) -> list[TimelineEvent]:
        """Retrieve ordered timeline history for an incident."""
        with self._session_factory() as session:
            stmt = (
                select(TimelineEventModel)
                .where(TimelineEventModel.incident_id == incident_id)
                .order_by(TimelineEventModel.timestamp.asc())
            )
            records = session.scalars(stmt).all()
            return [_to_domain_timeline_event(r) for r in records]

    def iter_all_incidents(self, batch_size: int = 1000) -> Iterator[Incident]:
        """Iterate over all persisted incidents in batches without collection size limits.

        Ensures that large incident datasets contribute to operational metrics without truncation
        or high memory overhead.
        """
        with self._session_factory() as session:
            offset = 0
            while True:
                stmt = (
                    select(IncidentModel)
                    .order_by(IncidentModel.created_at.asc(), IncidentModel.incident_id.asc())
                    .offset(offset)
                    .limit(batch_size)
                )
                batch = session.scalars(stmt).all()
                if not batch:
                    break
                for record in batch:
                    yield _to_domain_incident(record)
                if len(batch) < batch_size:
                    break
                offset += batch_size

    def bulk_create(self, incidents: Sequence[Incident]) -> None:
        """Persist a collection of incidents efficiently in a single transaction."""
        with self._session_factory() as session:
            try:
                for inc in incidents:
                    model = IncidentModel(
                        incident_id=inc.incident_id,
                        correlation_group_id=inc.correlation_group_id,
                        status=inc.status.value,
                        severity=inc.severity.value,
                        priority=inc.priority.value,
                        title=inc.title,
                        description=inc.description,
                        alarm_ids=list(inc.alarm_ids),
                        affected_node_ids=list(inc.affected_node_ids),
                        suspected_cause_type=inc.suspected_cause_type.value
                        if inc.suspected_cause_type
                        else None,
                        suspected_target_id=inc.suspected_target_id,
                        suspected_target_type=inc.suspected_target_type.value
                        if inc.suspected_target_type
                        else None,
                        rca_confidence_score=inc.rca_confidence_score,
                        rca_hypotheses=[dict(h) for h in inc.rca_hypotheses],
                        rca_evidence=[dict(e) for e in inc.rca_evidence],
                        created_at=inc.created_at,
                        ack_deadline=inc.ack_deadline,
                        resolve_deadline=inc.resolve_deadline,
                        acknowledged_at=inc.acknowledged_at,
                        acknowledged_by=inc.acknowledged_by,
                        resolved_at=inc.resolved_at,
                        resolved_by=inc.resolved_by,
                    )
                    session.add(model)
                session.commit()
            except Exception:
                session.rollback()
                raise
