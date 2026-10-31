"""Deterministic alarm correlation engine."""

from collections import deque
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from nexus.correlation.exceptions import (
    CorrelationError,
    InvalidCorrelationConfigError,
    MalformedAlarmError,
)
from nexus.correlation.models import (
    CorrelationConfig,
    CorrelationGroup,
    CorrelationResult,
)
from nexus.detection.models import Alarm
from nexus.topology.enums import NodeType
from nexus.topology.topology import Topology
from nexus.transport.network import TransportNetwork


# Symptom metric classification for compatibility evaluation
RADIO_METRICS = frozenset({"sinr_db", "rsrp_dbm"})
CONGESTION_METRICS = frozenset({"prb_utilization_pct"})
LOCALIZED_METRICS = RADIO_METRICS | CONGESTION_METRICS
SYSTEMIC_BRANCH_METRICS = frozenset({
    "availability_pct",
    "latency_ms",
    "throughput_mbps",
    "connection_drop_rate_pct",
    "handover_success_rate_pct",
})


def _get_node_lineage(node_id: str, topology: Topology) -> list[str]:
    """Return the bottom-up lineage [node_id, parent_id, grandparent_id, ...] to root."""
    if not topology.has_node(node_id):
        return [node_id]
    lineage = [node_id]
    curr_id = topology.get_node(node_id).parent_id
    while curr_id is not None:
        lineage.append(curr_id)
        if topology.has_node(curr_id):
            curr_id = topology.get_node(curr_id).parent_id
        else:
            break
    return lineage


def _find_lca(node_a: str, node_b: str, topology: Topology) -> tuple[Optional[str], int, int]:
    """Find Lowest Common Ancestor (LCA) between two nodes in topology and their hop distances."""
    lineage_a = _get_node_lineage(node_a, topology)
    lineage_b = _get_node_lineage(node_b, topology)

    set_b = {nid: idx for idx, nid in enumerate(lineage_b)}
    for dist_a, nid in enumerate(lineage_a):
        if nid in set_b:
            dist_b = set_b[nid]
            return nid, dist_a, dist_b

    return None, -1, -1


def _find_group_lca(node_ids: Sequence[str], topology: Topology) -> Optional[str]:
    """Find the Lowest Common Ancestor across a collection of node identifiers."""
    valid_nodes = [nid for nid in node_ids if topology.has_node(nid)]
    if not valid_nodes:
        return node_ids[0] if node_ids else None
    if len(valid_nodes) == 1:
        return valid_nodes[0]

    # Intersect lineages starting with the first node's lineage
    common_ancestors = _get_node_lineage(valid_nodes[0], topology)
    for other_node in valid_nodes[1:]:
        other_lineage_set = set(_get_node_lineage(other_node, topology))
        common_ancestors = [nid for nid in common_ancestors if nid in other_lineage_set]
        if not common_ancestors:
            return None

    return common_ancestors[0] if common_ancestors else None


def _are_symptoms_compatible(a1: Alarm, a2: Alarm) -> bool:
    """Evaluate whether symptoms on different nodes represent compatible aspects of a shared fault."""
    m1 = a1.metric_name
    m2 = a2.metric_name

    # If alarms are on different nodes, localized radio or resource metrics
    # must never correlate with another node.
    if a1.node_id != a2.node_id:
        if m1 in LOCALIZED_METRICS or m2 in LOCALIZED_METRICS:
            return False

    # 1. Identical metrics on different nodes are compatible
    if m1 == m2:
        return True

    # 2. Both metrics are systemic transport / availability / performance degradation
    if m1 in SYSTEMIC_BRANCH_METRICS and m2 in SYSTEMIC_BRANCH_METRICS:
        return True

    return False


