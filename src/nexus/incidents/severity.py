"""Configurable operational-impact severity policy for incidents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from nexus.correlation.models import CorrelationGroup
from nexus.detection.models import Severity
from nexus.incidents.enums import IncidentPriority, IncidentSeverity
from nexus.topology.enums import NodeType


SEVERITY_TO_PRIORITY: dict[IncidentSeverity, IncidentPriority] = {
    IncidentSeverity.CRITICAL: IncidentPriority.P1,
    IncidentSeverity.MAJOR: IncidentPriority.P2,
    IncidentSeverity.WARNING: IncidentPriority.P3,
    IncidentSeverity.MINOR: IncidentPriority.P4,
}


@dataclass(frozen=True)
class OperationalSeverityPolicy:
    """Configurable policy determining incident severity from network operational impact.

    Assumptions & Guarantees:
    - Independent of RCA confidence score (a low-confidence or UNKNOWN RCA on a critical core trunk is still CRITICAL).
    - Driven by topological tier, alarm severity, blast radius (node count), and service impact.
    """

    critical_node_count_threshold: int = 5
    major_node_count_threshold: int = 3

    def evaluate(self, group: CorrelationGroup) -> IncidentSeverity:
        """Evaluate operational impact of a correlation group and assign incident severity.

        Classification Hierarchy:
        1. CRITICAL (P1):
           - Any CRITICAL alarm on CORE or AGGREGATION tier.
           - Any CRITICAL alarm impacting >= critical_node_count_threshold (default 5) nodes.
        2. MAJOR (P2):
           - Any CRITICAL alarm on SITE or CELL tier.
           - Any MAJOR alarm on CORE or AGGREGATION tier.
           - Any MAJOR alarm impacting >= major_node_count_threshold (default 3) nodes.
        3. WARNING (P3):
           - Any MAJOR alarm on SITE or CELL tier.
           - Multiple affected nodes (>= 2) with WARNING alarms.
        4. MINOR (P4):
           - Isolated single-node WARNING alarm.
        """
        # Collect alarm severities
        alarm_severities = [a.severity for a in group.alarms]
        has_critical_alarm = Severity.CRITICAL in alarm_severities
        has_major_alarm = Severity.MAJOR in alarm_severities
        affected_count = len(group.node_ids)
        tier = group.root_cause_tier

        # Rule 1: High tier or wide blast radius with Critical alarm
        if has_critical_alarm:
            if tier in (NodeType.CORE, NodeType.AGGREGATION) or affected_count >= self.critical_node_count_threshold:
                return IncidentSeverity.CRITICAL

        # Rule 2: Critical alarm at access tier or Major alarm on backbone
        if has_critical_alarm:
            return IncidentSeverity.MAJOR
        if has_major_alarm and (
            tier in (NodeType.CORE, NodeType.AGGREGATION)
            or affected_count >= self.major_node_count_threshold
        ):
            return IncidentSeverity.MAJOR

        # Rule 3: Major alarm at access tier or multi-node warning
        if has_major_alarm or affected_count >= 2:
            return IncidentSeverity.WARNING

        # Rule 4: Isolated minor condition
        return IncidentSeverity.MINOR

    def get_priority(self, severity: IncidentSeverity) -> IncidentPriority:
        """Map incident severity to operational dispatch priority."""
        return SEVERITY_TO_PRIORITY[severity]
