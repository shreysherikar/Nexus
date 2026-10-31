"""SLA management, deadline calculation, and breach evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from nexus.detection.models import _normalize_utc_timestamp
from nexus.incidents.enums import IncidentSeverity
from nexus.incidents.exceptions import SLABreachCalculationError


def _validate_sla_duration(val: Any, field_name: str) -> float:
    """Validate SLA target duration: strictly rejects booleans, NaN, infinities, zero, and negative values."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise SLABreachCalculationError(
            f"{field_name} must be numeric, got {type(val).__name__}"
        )
    f_val = float(val)
    if not math.isfinite(f_val):
        raise SLABreachCalculationError(f"{field_name} must be finite, got {f_val}")
    if f_val <= 0.0:
        raise SLABreachCalculationError(f"{field_name} must be positive, got {f_val}")
    return f_val


@dataclass(frozen=True)
class SLATarget:
    """Configurable SLA duration targets for an incident severity level.

    Attributes:
        ack_target_minutes: Maximum duration from creation to acknowledgement.
        resolve_target_minutes: Maximum duration from creation to resolution.
    """

    ack_target_minutes: float
    resolve_target_minutes: float

    def __post_init__(self) -> None:
        ack = _validate_sla_duration(self.ack_target_minutes, "ack_target_minutes")
        res = _validate_sla_duration(self.resolve_target_minutes, "resolve_target_minutes")
        if res < ack:
            raise SLABreachCalculationError(
                "resolve_target_minutes cannot be less than ack_target_minutes"
            )
        object.__setattr__(self, "ack_target_minutes", ack)
        object.__setattr__(self, "resolve_target_minutes", res)


@dataclass(frozen=True)
class SLADeadlines:
    """Calculated absolute deadline timestamps for an incident."""

    ack_deadline: datetime
    resolve_deadline: datetime

    def __post_init__(self) -> None:
        ad = _normalize_utc_timestamp("ack_deadline", self.ack_deadline)
        rd = _normalize_utc_timestamp("resolve_deadline", self.resolve_deadline)
        object.__setattr__(self, "ack_deadline", ad)
        object.__setattr__(self, "resolve_deadline", rd)


@dataclass(frozen=True)
class SLABreachStatus:
    """Evaluation of SLA compliance as of a specific evaluation timestamp.

    Attributes:
        ack_breached: Whether acknowledgement target was or is currently breached.
        resolve_breached: Whether resolution target was or is currently breached.
        ack_time_seconds: Elapsed duration in seconds from creation to acknowledgement, if acknowledged.
        resolve_time_seconds: Elapsed duration in seconds from creation to resolution, if resolved.
        evaluation_timestamp: UTC timestamp at which this status was computed.
    """

    ack_breached: bool
    resolve_breached: bool
    ack_time_seconds: Optional[float]
    resolve_time_seconds: Optional[float]
    evaluation_timestamp: datetime


# Standard operational default targets per severity
DEFAULT_SLA_TARGETS: Mapping[IncidentSeverity, SLATarget] = {
    IncidentSeverity.CRITICAL: SLATarget(ack_target_minutes=15.0, resolve_target_minutes=60.0),
    IncidentSeverity.MAJOR: SLATarget(ack_target_minutes=30.0, resolve_target_minutes=240.0),
    IncidentSeverity.WARNING: SLATarget(ack_target_minutes=60.0, resolve_target_minutes=720.0),
    IncidentSeverity.MINOR: SLATarget(ack_target_minutes=120.0, resolve_target_minutes=1440.0),
}


class SLACalculator:
    """Deterministic, timezone-safe SLA calculator and deadline evaluator."""

    def __init__(
        self,
        targets: Optional[Mapping[IncidentSeverity, SLATarget]] = None,
    ) -> None:
        self._targets = dict(targets or DEFAULT_SLA_TARGETS)

    def get_target(self, severity: IncidentSeverity) -> SLATarget:
        """Retrieve SLA target configuration for a given severity."""
        if severity not in self._targets:
            raise SLABreachCalculationError(f"No SLA target configured for severity '{severity}'.")
        return self._targets[severity]

    def calculate_deadlines(
        self,
        created_at: datetime,
        severity: IncidentSeverity,
    ) -> SLADeadlines:
        """Compute absolute UTC acknowledgement and resolution deadlines from creation timestamp."""
        norm_created_at = _normalize_utc_timestamp("created_at", created_at)
        target = self.get_target(severity)

        ack_deadline = norm_created_at + timedelta(minutes=target.ack_target_minutes)
        resolve_deadline = norm_created_at + timedelta(minutes=target.resolve_target_minutes)

        return SLADeadlines(
            ack_deadline=ack_deadline,
            resolve_deadline=resolve_deadline,
        )

    def evaluate_sla(
        self,
        created_at: datetime,
        ack_deadline: datetime,
        resolve_deadline: datetime,
        acknowledged_at: Optional[datetime],
        resolved_at: Optional[datetime],
        evaluation_timestamp: Optional[datetime] = None,
    ) -> SLABreachStatus:
        """Evaluate acknowledgement and resolution SLA compliance deterministically.

        Rules:
        - If acknowledged: breach occurs if acknowledged_at > ack_deadline.
        - If not yet acknowledged: breach occurs if evaluation_timestamp > ack_deadline.
        - If resolved: breach occurs if resolved_at > resolve_deadline.
        - If not yet resolved: breach occurs if evaluation_timestamp > resolve_deadline.
        - Once resolved, breach status is frozen based on actual historical timestamps.
        """
        norm_created_at = _normalize_utc_timestamp("created_at", created_at)
        norm_ack_deadline = _normalize_utc_timestamp("ack_deadline", ack_deadline)
        norm_resolve_deadline = _normalize_utc_timestamp("resolve_deadline", resolve_deadline)

        if evaluation_timestamp is not None:
            now = _normalize_utc_timestamp("evaluation_timestamp", evaluation_timestamp)
        else:
            now = datetime.now(timezone.utc)

        # Acknowledgement evaluation
        ack_time_seconds: Optional[float] = None
        if acknowledged_at is not None:
            norm_ack_at = _normalize_utc_timestamp("acknowledged_at", acknowledged_at)
            ack_time_seconds = max(0.0, (norm_ack_at - norm_created_at).total_seconds())
            ack_breached = norm_ack_at > norm_ack_deadline
        else:
            ack_breached = now > norm_ack_deadline

        # Resolution evaluation
        resolve_time_seconds: Optional[float] = None
        if resolved_at is not None:
            norm_res_at = _normalize_utc_timestamp("resolved_at", resolved_at)
            resolve_time_seconds = max(0.0, (norm_res_at - norm_created_at).total_seconds())
            resolve_breached = norm_res_at > norm_resolve_deadline
        else:
            resolve_breached = now > norm_resolve_deadline

        return SLABreachStatus(
            ack_breached=ack_breached,
            resolve_breached=resolve_breached,
            ack_time_seconds=ack_time_seconds,
            resolve_time_seconds=resolve_time_seconds,
            evaluation_timestamp=now,
        )
