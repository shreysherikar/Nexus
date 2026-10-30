"""Domain exceptions for anomaly detection and alarm management."""


class DetectionError(Exception):
    """Base exception for all anomaly detection errors."""


class InvalidRuleError(DetectionError, ValueError):
    """Raised when a threshold rule definition is invalid."""


class InvalidDetectorConfigError(DetectionError, ValueError):
    """Raised when statistical detector configuration violates validation constraints."""


class InvalidAlarmStateError(DetectionError, ValueError):
    """Raised when an alarm model or lifecycle state transition is invalid."""


class DuplicateObservationError(DetectionError, ValueError):
    """Raised when duplicate observations for the same node and timestamp are ingested."""


class TelemetryOrderError(DetectionError, ValueError):
    """Raised when telemetry snapshots arrive out of chronological order for a node."""
