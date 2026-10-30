"""Fault and Scenario domain models and enumerations."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Optional, Sequence

from nexus.fault.exceptions import InvalidFaultStateError


class FaultType(str, Enum):
    """Categorization of supported network fault types."""

    CELL_OUTAGE = "CELL_OUTAGE"
    BACKHAUL_FAILURE = "BACKHAUL_FAILURE"
    RADIO_INTERFERENCE = "RADIO_INTERFERENCE"
    CELL_CONGESTION = "CELL_CONGESTION"
    SITE_POWER_FAILURE = "SITE_POWER_FAILURE"

    def __str__(self) -> str:
        return self.value


class EffectDimension(str, Enum):
    """Operational effect dimensions influenced by injected faults."""

    AVAILABILITY = "AVAILABILITY"       # Outage / service availability
    RADIO_SIGNAL = "RADIO_SIGNAL"       # Signal quality (SINR, RSRP)
    RADIO_RESOURCE = "RADIO_RESOURCE"   # Resource utilization (PRB)
    PERFORMANCE = "PERFORMANCE"         # Throughput & latency
    RELIABILITY = "RELIABILITY"         # Drop rate & handover success rate

    def __str__(self) -> str:
        return self.value


FAULT_EFFECT_DIMENSIONS: dict[FaultType, frozenset[EffectDimension]] = {
    FaultType.CELL_OUTAGE: frozenset({
        EffectDimension.AVAILABILITY,
        EffectDimension.PERFORMANCE,
        EffectDimension.RELIABILITY,
        EffectDimension.RADIO_SIGNAL,
        EffectDimension.RADIO_RESOURCE,
    }),
    FaultType.BACKHAUL_FAILURE: frozenset({
        EffectDimension.AVAILABILITY,
        EffectDimension.PERFORMANCE,
        EffectDimension.RELIABILITY,
        EffectDimension.RADIO_SIGNAL,
        EffectDimension.RADIO_RESOURCE,
    }),
    FaultType.SITE_POWER_FAILURE: frozenset({
        EffectDimension.AVAILABILITY,
        EffectDimension.PERFORMANCE,
        EffectDimension.RELIABILITY,
        EffectDimension.RADIO_SIGNAL,
        EffectDimension.RADIO_RESOURCE,
    }),
    FaultType.RADIO_INTERFERENCE: frozenset({
        EffectDimension.RADIO_SIGNAL,
        EffectDimension.PERFORMANCE,
        EffectDimension.RELIABILITY,
    }),
    FaultType.CELL_CONGESTION: frozenset({
        EffectDimension.RADIO_RESOURCE,
        EffectDimension.PERFORMANCE,
    }),
}


def _normalize_utc_timestamp(name: str, ts: Any) -> datetime:
    """Validate and normalize a timestamp to UTC."""
    if not isinstance(ts, datetime):
        raise InvalidFaultStateError(f"{name} must be a datetime, got {type(ts).__name__}")
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _validate_severity(val: Any) -> float:
    """Validate severity as a finite real float within [0.0, 1.0], rejecting booleans."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise InvalidFaultStateError(f"severity must be a numeric value, got {type(val).__name__}")
    f_val = float(val)
    if not math.isfinite(f_val):
        raise InvalidFaultStateError(f"severity must be a finite number, got {f_val}")
    if not (0.0 <= f_val <= 1.0):
        raise InvalidFaultStateError(f"severity ({f_val}) must be within [0.0, 1.0]")
    return f_val


