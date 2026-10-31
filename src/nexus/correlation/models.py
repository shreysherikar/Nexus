"""Domain models and data structures for alarm correlation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import types
from typing import Any, Mapping, Optional, Sequence

from nexus.correlation.exceptions import InvalidCorrelationConfigError
from nexus.detection.models import Alarm, _freeze_evidence, _normalize_utc_timestamp
from nexus.topology.enums import NodeType


def _validate_finite_float(name: str, val: Any, min_val: Optional[float] = None) -> float:
    """Validate numeric parameter, rejecting booleans, NaN, and infinity."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise InvalidCorrelationConfigError(f"{name} must be numeric, got {type(val).__name__}")
    f_val = float(val)
    if not math.isfinite(f_val):
        raise InvalidCorrelationConfigError(f"{name} must be a finite number, got {f_val}")
    if min_val is not None and f_val < min_val:
        raise InvalidCorrelationConfigError(f"{name} ({f_val}) must be >= {min_val}")
    return f_val


def _validate_int(name: str, val: Any, min_val: int = 1) -> int:
    """Validate integer parameter, rejecting booleans and floats."""
    if isinstance(val, bool) or not isinstance(val, int):
        raise InvalidCorrelationConfigError(f"{name} must be an integer, got {type(val).__name__}")
    if val < min_val:
        raise InvalidCorrelationConfigError(f"{name} ({val}) must be >= {min_val}")
    return val


@dataclass(frozen=True)
class CorrelationConfig:
    """Configuration options for the AlarmCorrelationEngine.

    Attributes:
        time_window_seconds: Maximum time difference between alarm onsets to consider correlation (default 300s).
        max_ancestor_distance: Maximum hierarchy levels to search for shared dependency (default 2: Cell -> Site -> Agg).
        group_singletons: Whether isolated alarms form singleton CorrelationGroups (default True).
    """

    time_window_seconds: float = 300.0
    max_ancestor_distance: int = 2
    group_singletons: bool = True

    def __post_init__(self) -> None:
        tw = _validate_finite_float("time_window_seconds", self.time_window_seconds, min_val=0.001)
        object.__setattr__(self, "time_window_seconds", tw)

        dist = _validate_int("max_ancestor_distance", self.max_ancestor_distance, min_val=1)
        object.__setattr__(self, "max_ancestor_distance", dist)

        if not isinstance(self.group_singletons, bool):
            raise InvalidCorrelationConfigError("group_singletons must be a boolean")


@dataclass(frozen=True)
class CorrelationGroup:
    """An immutable group of alarms correlated by shared topological dependency and time window.

    Attributes:
        group_id: Unique deterministic identifier for the correlation group.
        anchor_node_id: Nearest meaningful shared ancestor node in the topology, or None.
        root_cause_tier: Topology tier of the anchor node (CORE, AGGREGATION, SITE, CELL), or None.
        alarms: Ordered tuple of Alarm records belonging to this group.
        alarm_ids: Tuple of alarm identifiers in this group.
        node_ids: Distinct node identifiers impacted by alarms in this group.
        time_window_start: Earliest first_seen timestamp among grouped alarms.
        time_window_end: Latest last_seen timestamp among grouped alarms.
        correlation_reason: Human-readable explanation of why these alarms were correlated.
        evidence: Contextual diagnostic data supporting the correlation decision.
    """

    group_id: str
    anchor_node_id: Optional[str]
    root_cause_tier: Optional[NodeType]
    alarms: tuple[Alarm, ...]
    alarm_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    time_window_start: datetime
    time_window_end: datetime
    correlation_reason: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.group_id, str) or not self.group_id.strip():
            raise ValueError("group_id must be a non-empty string")

        ws = _normalize_utc_timestamp("time_window_start", self.time_window_start)
        we = _normalize_utc_timestamp("time_window_end", self.time_window_end)
        object.__setattr__(self, "time_window_start", ws)
        object.__setattr__(self, "time_window_end", we)

        if not isinstance(self.alarms, tuple):
            object.__setattr__(self, "alarms", tuple(self.alarms))

        if not isinstance(self.alarm_ids, tuple):
            object.__setattr__(self, "alarm_ids", tuple(self.alarm_ids))

        if not isinstance(self.node_ids, tuple):
            object.__setattr__(self, "node_ids", tuple(self.node_ids))

        if not isinstance(self.evidence, Mapping):
            raise ValueError(f"evidence must be a mapping, got {type(self.evidence).__name__}")
        object.__setattr__(self, "evidence", _freeze_evidence(self.evidence))

    @property
    def alarm_count(self) -> int:
        """Total number of alarms contained in this correlation group."""
        return len(self.alarms)

    @property
    def is_singleton(self) -> bool:
        """Whether this correlation group contains exactly one alarm."""
        return len(self.alarms) == 1


@dataclass(frozen=True)
class CorrelationResult:
    """Immutable result of correlating a batch of alarms.

    Attributes:
        groups: Tuple of identified CorrelationGroup instances.
        total_alarms_processed: Total number of unique alarms evaluated.
        total_groups_formed: Total number of correlation groups created.
        singleton_groups_count: Number of groups containing exactly one alarm.
        multi_alarm_groups_count: Number of groups containing two or more alarms.
        reduction_ratio: Ratio of noise reduction: (total_alarms - total_groups) / total_alarms.
    """

    groups: tuple[CorrelationGroup, ...]
    total_alarms_processed: int
    total_groups_formed: int
    singleton_groups_count: int
    multi_alarm_groups_count: int
    reduction_ratio: float
