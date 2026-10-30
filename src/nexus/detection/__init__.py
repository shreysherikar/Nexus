"""NEXUS Anomaly Detection & Alarm Generation package."""

from nexus.detection.alarm_manager import AlarmManager
from nexus.detection.engine import AnomalyDetectionEngine, DetectionBatchResult
from nexus.detection.exceptions import (
    DetectionError,
    DuplicateObservationError,
    InvalidAlarmStateError,
    InvalidDetectorConfigError,
    InvalidRuleError,
    TelemetryOrderError,
)
from nexus.detection.models import (
    Alarm,
    AlarmStatus,
    AnomalyEvent,
    ComparisonOperator,
    DetectionSource,
    Severity,
)
from nexus.detection.rules import (
    RADIO_METRICS,
    SUPPORTED_METRICS,
    ThresholdRule,
    get_default_rules,
)
from nexus.detection.statistical_detector import (
    StatisticalDetector,
    StatisticalDetectorConfig,
)
from nexus.detection.threshold_detector import (
    ThresholdDetector,
    extract_snapshot_metrics,
)

__all__ = [
    "Alarm",
    "AlarmManager",
    "AlarmStatus",
    "AnomalyDetectionEngine",
    "AnomalyEvent",
    "ComparisonOperator",
    "DetectionBatchResult",
    "DetectionError",
    "DetectionSource",
    "DuplicateObservationError",
    "InvalidAlarmStateError",
    "InvalidDetectorConfigError",
    "InvalidRuleError",
    "RADIO_METRICS",
    "SUPPORTED_METRICS",
    "Severity",
    "StatisticalDetector",
    "StatisticalDetectorConfig",
    "TelemetryOrderError",
    "ThresholdDetector",
    "ThresholdRule",
    "extract_snapshot_metrics",
    "get_default_rules",
]
