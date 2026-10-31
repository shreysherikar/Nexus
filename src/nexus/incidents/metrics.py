"""Operational incident metrics and SLA performance reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional, Sequence

from nexus.detection.models import _normalize_utc_timestamp
from nexus.incidents.enums import IncidentSeverity, IncidentStatus
from nexus.incidents.models import Incident
from nexus.incidents.sla import SLACalculator


@dataclass(frozen=True)
class IncidentMetricsReport:
    """Consolidated operational metrics report for incidents and SLA performance.

    Definitions:
    - MTTA (Mean Time To Acknowledge): Average elapsed time in seconds from creation to acknowledgement
      (acknowledged_at - created_at) across all acknowledged incidents. None if no incidents are acknowledged.
    - MTTR (Mean Time To Resolve): Average elapsed time in seconds from creation to resolution
      (resolved_at - created_at) across all resolved incidents. Unresolved incidents are strictly excluded.
      None if no incidents are resolved.
    - MTTD (Mean Time To Detect): Mean detection latency from injected fault onset to first detection,
      derived strictly from detection evaluation records. None when unavailable.
    - Open incident count: Total count of active, unresolved incidents (status in [OPEN, ACKNOWLEDGED]).
    - Acknowledgement SLA breach count: Incidents where acknowledgement exceeded the SLA target.
    - Resolution SLA breach count: Incidents where resolution exceeded the SLA target.
    """

    total_incidents: int
    open_incident_count: int
    incidents_by_status: Mapping[str, int]
    incidents_by_severity: Mapping[str, int]
    mtta_seconds: Optional[float]
    mttr_seconds: Optional[float]
    mttd_seconds: Optional[float]
    ack_sla_breached_count: int
    resolve_sla_breached_count: int
    as_of: datetime


class MetricsCalculator:
    """Computes operational incident and SLA metrics deterministically."""

    def __init__(self, sla_calculator: Optional[SLACalculator] = None) -> None:
        self._sla_calc = sla_calculator or SLACalculator()

    def compute_metrics(
        self,
        incidents: Iterable[Incident],
        as_of: Optional[datetime] = None,
        mttd_seconds: Optional[float] = None,
    ) -> IncidentMetricsReport:
        """Compute operational metrics for a collection or stream of incidents with O(1) memory."""
        eval_time = _normalize_utc_timestamp("as_of", as_of) if as_of else datetime.now(timezone.utc)

        total_count = 0
        by_status: dict[str, int] = {s.value: 0 for s in IncidentStatus}
        by_severity: dict[str, int] = {s.value: 0 for s in IncidentSeverity}

        open_count = 0
        total_ack_seconds = 0.0
        count_ack = 0
        total_resolve_seconds = 0.0
        count_resolve = 0
        ack_breaches = 0
        resolve_breaches = 0

        for inc in incidents:
            total_count += 1
            by_status[inc.status.value] = by_status.get(inc.status.value, 0) + 1
            by_severity[inc.severity.value] = by_severity.get(inc.severity.value, 0) + 1

            if inc.status in (IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED):
                open_count += 1

            sla_status = inc.get_sla_status(self._sla_calc, evaluation_timestamp=eval_time)
            if sla_status.ack_breached:
                ack_breaches += 1
            if sla_status.resolve_breached:
                resolve_breaches += 1

            if sla_status.ack_time_seconds is not None:
                total_ack_seconds += sla_status.ack_time_seconds
                count_ack += 1

            if sla_status.resolve_time_seconds is not None:
                total_resolve_seconds += sla_status.resolve_time_seconds
                count_resolve += 1

        mtta = (total_ack_seconds / count_ack) if count_ack > 0 else None
        mttr = (total_resolve_seconds / count_resolve) if count_resolve > 0 else None

        return IncidentMetricsReport(
            total_incidents=total_count,
            open_incident_count=open_count,
            incidents_by_status=by_status,
            incidents_by_severity=by_severity,
            mtta_seconds=round(mtta, 2) if mtta is not None else None,
            mttr_seconds=round(mttr, 2) if mttr is not None else None,
            mttd_seconds=round(mttd_seconds, 2) if mttd_seconds is not None else None,
            ack_sla_breached_count=ack_breaches,
            resolve_sla_breached_count=resolve_breaches,
            as_of=eval_time,
        )
