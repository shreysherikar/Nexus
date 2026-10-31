"""Domain exceptions for the alarm correlation subsystem."""


class CorrelationError(Exception):
    """Base exception for all alarm correlation errors."""


class InvalidCorrelationConfigError(CorrelationError, ValueError):
    """Raised when correlation engine configuration is invalid."""


class MalformedAlarmError(CorrelationError, TypeError):
    """Raised when an alarm object or collection is malformed."""
