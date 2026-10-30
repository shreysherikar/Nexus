"""Typed, validated domain models for network telemetry and KPI measurements."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Optional

from nexus.telemetry.exceptions import InvalidKPIValueError


def _validate_bounded(
    name: str,
    val: Any,
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
) -> float:
    """Validate that val is a finite real number within optional [min_val, max_val] bounds.

    Rejects:
    - Booleans (bool is a subclass of int in Python)
    - Non-numeric types
    - NaN
    - Positive and negative infinity
    - Values violating min_val or max_val
    """
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise InvalidKPIValueError(f"{name} must be a numeric value, got {type(val).__name__}")
    f_val = float(val)
    if not math.isfinite(f_val):
        raise InvalidKPIValueError(f"{name} must be a finite number, got {f_val}")
    if min_val is not None and f_val < min_val:
        raise InvalidKPIValueError(f"{name} ({f_val}) cannot be less than {min_val}")
    if max_val is not None and f_val > max_val:
        raise InvalidKPIValueError(f"{name} ({f_val}) cannot exceed {max_val}")
    return f_val


@dataclass(frozen=True)
class RadioMetrics:
    """Cell radio measurement vector.

    Attributes:
        rsrp_dbm: Reference Signal Received Power in dBm (typical normal range -140 to -40).
        sinr_db: Signal-to-Interference-plus-Noise Ratio in dB (typical normal range -20 to 40).
        prb_utilization_pct: Physical Resource Block utilization percentage [0.0, 100.0].
    """

    rsrp_dbm: float
    sinr_db: float
    prb_utilization_pct: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "rsrp_dbm",
            _validate_bounded("rsrp_dbm", self.rsrp_dbm, min_val=-150.0, max_val=-30.0),
        )
        object.__setattr__(
            self,
            "sinr_db",
            _validate_bounded("sinr_db", self.sinr_db, min_val=-30.0, max_val=50.0),
        )
        object.__setattr__(
            self,
            "prb_utilization_pct",
            _validate_bounded("prb_utilization_pct", self.prb_utilization_pct, min_val=0.0, max_val=100.0),
        )


@dataclass(frozen=True)
class PerformanceMetrics:
    """Network transport and performance measurement vector.

    Attributes:
        throughput_mbps: Data transfer rate in Megabits per second (finite, >= 0.0).
        latency_ms: Round-trip / processing latency in milliseconds (finite, >= 0.0).
    """

    throughput_mbps: float
    latency_ms: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "throughput_mbps",
            _validate_bounded("throughput_mbps", self.throughput_mbps, min_val=0.0),
        )
        object.__setattr__(
            self,
            "latency_ms",
            _validate_bounded("latency_ms", self.latency_ms, min_val=0.0),
        )


@dataclass(frozen=True)
class ReliabilityMetrics:
    """Service and session reliability measurement vector.

    Attributes:
        connection_drop_rate_pct: Unplanned disconnection rate percentage [0.0, 100.0].
        availability_pct: Operational service availability percentage [0.0, 100.0].
        handover_success_rate_pct: Successful handovers percentage [0.0, 100.0] or None for non-radio.
    """

    connection_drop_rate_pct: float
    availability_pct: float
    handover_success_rate_pct: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "connection_drop_rate_pct",
            _validate_bounded("connection_drop_rate_pct", self.connection_drop_rate_pct, min_val=0.0, max_val=100.0),
        )
        object.__setattr__(
            self,
            "availability_pct",
            _validate_bounded("availability_pct", self.availability_pct, min_val=0.0, max_val=100.0),
        )
        if self.handover_success_rate_pct is not None:
            object.__setattr__(
                self,
                "handover_success_rate_pct",
                _validate_bounded("handover_success_rate_pct", self.handover_success_rate_pct, min_val=0.0, max_val=100.0),
            )


@dataclass(frozen=True)
class KPISnapshot:
    """Point-in-time telemetry snapshot associated with a specific topology node.

    Attributes:
        node_id: Identifier of the network node emitting this snapshot.
        timestamp: Timestamp normalized to UTC timezone.
        performance: Throughput and latency measurements.
        reliability: Drop rate, availability, and optional handover rates.
        radio: Optional radio metrics (present on radio CELL nodes).
    """

    node_id: str
    timestamp: datetime
    performance: PerformanceMetrics
    reliability: ReliabilityMetrics
    radio: Optional[RadioMetrics] = None

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise InvalidKPIValueError("node_id must be a non-empty string")

        if not isinstance(self.timestamp, datetime):
            raise InvalidKPIValueError(f"timestamp must be a datetime, got {type(self.timestamp).__name__}")

        # Timestamp normalization:
        # If naive (no tzinfo or tzinfo is None), interpret as UTC.
        # If aware, convert to UTC preserving the represented instant.
        if self.timestamp.tzinfo is None or self.timestamp.tzinfo.utcoffset(self.timestamp) is None:
            norm_ts = self.timestamp.replace(tzinfo=timezone.utc)
        else:
            norm_ts = self.timestamp.astimezone(timezone.utc)
        object.__setattr__(self, "timestamp", norm_ts)

        if not isinstance(self.performance, PerformanceMetrics):
            raise InvalidKPIValueError("performance must be an instance of PerformanceMetrics")

        if not isinstance(self.reliability, ReliabilityMetrics):
            raise InvalidKPIValueError("reliability must be an instance of ReliabilityMetrics")

        if self.radio is not None and not isinstance(self.radio, RadioMetrics):
            raise InvalidKPIValueError("radio must be None or an instance of RadioMetrics")

    def to_metric_dict(self) -> dict[str, Any]:
        """Flatten snapshot into standard key-value metric pairs for export / serialization."""
        data: dict[str, Any] = {
            "node_id": self.node_id,
            "timestamp": self.timestamp.isoformat(),
            "throughput_mbps": self.performance.throughput_mbps,
            "latency_ms": self.performance.latency_ms,
            "connection_drop_rate_pct": self.reliability.connection_drop_rate_pct,
            "availability_pct": self.reliability.availability_pct,
        }
        if self.reliability.handover_success_rate_pct is not None:
            data["handover_success_rate_pct"] = self.reliability.handover_success_rate_pct
        if self.radio is not None:
            data["rsrp_dbm"] = self.radio.rsrp_dbm
            data["sinr_db"] = self.radio.sinr_db
            data["prb_utilization_pct"] = self.radio.prb_utilization_pct
        return data
