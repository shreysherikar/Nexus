"""Configurable operating profiles defining normal synthetic baseline ranges."""

from dataclasses import dataclass
import math
from typing import Any, Optional

from nexus.telemetry.exceptions import InvalidProfileError
from nexus.topology.enums import NodeType


def _validate_profile_number(name: str, val: Any) -> float:
    """Validate that val is a finite real number (not bool, NaN, or inf)."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise InvalidProfileError(f"{name} must be a numeric value, got {type(val).__name__}")
    f_val = float(val)
    if not math.isfinite(f_val):
        raise InvalidProfileError(f"{name} must be a finite number, got {f_val}")
    return f_val


def _validate_metric_bounds(
    name: str,
    r: "MetricRange",
    min_limit: Optional[float] = None,
    max_limit: Optional[float] = None,
) -> None:
    """Validate that MetricRange bounds fall within physical/logical boundaries."""
    if min_limit is not None and r.min_val < min_limit:
        raise InvalidProfileError(
            f"{name} minimum ({r.min_val}) cannot be less than {min_limit}"
        )
    if max_limit is not None and r.max_val > max_limit:
        raise InvalidProfileError(
            f"{name} maximum ({r.max_val}) cannot exceed {max_limit}"
        )


@dataclass(frozen=True)
class MetricRange:
    """Bounded range [min_val, max_val] with nominal midpoint for synthetic generation."""

    min_val: float
    max_val: float
    nominal: float

    def __post_init__(self) -> None:
        min_v = _validate_profile_number("min_val", self.min_val)
        max_v = _validate_profile_number("max_val", self.max_val)
        nom_v = _validate_profile_number("nominal", self.nominal)

        object.__setattr__(self, "min_val", min_v)
        object.__setattr__(self, "max_val", max_v)
        object.__setattr__(self, "nominal", nom_v)

        if min_v > max_v:
            raise InvalidProfileError(
                f"min_val ({min_v}) cannot be greater than max_val ({max_v})"
            )
        if not (min_v <= nom_v <= max_v):
            raise InvalidProfileError(
                f"nominal ({nom_v}) must be within [{min_v}, {max_v}]"
            )


@dataclass(frozen=True)
class NodeOperatingProfile:
    """Baseline normal operating profile for a specific network tier.

    Attributes:
        node_type: Target hierarchy tier (CORE, AGGREGATION, SITE, CELL).
        throughput_mbps: Operational throughput range in Mbps (min >= 0.0).
        latency_ms: Normal latency range in ms (min >= 0.0).
        connection_drop_rate_pct: Expected packet/connection drop rate percentage within [0.0, 100.0].
        availability_pct: Expected availability percentage within [0.0, 100.0].
        handover_success_rate_pct: Expected handover success rate within [0.0, 100.0] (required for CELL, rejected for non-CELL).
        rsrp_dbm: Radio RSRP range within [-150.0, -30.0] (required for CELL, rejected for non-CELL).
        sinr_db: Radio SINR range within [-30.0, 50.0] (required for CELL, rejected for non-CELL).
        prb_utilization_pct: Radio PRB utilization range within [0.0, 100.0] (required for CELL, rejected for non-CELL).
    """

    node_type: NodeType
    throughput_mbps: MetricRange
    latency_ms: MetricRange
    connection_drop_rate_pct: MetricRange
    availability_pct: MetricRange
    handover_success_rate_pct: Optional[MetricRange] = None
    rsrp_dbm: Optional[MetricRange] = None
    sinr_db: Optional[MetricRange] = None
    prb_utilization_pct: Optional[MetricRange] = None

    def __post_init__(self) -> None:
        # 1. Validate node_type
        if not isinstance(self.node_type, NodeType):
            try:
                coerced_type = NodeType(self.node_type)
                object.__setattr__(self, "node_type", coerced_type)
            except (ValueError, TypeError) as exc:
                raise InvalidProfileError(
                    f"Invalid node_type '{self.node_type}'. Expected one of: "
                    f"{', '.join(t.value for t in NodeType)}"
                ) from exc

        # 2. Validate mandatory MetricRange instances
        required_ranges = [
            ("throughput_mbps", self.throughput_mbps),
            ("latency_ms", self.latency_ms),
            ("connection_drop_rate_pct", self.connection_drop_rate_pct),
            ("availability_pct", self.availability_pct),
        ]
        for name, r in required_ranges:
            if not isinstance(r, MetricRange):
                raise InvalidProfileError(
                    f"{name} must be an instance of MetricRange, got {type(r).__name__}"
                )

        # 3. Apply metric-specific semantic boundary constraints
        _validate_metric_bounds("throughput_mbps", self.throughput_mbps, min_limit=0.0)
        _validate_metric_bounds("latency_ms", self.latency_ms, min_limit=0.0)
        _validate_metric_bounds("connection_drop_rate_pct", self.connection_drop_rate_pct, min_limit=0.0, max_limit=100.0)
        _validate_metric_bounds("availability_pct", self.availability_pct, min_limit=0.0, max_limit=100.0)

        # 4. Validate tier-specific fields
        if self.node_type == NodeType.CELL:
            if self.handover_success_rate_pct is None:
                raise InvalidProfileError("CELL operating profile requires handover_success_rate_pct range")
            if not isinstance(self.handover_success_rate_pct, MetricRange):
                raise InvalidProfileError("handover_success_rate_pct must be an instance of MetricRange")
            _validate_metric_bounds("handover_success_rate_pct", self.handover_success_rate_pct, min_limit=0.0, max_limit=100.0)

            for name, r, min_lim, max_lim in [
                ("rsrp_dbm", self.rsrp_dbm, -150.0, -30.0),
                ("sinr_db", self.sinr_db, -30.0, 50.0),
                ("prb_utilization_pct", self.prb_utilization_pct, 0.0, 100.0),
            ]:
                if r is None:
                    raise InvalidProfileError(f"CELL operating profile requires {name} range")
                if not isinstance(r, MetricRange):
                    raise InvalidProfileError(f"{name} must be an instance of MetricRange")
                _validate_metric_bounds(name, r, min_limit=min_lim, max_limit=max_lim)
        else:
            # Reject radio-specific and handover metrics for non-CELL profiles
            if any(
                r is not None
                for r in (
                    self.rsrp_dbm,
                    self.sinr_db,
                    self.prb_utilization_pct,
                    self.handover_success_rate_pct,
                )
            ):
                raise InvalidProfileError(
                    f"{self.node_type.value} profile must not specify radio-only or handover ranges"
                )


# Default normal operating profiles across tiers
DEFAULT_CORE_PROFILE = NodeOperatingProfile(
    node_type=NodeType.CORE,
    throughput_mbps=MetricRange(min_val=8000.0, max_val=10000.0, nominal=9200.0),
    latency_ms=MetricRange(min_val=0.5, max_val=2.5, nominal=1.2),
    connection_drop_rate_pct=MetricRange(min_val=0.00, max_val=0.02, nominal=0.005),
    availability_pct=MetricRange(min_val=99.99, max_val=100.0, nominal=99.999),
)

DEFAULT_AGGREGATION_PROFILE = NodeOperatingProfile(
    node_type=NodeType.AGGREGATION,
    throughput_mbps=MetricRange(min_val=3000.0, max_val=5000.0, nominal=4200.0),
    latency_ms=MetricRange(min_val=2.0, max_val=6.0, nominal=3.5),
    connection_drop_rate_pct=MetricRange(min_val=0.01, max_val=0.05, nominal=0.02),
    availability_pct=MetricRange(min_val=99.95, max_val=100.0, nominal=99.99),
)

DEFAULT_SITE_PROFILE = NodeOperatingProfile(
    node_type=NodeType.SITE,
    throughput_mbps=MetricRange(min_val=800.0, max_val=1500.0, nominal=1100.0),
    latency_ms=MetricRange(min_val=6.0, max_val=14.0, nominal=9.0),
    connection_drop_rate_pct=MetricRange(min_val=0.02, max_val=0.10, nominal=0.04),
    availability_pct=MetricRange(min_val=99.90, max_val=100.0, nominal=99.95),
)

DEFAULT_CELL_PROFILE = NodeOperatingProfile(
    node_type=NodeType.CELL,
    throughput_mbps=MetricRange(min_val=150.0, max_val=450.0, nominal=320.0),
    latency_ms=MetricRange(min_val=12.0, max_val=28.0, nominal=18.0),
    connection_drop_rate_pct=MetricRange(min_val=0.05, max_val=0.50, nominal=0.15),
    availability_pct=MetricRange(min_val=99.50, max_val=100.0, nominal=99.85),
    handover_success_rate_pct=MetricRange(min_val=98.0, max_val=100.0, nominal=99.4),
    rsrp_dbm=MetricRange(min_val=-105.0, max_val=-75.0, nominal=-88.0),
    sinr_db=MetricRange(min_val=10.0, max_val=30.0, nominal=20.0),
    prb_utilization_pct=MetricRange(min_val=20.0, max_val=65.0, nominal=42.0),
)

DEFAULT_PROFILES: dict[NodeType, NodeOperatingProfile] = {
    NodeType.CORE: DEFAULT_CORE_PROFILE,
    NodeType.AGGREGATION: DEFAULT_AGGREGATION_PROFILE,
    NodeType.SITE: DEFAULT_SITE_PROFILE,
    NodeType.CELL: DEFAULT_CELL_PROFILE,
}