@dataclass(frozen=True)
class Fault:
    """Immutable representation of a controlled network fault.

    Active during the half-open interval: start_time <= timestamp < end_time.

    Attributes:
        fault_id: Unique string identifier for the fault.
        fault_type: Category of the fault (FaultType enum).
        target_id: Identifier of the target entity (cell node, site node, or transport link).
        start_time: Activation timestamp (normalized to UTC).
        end_time: Recovery timestamp (normalized to UTC, must be strictly greater than start_time).
        severity: Normalized fault intensity within [0.0, 1.0] (default 1.0).
        description: Optional human-readable notes.
    """

    fault_id: str
    fault_type: FaultType
    target_id: str
    start_time: datetime
    end_time: datetime
    severity: float = 1.0
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.fault_id, str) or not self.fault_id.strip():
            raise InvalidFaultStateError("fault_id must be a non-empty string")

        if not isinstance(self.fault_type, FaultType):
            try:
                coerced_type = FaultType(self.fault_type)
                object.__setattr__(self, "fault_type", coerced_type)
            except (ValueError, TypeError) as exc:
                raise InvalidFaultStateError(
                    f"Invalid fault_type '{self.fault_type}'. Expected one of: "
                    f"{', '.join(t.value for t in FaultType)}"
                ) from exc

        if not isinstance(self.target_id, str) or not self.target_id.strip():
            raise InvalidFaultStateError("target_id must be a non-empty string")

        start_utc = _normalize_utc_timestamp("start_time", self.start_time)
        end_utc = _normalize_utc_timestamp("end_time", self.end_time)
        object.__setattr__(self, "start_time", start_utc)
        object.__setattr__(self, "end_time", end_utc)

        if start_utc >= end_utc:
            raise InvalidFaultStateError(
                f"start_time ({start_utc.isoformat()}) must be strictly earlier than end_time ({end_utc.isoformat()})"
            )

        sev_v = _validate_severity(self.severity)
        object.__setattr__(self, "severity", sev_v)

        if self.description is not None and not isinstance(self.description, str):
            raise InvalidFaultStateError(
                f"description must be a string or None, got {type(self.description).__name__}"
            )

    def is_active_at(self, timestamp: datetime) -> bool:
        """Check if this fault is active at the given timestamp using the half-open interval [start, end)."""
        norm_ts = _normalize_utc_timestamp("timestamp", timestamp)
        return self.start_time <= norm_ts < self.end_time


@dataclass(frozen=True)
class GroundTruthRecord:
    """Immutable record capturing the exact ground truth impact of a fault in a scenario.

    Attributes:
        scenario_id: Identifier of the parent scenario.
        fault_id: Identifier of the injected fault.
        fault_type: Category of the fault.
        target_id: Target node or transport link ID.
        start_time: UTC activation timestamp.
        end_time: UTC recovery timestamp.
        severity: Fault severity.
        affected_node_ids: Deterministically ordered list/tuple of unique topology nodes impacted.
        description: Optional notes describing the fault scenario.
    """

    scenario_id: str
    fault_id: str
    fault_type: FaultType
    target_id: str
    start_time: datetime
    end_time: datetime
    severity: float
    affected_node_ids: tuple[str, ...]
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.scenario_id, str) or not self.scenario_id.strip():
            raise InvalidFaultStateError("scenario_id must be a non-empty string")

        if not isinstance(self.fault_id, str) or not self.fault_id.strip():
            raise InvalidFaultStateError("fault_id must be a non-empty string")

        if not isinstance(self.fault_type, FaultType):
            try:
                coerced_type = FaultType(self.fault_type)
                object.__setattr__(self, "fault_type", coerced_type)
            except (ValueError, TypeError) as exc:
                raise InvalidFaultStateError(
                    f"Invalid fault_type '{self.fault_type}'. Expected one of: "
                    f"{', '.join(t.value for t in FaultType)}"
                ) from exc

        if not isinstance(self.target_id, str) or not self.target_id.strip():
            raise InvalidFaultStateError("target_id must be a non-empty string")

        start_utc = _normalize_utc_timestamp("start_time", self.start_time)
        end_utc = _normalize_utc_timestamp("end_time", self.end_time)
        object.__setattr__(self, "start_time", start_utc)
        object.__setattr__(self, "end_time", end_utc)

        if start_utc >= end_utc:
            raise InvalidFaultStateError(
                f"start_time ({start_utc.isoformat()}) must be strictly earlier than end_time ({end_utc.isoformat()})"
            )

        sev_v = _validate_severity(self.severity)
        object.__setattr__(self, "severity", sev_v)

        if self.description is not None and not isinstance(self.description, str):
            raise InvalidFaultStateError(
                f"description must be a string or None, got {type(self.description).__name__}"
            )

        # Validate affected_node_ids
        if not isinstance(self.affected_node_ids, (tuple, list)):
            raise InvalidFaultStateError(
                f"affected_node_ids must be a sequence of non-empty strings, got {type(self.affected_node_ids).__name__}"
            )

        seen_nodes: set[str] = set()
        clean_nodes: list[str] = []
        for nid in self.affected_node_ids:
            if not isinstance(nid, str) or not nid.strip():
                raise InvalidFaultStateError("affected_node_ids cannot contain empty or non-string identifiers")
            clean_id = nid.strip()
            if clean_id in seen_nodes:
                raise InvalidFaultStateError(f"Duplicate node ID '{clean_id}' in affected_node_ids")
            seen_nodes.add(clean_id)
            clean_nodes.append(clean_id)

        object.__setattr__(self, "affected_node_ids", tuple(clean_nodes))
