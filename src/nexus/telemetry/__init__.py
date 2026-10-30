"""Telemetry domain package."""

from nexus.telemetry.exceptions import (
    IncompatibleNodeError,
    InvalidKPIValueError,
    InvalidProfileError,
    TelemetryError,
)
from nexus.telemetry.generator import SyntheticTelemetryGenerator
from nexus.telemetry.models import (
    KPISnapshot,
    PerformanceMetrics,
    RadioMetrics,
    ReliabilityMetrics,
)
from nexus.telemetry.profiles import (
    DEFAULT_AGGREGATION_PROFILE,
    DEFAULT_CELL_PROFILE,
    DEFAULT_CORE_PROFILE,
    DEFAULT_PROFILES,
    DEFAULT_SITE_PROFILE,
    MetricRange,
    NodeOperatingProfile,
)

__all__ = [
    "DEFAULT_AGGREGATION_PROFILE",
    "DEFAULT_CELL_PROFILE",
    "DEFAULT_CORE_PROFILE",
    "DEFAULT_PROFILES",
    "DEFAULT_SITE_PROFILE",
    "IncompatibleNodeError",
    "InvalidKPIValueError",
    "InvalidProfileError",
    "KPISnapshot",
    "MetricRange",
    "NodeOperatingProfile",
    "PerformanceMetrics",
    "RadioMetrics",
    "ReliabilityMetrics",
    "SyntheticTelemetryGenerator",
    "TelemetryError",
]
