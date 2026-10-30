"""Telemetry domain exceptions."""


class TelemetryError(Exception):
    """Base exception for telemetry domain errors."""


class InvalidKPIValueError(TelemetryError, ValueError):
    """Raised when a KPI value violates physical or logical boundaries."""


class InvalidProfileError(TelemetryError, ValueError):
    """Raised when an operating profile is improperly configured."""


class IncompatibleNodeError(TelemetryError, ValueError):
    """Raised when generating measurements for a node type incompatible with the profile."""
