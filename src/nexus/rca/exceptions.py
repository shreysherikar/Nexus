"""Domain exceptions for the Root Cause Analysis (RCA) subsystem."""


class RCAError(Exception):
    """Base exception for all root cause analysis errors."""


class InvalidRCAConfigError(RCAError):
    """Raised when RCA engine configuration is invalid."""


class InsufficientTelemetryError(RCAError):
    """Raised when telemetry provided to the RCA engine is malformed."""
