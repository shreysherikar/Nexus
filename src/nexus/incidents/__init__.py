"""NEXUS Incident Management and SLA Tracking Subsystem."""

from __future__ import annotations

from nexus.incidents.api import app, create_app, router
from nexus.incidents.enums import (
    ActorType,
    IncidentPriority,
    IncidentSeverity,
    IncidentStatus,
    TimelineEventType,
)
from nexus.incidents.exceptions import (
    DuplicateIncidentError,
    IncidentDomainError,
    IncidentNotFoundError,
    InvalidIncidentDataError,
    InvalidStateTransitionError,
    SLABreachCalculationError,
)
from nexus.incidents.metrics import IncidentMetricsReport, MetricsCalculator
from nexus.incidents.models import Incident, TimelineEvent
from nexus.incidents.repository import IncidentModel, IncidentRepository, TimelineEventModel
from nexus.incidents.severity import OperationalSeverityPolicy
from nexus.incidents.service import IncidentService
from nexus.incidents.sla import (
    DEFAULT_SLA_TARGETS,
    SLABreachStatus,
    SLACalculator,
    SLADeadlines,
    SLATarget,
)

__all__ = [
    # Enums
    "IncidentStatus",
    "IncidentSeverity",
    "IncidentPriority",
    "TimelineEventType",
    "ActorType",
    # Domain Models
    "Incident",
    "TimelineEvent",
    # SLA
    "SLATarget",
    "SLADeadlines",
    "SLABreachStatus",
    "SLACalculator",
    "DEFAULT_SLA_TARGETS",
    # Severity
    "OperationalSeverityPolicy",
    # Persistence
    "IncidentModel",
    "TimelineEventModel",
    "IncidentRepository",
    # Service & Metrics
    "IncidentService",
    "IncidentMetricsReport",
    "MetricsCalculator",
    # Exceptions
    "IncidentDomainError",
    "IncidentNotFoundError",
    "DuplicateIncidentError",
    "InvalidStateTransitionError",
    "InvalidIncidentDataError",
    "SLABreachCalculationError",
    # API
    "app",
    "create_app",
    "router",
]
