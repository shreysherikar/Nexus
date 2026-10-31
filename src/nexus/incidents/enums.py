"""Enumerations for the NEXUS Incident Management Subsystem."""

from __future__ import annotations

from enum import Enum


class IncidentStatus(str, Enum):
    """Lifecycle status of a network incident."""

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"

    def __str__(self) -> str:
        return self.value


class IncidentSeverity(str, Enum):
    """Operational impact severity of an incident."""

    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    WARNING = "WARNING"
    MINOR = "MINOR"

    def __str__(self) -> str:
        return self.value


class IncidentPriority(str, Enum):
    """Operational dispatch priority corresponding to incident severity."""

    P1 = "P1"  # Critical operational urgency
    P2 = "P2"  # High operational urgency
    P3 = "P3"  # Medium operational urgency
    P4 = "P4"  # Low operational urgency

    def __str__(self) -> str:
        return self.value


class TimelineEventType(str, Enum):
    """Classification of events recorded in the append-only incident timeline."""

    CREATED = "CREATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    SEVERITY_CHANGED = "SEVERITY_CHANGED"
    SLA_BREACH_DETECTED = "SLA_BREACH_DETECTED"
    NOTE_ADDED = "NOTE_ADDED"

    def __str__(self) -> str:
        return self.value


class ActorType(str, Enum):
    """Entity initiating a state change or timeline event."""

    SYSTEM = "SYSTEM"
    OPERATOR = "OPERATOR"

    def __str__(self) -> str:
        return self.value
