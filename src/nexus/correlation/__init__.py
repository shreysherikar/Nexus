"""NEXUS Alarm Correlation package."""

from nexus.correlation.engine import AlarmCorrelationEngine
from nexus.correlation.exceptions import (
    CorrelationError,
    InvalidCorrelationConfigError,
    MalformedAlarmError,
)
from nexus.correlation.models import (
    CorrelationConfig,
    CorrelationGroup,
    CorrelationResult,
)

__all__ = [
    "AlarmCorrelationEngine",
    "CorrelationConfig",
    "CorrelationError",
    "CorrelationGroup",
    "CorrelationResult",
    "InvalidCorrelationConfigError",
    "MalformedAlarmError",
]
