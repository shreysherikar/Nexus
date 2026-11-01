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

from nexus.telemetry.orchestrator import (
    TelemetryPipeline,
    get_telemetry_pipeline,
    set_telemetry_pipeline,
)
from nexus.telemetry.store import (
    TelemetryStore,
    get_telemetry_store,
    set_telemetry_store,
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
    "TelemetryPipeline",
    "TelemetryStore",
    "get_telemetry_pipeline",
    "get_telemetry_store",
    "set_telemetry_pipeline",
    "set_telemetry_store",
]
