"""Domain exceptions for the NEXUS Incident Management Subsystem."""

from __future__ import annotations


class IncidentDomainError(Exception):
    """Base exception for all incident management domain errors."""


class IncidentNotFoundError(IncidentDomainError):
    """Raised when an incident identifier cannot be found."""

    def __init__(self, incident_id: str) -> None:
        super().__init__(f"Incident '{incident_id}' not found.")
        self.incident_id = incident_id


class DuplicateIncidentError(IncidentDomainError):
    """Raised when an incident already exists for a given correlation group."""

    def __init__(self, correlation_group_id: str) -> None:
        super().__init__(
            f"An incident already exists for correlation group '{correlation_group_id}'."
        )
        self.correlation_group_id = correlation_group_id


class InvalidStateTransitionError(IncidentDomainError):
    """Raised when an illegal lifecycle transition is attempted."""

    def __init__(self, current_status: str, attempted_transition: str, reason: str = "") -> None:
        msg = f"Cannot transition incident from '{current_status}' via '{attempted_transition}'."
        if reason:
            msg += f" Reason: {reason}"
        super().__init__(msg)
        self.current_status = current_status
        self.attempted_transition = attempted_transition
        self.reason = reason


class InvalidIncidentDataError(IncidentDomainError):
    """Raised when incident parameters or payloads violate structural validation rules."""


class SLABreachCalculationError(IncidentDomainError):
    """Raised when SLA metrics or deadline calculations encounter invalid inputs."""