class AlarmCorrelationEngine:
    """Correlates point-in-time alarm observations into coherent, immutable correlation groups.

    Invariants and Policies:
    - Independent Packages: Never imports, consumes, or inspects fault definitions or ground-truth records.
    - Non-Mutating: Original alarm objects and input collections are never modified.
    - Topological Hierarchy: Correlates alarms based strictly on topology hierarchy (lineage,
      Lowest Common Ancestor, and parent-child/sibling relationships) and symptom compatibility.
      Transport link dependencies and routing paths are intentionally resolved downstream during
      Root Cause Analysis (RCA), where link-level targets are identified; the correlation engine
      relies on the topology hierarchy rather than transport routing.
    - Time-Span Invariant: Enforces a strict maximum onset-time span (max first_seen - min first_seen
      <= time_window_seconds) for every formed correlation group, preventing uncontrolled transitive
      time-window chaining.
    - Near-Ancestor Preference: Prefers nearest meaningful topological dependencies (Site, Aggregation)
      and never merges alarms merely because they share a distant ancestor like CORE.
    - Determinism: Identical inputs produce identical groups and ordering.
    - Singleton Support: Preserves isolated alarms as independent singleton groups when configured.
    """

    def __init__(
        self,
        config: Optional[CorrelationConfig] = None,
        topology: Optional[Topology] = None,
        transport: Optional[TransportNetwork] = None,
    ) -> None:
        if config is not None and not isinstance(config, CorrelationConfig):
            raise TypeError(f"Expected CorrelationConfig instance, got {type(config).__name__}")
        if topology is not None and not isinstance(topology, Topology):
            raise TypeError(f"Expected Topology instance, got {type(topology).__name__}")
        if transport is not None and not isinstance(transport, TransportNetwork):
            raise TypeError(f"Expected TransportNetwork instance, got {type(transport).__name__}")
        self._config = config if config is not None else CorrelationConfig()
        self._topology = topology
        self._transport = transport

    @property
    def config(self) -> CorrelationConfig:
        return self._config

    @property
    def topology(self) -> Optional[Topology]:
        return self._topology

    @property
    def transport(self) -> Optional[TransportNetwork]:
        return self._transport

    def _can_correlate(
        self,
        a1: Alarm,
        a2: Alarm,
        topology: Topology,
        transport: Optional[TransportNetwork],
    ) -> tuple[bool, Optional[str], str]:
        """Evaluate if two alarms should be linked based on temporal, topological, and symptom affinity."""
        # 1. Temporal window validation
        time_diff = abs((a1.first_seen - a2.first_seen).total_seconds())
        if time_diff > self._config.time_window_seconds:
            return False, None, "outside_time_window"

        # 2. Same node alarms within time window always correlate
        if a1.node_id == a2.node_id:
            return True, a1.node_id, "same_node_multi_metric"

        # 3. Check topology presence
        if not topology.has_node(a1.node_id) or not topology.has_node(a2.node_id):
            return False, None, "node_missing_from_topology"

        # 4. Check Lowest Common Ancestor
        lca_id, dist1, dist2 = _find_lca(a1.node_id, a2.node_id, topology)
        if lca_id is None:
            return False, None, "no_common_ancestor"

        max_dist = max(dist1, dist2)
        if max_dist > self._config.max_ancestor_distance:
            return False, None, "exceeds_max_ancestor_distance"

        # 5. Distant ancestor protection: Never merge independent branches solely because of CORE
        lca_node = topology.get_node(lca_id)
        if lca_node.node_type == NodeType.CORE:
            if a1.node_id != lca_id and a2.node_id != lca_id:
                return False, None, "distant_ancestor_core_rejected"

        # 6. Symptom compatibility
        if not _are_symptoms_compatible(a1, a2):
            return False, None, "incompatible_symptoms"

        return True, lca_id, f"common_ancestor_{lca_id}"

    def correlate_alarms(
        self,
        alarms: Sequence[Alarm],
        topology: Optional[Topology] = None,
        transport: Optional[TransportNetwork] = None,
    ) -> CorrelationResult:
        """Correlate a batch of alarms into immutable correlation groups.

        Args:
            alarms: Sequence of Alarm instances to evaluate.
            topology: Optional validated network topology graph (falls back to engine topology).
            transport: Optional transport network parameter (reserved for compatibility;
                       correlation relies on topology hierarchy).

        Returns:
            CorrelationResult containing immutable correlation groups and summary statistics.

        Raises:
            MalformedAlarmError: If any item in alarms is not an Alarm instance.
            TypeError: If topology is missing or invalid.
        """
        if not isinstance(alarms, Sequence):
            raise MalformedAlarmError(f"alarms must be a Sequence, got {type(alarms).__name__}")

        eff_topology = topology if topology is not None else self._topology
        if not isinstance(eff_topology, Topology):
            raise TypeError(f"Expected Topology instance, got {type(eff_topology).__name__}")

        eff_transport = transport if transport is not None else self._transport
        if eff_transport is not None and not isinstance(eff_transport, TransportNetwork):
            raise TypeError(f"Expected TransportNetwork instance, got {type(eff_transport).__name__}")

        if not alarms:
            return CorrelationResult(
                groups=(),
                total_alarms_processed=0,
                total_groups_formed=0,
                singleton_groups_count=0,
                multi_alarm_groups_count=0,
                reduction_ratio=0.0,
            )

        # 1. Deduplicate alarms by unique alarm_id preserving deterministic order
        unique_alarms_map: dict[str, Alarm] = {}
        for a in alarms:
            if not isinstance(a, Alarm):
                raise MalformedAlarmError(f"Expected Alarm instance, got {type(a).__name__}")
            if a.alarm_id not in unique_alarms_map:
                unique_alarms_map[a.alarm_id] = a
        unique_alarms = list(unique_alarms_map.values())

        # Sort unique alarms deterministically: (first_seen, node_id, alarm_id)
        unique_alarms.sort(key=lambda a: (a.first_seen, a.node_id, a.alarm_id))

        n = len(unique_alarms)
        adj: dict[int, list[int]] = {i: [] for i in range(n)}

        # 2. Build pairwise correlation compatibility graph
        for i in range(n):
            for j in range(i + 1, n):
                can_corr, _, _ = self._can_correlate(unique_alarms[i], unique_alarms[j], eff_topology, eff_transport)
                if can_corr:
                    adj[i].append(j)
                    adj[j].append(i)

        # 3. Find connected components subject to maximum group onset span constraint
        # Time-Window Chaining Prevention Policy:
        # Traversal groups compatible alarms into a connected component only as long as adding
        # a new alarm does not cause the group's total onset span (max first_seen - min first_seen)
        # to exceed self._config.time_window_seconds. If an edge would violate the maximum onset
        # window, the candidate node is deferred to a subsequent group, preventing uncontrolled chaining.
        visited: set[int] = set()
        components: list[list[int]] = []

        for i in range(n):
            if i not in visited:
                comp: list[int] = []
                queue: deque[int] = deque([i])
                visited.add(i)
                min_fs = unique_alarms[i].first_seen
                max_fs = unique_alarms[i].first_seen
                while queue:
                    curr = queue.popleft()
                    comp.append(curr)
                    for neighbor in adj[curr]:
                        if neighbor not in visited:
                            n_fs = unique_alarms[neighbor].first_seen
                            cand_min = min(min_fs, n_fs)
                            cand_max = max(max_fs, n_fs)
                            if (cand_max - cand_min).total_seconds() <= self._config.time_window_seconds:
                                visited.add(neighbor)
                                min_fs = cand_min
                                max_fs = cand_max
                                queue.append(neighbor)
                components.append(comp)

        # 4. Form CorrelationGroup instances
        formed_groups: list[CorrelationGroup] = []

        for idx, comp in enumerate(components, start=1):
            comp_alarms = [unique_alarms[i] for i in comp]
            if len(comp_alarms) == 1 and not self._config.group_singletons:
                continue

            # Deterministic sorting within group
            comp_alarms.sort(key=lambda a: (a.first_seen, a.node_id, a.alarm_id))

            distinct_node_ids = tuple(sorted({a.node_id for a in comp_alarms}))
            alarm_ids = tuple(a.alarm_id for a in comp_alarms)

            # Determine anchor node
            anchor_node_id = _find_group_lca(distinct_node_ids, eff_topology)
            anchor_tier: Optional[NodeType] = None
            if anchor_node_id and eff_topology.has_node(anchor_node_id):
                anchor_tier = eff_topology.get_node(anchor_node_id).node_type

            ws = min(a.first_seen for a in comp_alarms)
            we = max(a.last_seen for a in comp_alarms)

            anchor_str = anchor_node_id if anchor_node_id else "UNKNOWN"
            group_id = f"CORR-{anchor_str}-{ws.strftime('%Y%m%d%H%M%S')}-{idx:03d}"

            if len(comp_alarms) == 1:
                reason = f"Isolated alarm on {comp_alarms[0].node_id} ({comp_alarms[0].metric_name})"
            else:
                reason = (
                    f"Correlated {len(comp_alarms)} alarms across {len(distinct_node_ids)} nodes "
                    f"under common dependency '{anchor_str}'"
                )

            evidence = {
                "alarm_count": len(comp_alarms),
                "impacted_nodes": distinct_node_ids,
                "metrics": tuple(sorted({a.metric_name for a in comp_alarms})),
                "anchor_tier": anchor_tier.value if anchor_tier else None,
                "time_span_seconds": round((we - ws).total_seconds(), 2),
            }

            formed_groups.append(
                CorrelationGroup(
                    group_id=group_id,
                    anchor_node_id=anchor_node_id,
                    root_cause_tier=anchor_tier,
                    alarms=tuple(comp_alarms),
                    alarm_ids=alarm_ids,
                    node_ids=distinct_node_ids,
                    time_window_start=ws,
                    time_window_end=we,
                    correlation_reason=reason,
                    evidence=evidence,
                )
            )

        # Sort groups deterministically: (time_window_start, anchor_node_id, group_id)
        formed_groups.sort(key=lambda g: (g.time_window_start, g.anchor_node_id or "", g.group_id))

        total_alarms = len(unique_alarms)
        total_groups = len(formed_groups)
        singletons = sum(1 for g in formed_groups if g.is_singleton)
        multi = total_groups - singletons
        reduction = round((total_alarms - total_groups) / total_alarms, 4) if total_alarms > 0 else 0.0

        return CorrelationResult(
            groups=tuple(formed_groups),
            total_alarms_processed=total_alarms,
            total_groups_formed=total_groups,
            singleton_groups_count=singletons,
            multi_alarm_groups_count=multi,
            reduction_ratio=reduction,
        )

    correlate = correlate_alarms
