"""Explainable diagnostic rules for Root Cause Analysis (RCA)."""

from typing import Any, Mapping, Optional, Sequence

from nexus.correlation.models import CorrelationGroup
from nexus.detection.models import Alarm
from nexus.rca.models import (
    EvidenceItem,
    RootCauseHypothesis,
    RootCauseType,
    TargetType,
)
from nexus.telemetry.models import KPISnapshot
from nexus.topology.enums import NodeType
from nexus.topology.topology import Topology
from nexus.transport.network import TransportNetwork


# Normal baseline reference thresholds for heuristic diagnostic rules
NORMAL_SINR_FLOOR_DB = 10.0  # Normal radio cell SINR is >= 10 dB
MIN_CONGESTION_PRB_PCT = 80.0  # Cell congestion requires PRB utilization >= 80%
SEVERE_AVAILABILITY_CEILING_PCT = 10.0  # Severe outage requires availability <= 10%
BACKHAUL_LATENCY_THRESHOLD_MS = 50.0  # Transport latency degradation threshold
BACKHAUL_THROUGHPUT_CEILING_MBPS = 20.0  # Transport throughput collapse ceiling


def _find_upstream_transport_link(
    node_id: str,
    topology: Topology,
    transport: Optional[TransportNetwork],
) -> Optional[str]:
    """Find the incoming transport link connecting parent to the given node."""
    if transport is None or not topology.has_node(node_id):
        return None
    parent_id = topology.get_node(node_id).parent_id
    if parent_id is None:
        return None
    link = transport.get_link_between(parent_id, node_id)
    return link.link_id if link else None


def evaluate_backhaul_failure(
    group: CorrelationGroup,
    topology: Topology,
    transport: Optional[TransportNetwork],
    snapshot_map: Mapping[str, KPISnapshot],
) -> Optional[RootCauseHypothesis]:
    """Evaluate whether correlation group symptoms match a backhaul/transport failure pattern.

    Diagnostic Signature:
    - Anchor at SITE or AGGREGATION tier, or multiple child cells degraded.
    - Verified transport degradation: elevated latency (> 50 ms), collapsed throughput (< 20 Mbps),
      or severe availability loss (<= 10%). High throughput (e.g. surge) does NOT qualify.
    - Upstream transport link dependency identified.
    - Does NOT award high score merely because anchor is SITE and link exists in topology.
    - Single cell symptom plus link existence does not qualify as strong backhaul failure.
    """
    anchor_id = group.anchor_node_id
    if not anchor_id or not topology.has_node(anchor_id):
        return None

    anchor_node = topology.get_node(anchor_id)
    if anchor_node.node_type not in (NodeType.SITE, NodeType.AGGREGATION, NodeType.CELL):
        return None

    # Collect latency, throughput, and availability alarms meeting degradation criteria
    lat_alarms = [
        a for a in group.alarms
        if a.metric_name == "latency_ms" and a.current_value > BACKHAUL_LATENCY_THRESHOLD_MS
    ]
    tp_alarms = [
        a for a in group.alarms
        if a.metric_name == "throughput_mbps" and a.current_value < BACKHAUL_THROUGHPUT_CEILING_MBPS
    ]
    avail_alarms = [
        a for a in group.alarms
        if a.metric_name == "availability_pct" and a.current_value <= SEVERE_AVAILABILITY_CEILING_PCT
    ]

    # Check snapshots for transport degradation symptoms
    snap_lat_nodes = [
        nid for nid in group.node_ids
        if nid in snapshot_map and snapshot_map[nid].performance.latency_ms > BACKHAUL_LATENCY_THRESHOLD_MS
    ]
    snap_tp_nodes = [
        nid for nid in group.node_ids
        if nid in snapshot_map and snapshot_map[nid].performance.throughput_mbps < BACKHAUL_THROUGHPUT_CEILING_MBPS
    ]
    snap_avail_nodes = [
        nid for nid in group.node_ids
        if nid in snapshot_map and snapshot_map[nid].reliability.availability_pct <= SEVERE_AVAILABILITY_CEILING_PCT
    ]

    has_lat_degradation = bool(lat_alarms or snap_lat_nodes)
    has_tp_degradation = bool(tp_alarms or snap_tp_nodes)
    has_avail_degradation = bool(avail_alarms or snap_avail_nodes)

    # Must have genuine transport degradation symptoms. Presence of an upstream link alone is insufficient.
    if not (has_lat_degradation or has_tp_degradation or has_avail_degradation):
        return None

    score = 0.0
    evidence_items: list[EvidenceItem] = []

    # 1. Base symptom contribution: latency
    if has_lat_degradation:
        score += 0.25
        for a in lat_alarms[:2]:
            evidence_items.append(
                EvidenceItem(
                    source_node_id=a.node_id,
                    metric_name=a.metric_name,
                    observed_value=a.current_value,
                    threshold_or_baseline=a.threshold,
                    reasoning=f"Elevated latency ({a.current_value} ms > {BACKHAUL_LATENCY_THRESHOLD_MS} ms) indicates transport bottleneck",
                    severity=a.severity,
                    evidence_source="ALARM",
                )
            )
        for nid in snap_lat_nodes[:2]:
            if not any(e.source_node_id == nid and e.metric_name == "latency_ms" for e in evidence_items):
                val = snapshot_map[nid].performance.latency_ms
                evidence_items.append(
                    EvidenceItem(
                        source_node_id=nid,
                        metric_name="latency_ms",
                        observed_value=val,
                        threshold_or_baseline=BACKHAUL_LATENCY_THRESHOLD_MS,
                        reasoning=f"Telemetry snapshot confirms elevated latency ({val:.1f} ms > {BACKHAUL_LATENCY_THRESHOLD_MS} ms)",
                        evidence_source="SNAPSHOT",
                    )
                )

    # 2. Base symptom contribution: throughput collapse
    if has_tp_degradation:
        score += 0.20
        for a in tp_alarms[:2]:
            evidence_items.append(
                EvidenceItem(
                    source_node_id=a.node_id,
                    metric_name=a.metric_name,
                    observed_value=a.current_value,
                    threshold_or_baseline=a.threshold,
                    reasoning=f"Collapsed throughput ({a.current_value} Mbps < {BACKHAUL_THROUGHPUT_CEILING_MBPS} Mbps) aligns with backhaul loss",
                    severity=a.severity,
                    evidence_source="ALARM",
                )
            )
        for nid in snap_tp_nodes[:2]:
            if not any(e.source_node_id == nid and e.metric_name == "throughput_mbps" for e in evidence_items):
                val = snapshot_map[nid].performance.throughput_mbps
                evidence_items.append(
                    EvidenceItem(
                        source_node_id=nid,
                        metric_name="throughput_mbps",
                        observed_value=val,
                        threshold_or_baseline=BACKHAUL_THROUGHPUT_CEILING_MBPS,
                        reasoning=f"Telemetry snapshot confirms throughput collapse ({val:.1f} Mbps < {BACKHAUL_THROUGHPUT_CEILING_MBPS} Mbps)",
                        evidence_source="SNAPSHOT",
                    )
                )

    # 3. Base symptom contribution: availability collapse (explicit evidence item and source)
    if has_avail_degradation:
        if not (has_lat_degradation and has_tp_degradation):
            score += 0.20
        for a in avail_alarms[:2]:
            evidence_items.append(
                EvidenceItem(
                    source_node_id=a.node_id,
                    metric_name=a.metric_name,
                    observed_value=a.current_value,
                    threshold_or_baseline=a.threshold,
                    reasoning=f"Severe availability collapse ({a.current_value}% <= {SEVERE_AVAILABILITY_CEILING_PCT}%) from link severance",
                    severity=a.severity,
                    evidence_source="ALARM",
                )
            )
        for nid in snap_avail_nodes[:2]:
            if not any(e.source_node_id == nid and e.metric_name == "availability_pct" for e in evidence_items):
                val = snapshot_map[nid].reliability.availability_pct
                evidence_items.append(
                    EvidenceItem(
                        source_node_id=nid,
                        metric_name="availability_pct",
                        observed_value=val,
                        threshold_or_baseline=SEVERE_AVAILABILITY_CEILING_PCT,
                        reasoning=f"Telemetry snapshot confirms severe availability collapse ({val:.1f}%)",
                        evidence_source="SNAPSHOT",
                    )
                )

    # 4. Multi-node branch impact:
    # A backhaul cut affects multiple downstream nodes under a shared dependency.
    # Must require at least two distinct affected nodes supported by actual qualifying transport symptoms.
    # A SITE or AGGREGATION anchor alone must not award multi-node score.
    branch_node_ids = {anchor_id} | {d.node_id for d in topology.get_descendants(anchor_id)}
    transport_alarm_nodes = {a.node_id for a in lat_alarms} | {a.node_id for a in tp_alarms} | {a.node_id for a in avail_alarms}
    transport_telemetry_nodes = set(snap_lat_nodes) | set(snap_tp_nodes) | set(snap_avail_nodes)
    affected_branch_nodes = (transport_alarm_nodes | transport_telemetry_nodes) & branch_node_ids
    is_multi_node = len(affected_branch_nodes) >= 2

    if is_multi_node:
        score += 0.20
        evidence_items.append(
            EvidenceItem(
                source_node_id=anchor_id,
                metric_name="branch_impact",
                observed_value=float(len(affected_branch_nodes)),
                threshold_or_baseline=2.0,
                reasoning=f"Shared transport branch impact across {len(affected_branch_nodes)} nodes under '{anchor_id}'",
                evidence_source="TOPOLOGY",
            )
        )

    # 5. Transport link identification:
    # Distinguish structural transport-link existence from evidence of link failure.
    # Link existence identifies target entity, but only awards strong support when multi-node branch impact exists.
    upstream_link_id = _find_upstream_transport_link(anchor_id, topology, transport)
    if upstream_link_id:
        target_id = upstream_link_id
        target_type = TargetType.TRANSPORT_LINK
        # Only award significant link score if multi-node impact exists; single-cell receives minimal structural score
        link_score = 0.20 if is_multi_node else 0.05
        score += link_score
        evidence_items.append(
            EvidenceItem(
                source_node_id=anchor_id,
                metric_name="transport_dependency",
                observed_value=1.0,
                threshold_or_baseline=None,
                reasoning=f"Upstream transport link '{upstream_link_id}' serves impacted anchor '{anchor_id}'",
                evidence_source="TOPOLOGY",
            )
        )
    else:
        target_id = anchor_id
        target_type = TargetType.NODE

    # 6. Absence of local radio failure (counter-indicator absent)
    has_rf_alarm = any(a.metric_name in ("sinr_db", "rsrp_dbm") for a in group.alarms)
    if not has_rf_alarm:
        score += 0.05

    if score < 0.35:
        return None

    observed_symptoms: list[str] = []
    if has_lat_degradation:
        observed_symptoms.append("elevated latency")
    if has_tp_degradation:
        observed_symptoms.append("collapsed throughput")
    if has_avail_degradation:
        observed_symptoms.append("availability collapse")
    symptoms_str = " and ".join(observed_symptoms) if observed_symptoms else "transport degradation"

    return RootCauseHypothesis(
        hypothesis_id=f"HYP-BACKHAUL-{target_id}-{group.group_id}",
        cause_type=RootCauseType.BACKHAUL_FAILURE,
        target_id=target_id,
        target_type=target_type,
        confidence_score=min(1.0, score),
        explanation=(
            f"Backhaul transport failure suspected on '{target_id}' affecting "
            f"{len(affected_branch_nodes)} downstream nodes under '{anchor_id}' with observed {symptoms_str}"
        ),
        evidence_items=tuple(evidence_items),
        group_id=group.group_id,
    )


def evaluate_site_power_failure(
    group: CorrelationGroup,
    topology: Topology,
    transport: Optional[TransportNetwork],
    snapshot_map: Mapping[str, KPISnapshot],
) -> Optional[RootCauseHypothesis]:
    """Evaluate whether symptoms match a complete facility power outage at a SITE.

    Diagnostic Signature:
    - Target node is SITE.
    - Multiple descendant cells and/or site show severe availability collapse (<= 10.0%).
    - Mild availability drops (e.g. 85%) do not qualify.
    - Simultaneous blackout across multiple cells in the branch.
    """
    anchor_id = group.anchor_node_id
    if not anchor_id or not topology.has_node(anchor_id):
        return None

    anchor_node = topology.get_node(anchor_id)
    if anchor_node.node_type != NodeType.SITE:
        if anchor_node.node_type == NodeType.CELL:
            parent = topology.get_parent(anchor_id)
            if parent and parent.node_type == NodeType.SITE:
                anchor_id = parent.node_id
                anchor_node = parent
            else:
                return None
        else:
            return None

    avail_alarms = [a for a in group.alarms if a.metric_name == "availability_pct"]

    children = topology.get_children(anchor_id)
    child_ids = {c.node_id for c in children}
    impacted_children = set(group.node_ids) & child_ids

    snap_avail_children = [
        cid for cid in child_ids
        if cid in snapshot_map and snapshot_map[cid].reliability.availability_pct <= SEVERE_AVAILABILITY_CEILING_PCT
    ]

    all_avail_values = [a.current_value for a in avail_alarms]
    for cid in child_ids:
        if cid in snapshot_map:
            all_avail_values.append(snapshot_map[cid].reliability.availability_pct)

    if not all_avail_values:
        return None

    # Require severe availability collapse (<= 10%). Mild drops do NOT qualify.
    severe_avail_values = [v for v in all_avail_values if v <= SEVERE_AVAILABILITY_CEILING_PCT]
    if not severe_avail_values:
        return None

    # Must affect multiple child cells (or all child cells if <= 1 child exists)
    severe_child_count = len(
        {a.node_id for a in avail_alarms if a.current_value <= SEVERE_AVAILABILITY_CEILING_PCT and a.node_id in child_ids}
        | set(snap_avail_children)
    )
    if len(children) >= 2 and severe_child_count < 2:
        return None

    score = 0.0
    evidence_items: list[EvidenceItem] = []

    # 1. Base availability collapse score: +0.35
    score += 0.35
    for a in avail_alarms:
        if a.current_value <= SEVERE_AVAILABILITY_CEILING_PCT:
            evidence_items.append(
                EvidenceItem(
                    source_node_id=a.node_id,
                    metric_name=a.metric_name,
                    observed_value=a.current_value,
                    threshold_or_baseline=a.threshold,
                    reasoning=f"Critical availability collapse ({a.current_value}% <= {SEVERE_AVAILABILITY_CEILING_PCT}%) on {a.node_id}",
                    severity=a.severity,
                    evidence_source="ALARM",
                )
            )

    for cid in snap_avail_children:
        if not any(e.source_node_id == cid and e.metric_name == "availability_pct" for e in evidence_items):
            val = snapshot_map[cid].reliability.availability_pct
            evidence_items.append(
                EvidenceItem(
                    source_node_id=cid,
                    metric_name="availability_pct",
                    observed_value=val,
                    threshold_or_baseline=SEVERE_AVAILABILITY_CEILING_PCT,
                    reasoning=f"Telemetry snapshot confirms severe availability collapse ({val:.1f}%) on child cell",
                    evidence_source="SNAPSHOT",
                )
            )

    # 2. Complete blackout check (value == 0.0)
    has_zero_alarm = any(a.current_value == 0.0 for a in avail_alarms)
    has_zero_snap = any(cid in snapshot_map and snapshot_map[cid].reliability.availability_pct == 0.0 for cid in child_ids)
    if has_zero_alarm or has_zero_snap:
        score += 0.25

    # 3. Branch coverage: multiple child cells affected under this site
    total_impacted = len(impacted_children | set(snap_avail_children))
    if total_impacted >= 2 or (children and total_impacted == len(children)):
        score += 0.30
        evidence_items.append(
            EvidenceItem(
                source_node_id=anchor_id,
                metric_name="branch_blackout_coverage",
                observed_value=float(total_impacted),
                threshold_or_baseline=float(len(children)),
                reasoning=f"Multiple subordinate cells ({total_impacted}/{len(children)}) experienced simultaneous outage",
                evidence_source="TOPOLOGY",
            )
        )

    if score < 0.35:
        return None

    return RootCauseHypothesis(
        hypothesis_id=f"HYP-POWER-{anchor_id}-{group.group_id}",
        cause_type=RootCauseType.SITE_POWER_FAILURE,
        target_id=anchor_id,
        target_type=TargetType.NODE,
        confidence_score=min(1.0, score),
        explanation=(
            f"Site power failure diagnosed at '{anchor_id}': facility blackout causing complete "
            f"loss of availability across subordinate cell sectors"
        ),
        evidence_items=tuple(evidence_items),
        group_id=group.group_id,
    )


def evaluate_radio_interference(
    group: CorrelationGroup,
    topology: Topology,
    transport: Optional[TransportNetwork],
    snapshot_map: Mapping[str, KPISnapshot],
) -> Optional[RootCauseHypothesis]:
    """Evaluate whether symptoms indicate external RF interference on a cell.

    Diagnostic Signature:
    - Localized to a single CELL.
    - Requires observed, meaningful SINR degradation (alarm on sinr_db with value < 10 dB, or snapshot sinr_db < 10 dB).
    - A sinr_db alarm with a normal value (>= 10 dB) does NOT prove interference.
    - RSRP degradation alone does NOT prove interference.
    - Inspects available snapshot availability and PRB metrics for contradictory outage or congestion evidence.
    - Does NOT award counter-indicator points merely because an alarm is absent if telemetry contradicts.
    - Missing metrics remain unverified rather than being treated as healthy.
    - Sibling cell health verified via telemetry or marked unverified.
    """
    sinr_alarms = [a for a in group.alarms if a.metric_name == "sinr_db"]
    rsrp_alarms = [a for a in group.alarms if a.metric_name == "rsrp_dbm"]

    target_cell_id: Optional[str] = None
    if sinr_alarms:
        target_cell_id = sinr_alarms[0].node_id
    elif rsrp_alarms:
        target_cell_id = rsrp_alarms[0].node_id
    elif group.anchor_node_id and topology.has_node(group.anchor_node_id):
        if topology.get_node(group.anchor_node_id).node_type == NodeType.CELL:
            target_cell_id = group.anchor_node_id

    if not target_cell_id or not topology.has_node(target_cell_id):
        return None

    target_node = topology.get_node(target_cell_id)
    if target_node.node_type != NodeType.CELL:
        return None

    # Check whether SINR degradation is genuinely observed:
    # 1. An alarm explicitly on sinr_db with current_value below NORMAL_SINR_FLOOR_DB (10 dB)
    degraded_sinr_alarms = [
        a for a in sinr_alarms
        if a.node_id == target_cell_id and a.current_value < NORMAL_SINR_FLOOR_DB
    ]
    # 2. Or snapshot telemetry showing degraded SINR (< 10.0 dB)
    snap_sinr_val: Optional[float] = None
    snap_sinr_degraded = False
    if target_cell_id in snapshot_map and snapshot_map[target_cell_id].radio is not None:
        snap_sinr_val = snapshot_map[target_cell_id].radio.sinr_db
        if snap_sinr_val < NORMAL_SINR_FLOOR_DB:
            snap_sinr_degraded = True

    # Reject if no meaningful SINR degradation is observed (normal-valued SINR alarms and RSRP alone rejected)
    if not (degraded_sinr_alarms or snap_sinr_degraded):
        return None

    # Inspect contradictory evidence in alarms and snapshots:
    # Outage contradiction: availability collapse
    has_avail_alarm = any(
        a.node_id == target_cell_id and a.metric_name == "availability_pct" and a.current_value <= SEVERE_AVAILABILITY_CEILING_PCT
        for a in group.alarms
    )
    snap_avail_collapse = (
        target_cell_id in snapshot_map
        and snapshot_map[target_cell_id].reliability.availability_pct <= SEVERE_AVAILABILITY_CEILING_PCT
    )
    if has_avail_alarm or snap_avail_collapse:
        # Severe facility/hardware outage contradicts external RF interference
        return None

    # Congestion contradiction: high PRB utilization
    has_prb_alarm = any(
        a.node_id == target_cell_id and a.metric_name == "prb_utilization_pct" and a.current_value >= MIN_CONGESTION_PRB_PCT
        for a in group.alarms
    )
    snap_prb_high = (
        target_cell_id in snapshot_map
        and snapshot_map[target_cell_id].radio is not None
        and snapshot_map[target_cell_id].radio.prb_utilization_pct >= MIN_CONGESTION_PRB_PCT
    )

    score = 0.0
    evidence_items: list[EvidenceItem] = []

    # 1. Base RF degradation score: +0.40
    score += 0.40
    for a in degraded_sinr_alarms:
        evidence_items.append(
            EvidenceItem(
                source_node_id=a.node_id,
                metric_name=a.metric_name,
                observed_value=a.current_value,
                threshold_or_baseline=a.threshold,
                reasoning=f"Degraded SINR ({a.current_value} dB < {NORMAL_SINR_FLOOR_DB} dB) indicating interference",
                severity=a.severity,
                evidence_source="ALARM",
            )
        )

    if snap_sinr_degraded and snap_sinr_val is not None:
        evidence_items.append(
            EvidenceItem(
                source_node_id=target_cell_id,
                metric_name="sinr_db",
                observed_value=snap_sinr_val,
                threshold_or_baseline=NORMAL_SINR_FLOOR_DB,
                reasoning=f"Telemetry snapshot confirms degraded SINR ({snap_sinr_val:.1f} dB < {NORMAL_SINR_FLOOR_DB} dB)",
                evidence_source="SNAPSHOT",
            )
        )

    # 2. Localization & Sibling health verification
    parent = topology.get_parent(target_cell_id)
    if parent:
        siblings = [c for c in topology.get_children(parent.node_id) if c.node_id != target_cell_id]
        sibling_ids = {s.node_id for s in siblings}
        if sibling_ids & set(group.node_ids):
            # Contradicts localized RF interference
            return None

        # Check telemetry for sibling cells
        sibling_snaps = [
            snapshot_map[sid] for sid in sibling_ids
            if sid in snapshot_map and snapshot_map[sid].radio is not None
        ]
        if sibling_snaps:
            if all(s.radio.sinr_db >= NORMAL_SINR_FLOOR_DB for s in sibling_snaps):
                score += 0.25
                evidence_items.append(
                    EvidenceItem(
                        source_node_id=target_cell_id,
                        metric_name="spatial_isolation",
                        observed_value=1.0,
                        threshold_or_baseline=NORMAL_SINR_FLOOR_DB,
                        reasoning=f"Sibling cell telemetry confirms healthy SINR (>= {NORMAL_SINR_FLOOR_DB} dB) on '{parent.node_id}', isolating interference to '{target_cell_id}'",
                        evidence_source="SNAPSHOT",
                    )
                )
            else:
                pass
        else:
            # Telemetry absent: missing metrics remain unverified
            score += 0.05
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="spatial_isolation",
                    observed_value=1.0,
                    threshold_or_baseline=None,
                    reasoning="No sibling alarms in group, but sibling telemetry is unverified",
                    evidence_source="ALARM",
                )
            )

    # 3. Counter-indicators: Availability and PRB
    # Only award verified points if telemetry confirms healthy condition; missing metrics remain unverified
    if target_cell_id in snapshot_map:
        snap_avail = snapshot_map[target_cell_id].reliability.availability_pct
        if snap_avail >= 90.0:
            score += 0.15
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="availability_pct",
                    observed_value=snap_avail,
                    threshold_or_baseline=90.0,
                    reasoning=f"Telemetry snapshot confirms operational availability ({snap_avail:.1f}%), ruling out outage",
                    evidence_source="SNAPSHOT",
                )
            )
        if snapshot_map[target_cell_id].radio is not None:
            snap_prb = snapshot_map[target_cell_id].radio.prb_utilization_pct
            if snap_prb < MIN_CONGESTION_PRB_PCT:
                score += 0.15
                evidence_items.append(
                    EvidenceItem(
                        source_node_id=target_cell_id,
                        metric_name="prb_utilization_pct",
                        observed_value=snap_prb,
                        threshold_or_baseline=MIN_CONGESTION_PRB_PCT,
                        reasoning=f"Telemetry snapshot confirms normal PRB utilization ({snap_prb:.1f}% < {MIN_CONGESTION_PRB_PCT}%), ruling out congestion",
                        evidence_source="SNAPSHOT",
                    )
                )
    else:
        # Telemetry absent: missing metrics remain unverified rather than treated as healthy
        if not has_avail_alarm:
            score += 0.05
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="availability_health",
                    observed_value=1.0,
                    threshold_or_baseline=None,
                    reasoning="No availability alarm in group, but availability telemetry is unverified",
                    evidence_source="ALARM",
                )
            )
        if not (has_prb_alarm or snap_prb_high):
            score += 0.05
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="prb_health",
                    observed_value=1.0,
                    threshold_or_baseline=None,
                    reasoning="No PRB alarm in group, but PRB telemetry is unverified",
                    evidence_source="ALARM",
                )
            )

    if score < 0.35:
        return None

    observed_eff_sinr = snap_sinr_val if snap_sinr_val is not None else degraded_sinr_alarms[0].current_value
    explanation = (
        f"External radio frequency interference diagnosed on sector '{target_cell_id}': "
        f"degraded SINR ({observed_eff_sinr:.1f} dB < {NORMAL_SINR_FLOOR_DB} dB)"
    )
    if target_cell_id in snapshot_map and snapshot_map[target_cell_id].reliability.availability_pct >= 90.0:
        explanation += " without facility outage"
    if target_cell_id in snapshot_map and snapshot_map[target_cell_id].radio and snapshot_map[target_cell_id].radio.prb_utilization_pct < MIN_CONGESTION_PRB_PCT:
        explanation += " or resource congestion"

    return RootCauseHypothesis(
        hypothesis_id=f"HYP-RF-INTERFERENCE-{target_cell_id}-{group.group_id}",
        cause_type=RootCauseType.RADIO_INTERFERENCE,
        target_id=target_cell_id,
        target_type=TargetType.NODE,
        confidence_score=min(1.0, score),
        explanation=explanation,
        evidence_items=tuple(evidence_items),
        group_id=group.group_id,
    )


def evaluate_cell_congestion(
    group: CorrelationGroup,
    topology: Topology,
    transport: Optional[TransportNetwork],
    snapshot_map: Mapping[str, KPISnapshot],
) -> Optional[RootCauseHypothesis]:
    """Evaluate whether symptoms indicate resource saturation / scheduling congestion.

    Diagnostic Signature:
    - High PRB utilization (>= 80.0%). Mild PRB utilization does NOT qualify.
    - Requires at least one independently observed performance degradation:
      - latency_ms > 30 ms, or
      - throughput_mbps < 50 Mbps.
    - If high PRB exists but performance is normal or unobserved, returns None.
    - Radio signal quality (SINR) verified healthy (>= 10.0 dB) via telemetry or marked unverified.
    """
    prb_alarms = [a for a in group.alarms if a.metric_name == "prb_utilization_pct"]

    target_cell_id: Optional[str] = None
    if prb_alarms:
        target_cell_id = prb_alarms[0].node_id
    else:
        for nid in group.node_ids:
            if nid in snapshot_map and snapshot_map[nid].radio and snapshot_map[nid].radio.prb_utilization_pct >= MIN_CONGESTION_PRB_PCT:
                target_cell_id = nid
                break

    if not target_cell_id or not topology.has_node(target_cell_id):
        return None

    target_node = topology.get_node(target_cell_id)
    if target_node.node_type != NodeType.CELL:
        return None

    # Check observed PRB utilization: must be >= 80.0%
    observed_prb_values: list[float] = [a.current_value for a in prb_alarms if a.node_id == target_cell_id]
    if target_cell_id in snapshot_map and snapshot_map[target_cell_id].radio is not None:
        observed_prb_values.append(snapshot_map[target_cell_id].radio.prb_utilization_pct)

    if not observed_prb_values or max(observed_prb_values) < MIN_CONGESTION_PRB_PCT:
        return None

    # Require at least one independently observed performance degradation:
    # latency_ms > 30 ms or throughput_mbps < 50 Mbps
    lat_degraded_alarms = [
        a for a in group.alarms
        if a.node_id == target_cell_id and a.metric_name == "latency_ms" and a.current_value > 30.0
    ]
    tp_degraded_alarms = [
        a for a in group.alarms
        if a.node_id == target_cell_id and a.metric_name == "throughput_mbps" and a.current_value < 50.0
    ]

    snap_lat_val: Optional[float] = None
    snap_tp_val: Optional[float] = None
    if target_cell_id in snapshot_map:
        perf = snapshot_map[target_cell_id].performance
        if perf.latency_ms > 30.0:
            snap_lat_val = perf.latency_ms
        if perf.throughput_mbps < 50.0:
            snap_tp_val = perf.throughput_mbps

    has_perf_degradation = bool(lat_degraded_alarms or tp_degraded_alarms or (snap_lat_val is not None) or (snap_tp_val is not None))
    # If high PRB exists but performance is normal or unobserved, do not return a CELL_CONGESTION hypothesis
    if not has_perf_degradation:
        return None

    score = 0.0
    evidence_items: list[EvidenceItem] = []

    # 1. Base PRB utilization score: +0.40
    score += 0.40
    for a in prb_alarms:
        if a.node_id == target_cell_id and a.current_value >= MIN_CONGESTION_PRB_PCT:
            evidence_items.append(
                EvidenceItem(
                    source_node_id=a.node_id,
                    metric_name=a.metric_name,
                    observed_value=a.current_value,
                    threshold_or_baseline=a.threshold,
                    reasoning=f"High physical resource block utilization ({a.current_value}% >= {MIN_CONGESTION_PRB_PCT}%) indicates saturation",
                    severity=a.severity,
                    evidence_source="ALARM",
                )
            )

    if target_cell_id in snapshot_map and snapshot_map[target_cell_id].radio is not None:
        snap_prb = snapshot_map[target_cell_id].radio.prb_utilization_pct
        if snap_prb >= MIN_CONGESTION_PRB_PCT:
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="prb_utilization_pct",
                    observed_value=snap_prb,
                    threshold_or_baseline=MIN_CONGESTION_PRB_PCT,
                    reasoning=f"Telemetry snapshot confirms high PRB utilization ({snap_prb:.1f}% >= {MIN_CONGESTION_PRB_PCT}%)",
                    evidence_source="SNAPSHOT",
                )
            )

    # 2. Performance impact evidence: +0.25
    score += 0.25
    for a in lat_degraded_alarms:
        evidence_items.append(
            EvidenceItem(
                source_node_id=a.node_id,
                metric_name=a.metric_name,
                observed_value=a.current_value,
                threshold_or_baseline=a.threshold,
                reasoning=f"Queuing delay ({a.current_value} ms > 30 ms) co-occurring with resource saturation",
                severity=a.severity,
                evidence_source="ALARM",
            )
        )
    for a in tp_degraded_alarms:
        evidence_items.append(
            EvidenceItem(
                source_node_id=a.node_id,
                metric_name=a.metric_name,
                observed_value=a.current_value,
                threshold_or_baseline=a.threshold,
                reasoning=f"Reduced throughput ({a.current_value} Mbps < 50 Mbps) co-occurring with resource saturation",
                severity=a.severity,
                evidence_source="ALARM",
            )
        )
    if snap_lat_val is not None and not lat_degraded_alarms:
        evidence_items.append(
            EvidenceItem(
                source_node_id=target_cell_id,
                metric_name="latency_ms",
                observed_value=snap_lat_val,
                threshold_or_baseline=30.0,
                reasoning=f"Telemetry snapshot confirms elevated latency ({snap_lat_val:.1f} ms > 30 ms)",
                evidence_source="SNAPSHOT",
            )
        )
    if snap_tp_val is not None and not tp_degraded_alarms:
        evidence_items.append(
            EvidenceItem(
                source_node_id=target_cell_id,
                metric_name="throughput_mbps",
                observed_value=snap_tp_val,
                threshold_or_baseline=50.0,
                reasoning=f"Telemetry snapshot confirms reduced throughput ({snap_tp_val:.1f} Mbps < 50 Mbps)",
                evidence_source="SNAPSHOT",
            )
        )

    # 3. Radio RF health verification:
    # Verify that radio RF is healthy before claiming it (via snapshot: sinr_db >= 10.0 dB)
    if target_cell_id in snapshot_map and snapshot_map[target_cell_id].radio is not None:
        sinr = snapshot_map[target_cell_id].radio.sinr_db
        if sinr >= NORMAL_SINR_FLOOR_DB:
            score += 0.20
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="sinr_db",
                    observed_value=sinr,
                    threshold_or_baseline=NORMAL_SINR_FLOOR_DB,
                    reasoning=f"Telemetry confirms clean radio environment (SINR {sinr:.1f} dB >= {NORMAL_SINR_FLOOR_DB} dB), ruling out RF interference",
                    evidence_source="SNAPSHOT",
                )
            )
    else:
        has_rf_alarm = any(a.node_id == target_cell_id and a.metric_name == "sinr_db" for a in group.alarms)
        if not has_rf_alarm:
            score += 0.05
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="radio_signal_health",
                    observed_value=1.0,
                    threshold_or_baseline=None,
                    reasoning="No radio alarms present, but radio telemetry is unverified",
                    evidence_source="ALARM",
                )
            )

    if score < 0.35:
        return None

    max_prb = max(observed_prb_values)
    return RootCauseHypothesis(
        hypothesis_id=f"HYP-CONGESTION-{target_cell_id}-{group.group_id}",
        cause_type=RootCauseType.CELL_CONGESTION,
        target_id=target_cell_id,
        target_type=TargetType.NODE,
        confidence_score=min(1.0, score),
        explanation=(
            f"Cell resource congestion diagnosed on '{target_cell_id}': "
            f"high PRB utilization ({max_prb:.1f}% >= {MIN_CONGESTION_PRB_PCT}%) with observed performance degradation"
        ),
        evidence_items=tuple(evidence_items),
        group_id=group.group_id,
    )


def evaluate_cell_outage(
    group: CorrelationGroup,
    topology: Topology,
    transport: Optional[TransportNetwork],
    snapshot_map: Mapping[str, KPISnapshot],
) -> Optional[RootCauseHypothesis]:
    """Evaluate whether symptoms indicate an isolated single-cell outage.

    Diagnostic Signature:
    - Availability collapse (<= 10.0%) and/or near-zero throughput (< 1.0 Mbps) on a single cell.
    - Availability collapse and throughput collapse are treated as separate evidence paths.
    - Mild availability drops (> 10.0%) and normal throughput (>= 1.0 Mbps) do NOT qualify.
    - Sibling cells on the same site verified healthy via telemetry or marked unverified.
    """
    # 1. Identify candidate target cell node
    target_cell_id: Optional[str] = None

    # Check alarms for cell nodes with severe availability or near-zero throughput
    for a in group.alarms:
        if topology.has_node(a.node_id) and topology.get_node(a.node_id).node_type == NodeType.CELL:
            if (a.metric_name == "availability_pct" and a.current_value <= SEVERE_AVAILABILITY_CEILING_PCT) or \
               (a.metric_name == "throughput_mbps" and a.current_value < 1.0):
                target_cell_id = a.node_id
                break

    # If no qualifying alarm, check any alarm on cell nodes in the group
    if not target_cell_id:
        for a in group.alarms:
            if topology.has_node(a.node_id) and topology.get_node(a.node_id).node_type == NodeType.CELL:
                target_cell_id = a.node_id
                break

    # If still not found, check group node_ids / snapshots for qualifying cell conditions
    if not target_cell_id:
        for nid in group.node_ids:
            if topology.has_node(nid) and topology.get_node(nid).node_type == NodeType.CELL:
                if nid in snapshot_map and (
                    snapshot_map[nid].reliability.availability_pct <= SEVERE_AVAILABILITY_CEILING_PCT or
                    snapshot_map[nid].performance.throughput_mbps < 1.0
                ):
                    target_cell_id = nid
                    break

    # If still not found, check if anchor is a CELL
    if not target_cell_id and group.anchor_node_id and topology.has_node(group.anchor_node_id):
        if topology.get_node(group.anchor_node_id).node_type == NodeType.CELL:
            target_cell_id = group.anchor_node_id

    if not target_cell_id or not topology.has_node(target_cell_id):
        return None

    target_node = topology.get_node(target_cell_id)
    if target_node.node_type != NodeType.CELL:
        return None

    # Separate Evidence Path 1: Severe Availability Collapse (<= 10.0%)
    avail_alarms = [
        a for a in group.alarms
        if a.node_id == target_cell_id
        and a.metric_name == "availability_pct"
        and a.current_value <= SEVERE_AVAILABILITY_CEILING_PCT
    ]
    snap_avail_val: Optional[float] = None
    if target_cell_id in snapshot_map:
        val = snapshot_map[target_cell_id].reliability.availability_pct
        if val <= SEVERE_AVAILABILITY_CEILING_PCT:
            snap_avail_val = val

    has_avail_collapse = bool(avail_alarms or snap_avail_val is not None)

    # Separate Evidence Path 2: Near-zero Throughput Collapse (< 1.0 Mbps)
    tp_alarms = [
        a for a in group.alarms
        if a.node_id == target_cell_id
        and a.metric_name == "throughput_mbps"
        and a.current_value < 1.0
    ]
    snap_tp_val: Optional[float] = None
    if target_cell_id in snapshot_map:
        val = snapshot_map[target_cell_id].performance.throughput_mbps
        if val < 1.0:
            snap_tp_val = val

    has_tp_collapse = bool(tp_alarms or snap_tp_val is not None)

    if not (has_avail_collapse or has_tp_collapse):
        return None

    score = 0.0
    evidence_items: list[EvidenceItem] = []

    # 1. Base symptom contribution: availability collapse (only when availability condition met)
    if has_avail_collapse:
        score += 0.40
        for a in avail_alarms[:2]:
            evidence_items.append(
                EvidenceItem(
                    source_node_id=a.node_id,
                    metric_name=a.metric_name,
                    observed_value=a.current_value,
                    threshold_or_baseline=a.threshold,
                    reasoning=f"Radio cell availability collapse ({a.current_value}% <= {SEVERE_AVAILABILITY_CEILING_PCT}%)",
                    severity=a.severity,
                    evidence_source="ALARM",
                )
            )
        if snap_avail_val is not None:
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="availability_pct",
                    observed_value=snap_avail_val,
                    threshold_or_baseline=SEVERE_AVAILABILITY_CEILING_PCT,
                    reasoning=f"Telemetry snapshot confirms severe cell availability collapse ({snap_avail_val:.1f}%)",
                    evidence_source="SNAPSHOT",
                )
            )

    # 2. Base symptom contribution: throughput collapse (only when throughput condition met)
    # Does not award availability points for throughput-only evidence
    if has_tp_collapse:
        score += 0.20 if has_avail_collapse else 0.35
        for a in tp_alarms[:2]:
            evidence_items.append(
                EvidenceItem(
                    source_node_id=a.node_id,
                    metric_name=a.metric_name,
                    observed_value=a.current_value,
                    threshold_or_baseline=1.0,
                    reasoning=f"Radio cell throughput collapse ({a.current_value} Mbps < 1.0 Mbps)",
                    severity=a.severity,
                    evidence_source="ALARM",
                )
            )
        if snap_tp_val is not None:
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="throughput_mbps",
                    observed_value=snap_tp_val,
                    threshold_or_baseline=1.0,
                    reasoning=f"Telemetry snapshot confirms near-zero throughput ({snap_tp_val:.2f} Mbps < 1.0 Mbps)",
                    evidence_source="SNAPSHOT",
                )
            )

    # 3. Sibling health check and complete isolation coverage handling
    parent = topology.get_parent(target_cell_id)
    site_id = parent.node_id if parent else None

    # Check site-level telemetry and alarms to assess host site health
    # Do not infer site health from the target cell's own telemetry
    site_status = "unverified"
    if site_id:
        has_site_outage_alarm = any(
            a.node_id == site_id and a.metric_name == "availability_pct" and a.current_value <= SEVERE_AVAILABILITY_CEILING_PCT
            for a in group.alarms
        )
        site_snap = snapshot_map.get(site_id)
        if has_site_outage_alarm or (site_snap and site_snap.reliability.availability_pct <= SEVERE_AVAILABILITY_CEILING_PCT):
            site_status = "wider_outage"
        elif site_snap and site_snap.reliability.availability_pct >= 90.0:
            site_status = "operational"

    unhealthy_sibling_count = 0
    if parent:
        siblings = [c for c in topology.get_children(parent.node_id) if c.node_id != target_cell_id]
        sibling_ids = {s.node_id for s in siblings}
        expected_sibling_count = len(siblings)

        if sibling_ids & set(group.node_ids):
            # Multiple cells down under same site is site-wide outage, not isolated cell outage
            return None

        # Check sibling snapshots
        observed_sibling_snaps = {sid: snapshot_map[sid] for sid in sibling_ids if sid in snapshot_map}
        observed_sibling_count = len(observed_sibling_snaps)
        healthy_sibling_count = sum(1 for s in observed_sibling_snaps.values() if s.reliability.availability_pct >= 90.0)
        unhealthy_sibling_count = observed_sibling_count - healthy_sibling_count

        if unhealthy_sibling_count > 0:
            # Any observed sibling unhealthy: do not claim the cell is isolated
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="sibling_health_isolation",
                    observed_value=float(healthy_sibling_count),
                    threshold_or_baseline=float(expected_sibling_count),
                    reasoning=(
                        f"Sibling cell degradation observed ({unhealthy_sibling_count}/{observed_sibling_count} observed degraded, "
                        f"{expected_sibling_count} expected) under '{site_id}', contradicting cell isolation"
                    ),
                    evidence_source="SNAPSHOT",
                )
            )
        elif observed_sibling_count == expected_sibling_count and expected_sibling_count > 0:
            # All siblings observed and healthy: full verification score and evidence
            score += 0.25
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="sibling_health_isolation",
                    observed_value=float(expected_sibling_count),
                    threshold_or_baseline=float(expected_sibling_count),
                    reasoning=(
                        f"All sibling cell telemetry ({observed_sibling_count}/{expected_sibling_count} observed) "
                        f"confirms normal availability (>= 90%) under '{site_id}', confirming cell isolation"
                    ),
                    evidence_source="SNAPSHOT",
                )
            )
        elif 0 < observed_sibling_count < expected_sibling_count:
            # Some siblings observed healthy, others missing: partial/unverified score with explicit coverage details
            score += 0.10
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="sibling_health_isolation",
                    observed_value=float(observed_sibling_count),
                    threshold_or_baseline=float(expected_sibling_count),
                    reasoning=(
                        f"Partial sibling telemetry ({observed_sibling_count}/{expected_sibling_count} observed) "
                        f"indicates normal availability, but {expected_sibling_count - observed_sibling_count} sibling(s) are unverified under '{site_id}'"
                    ),
                    evidence_source="SNAPSHOT",
                )
            )
        else:
            # No sibling telemetry: retain the existing unverified behavior
            score += 0.05
            evidence_items.append(
                EvidenceItem(
                    source_node_id=target_cell_id,
                    metric_name="sibling_health_isolation",
                    observed_value=0.0,
                    threshold_or_baseline=float(expected_sibling_count),
                    reasoning=f"No sibling alarms in group, but sibling telemetry is unverified (0/{expected_sibling_count} observed)",
                    evidence_source="ALARM",
                )
            )

    # 4. Non-systemic: Only one cell impacted in group
    if len(group.node_ids) == 1 and unhealthy_sibling_count == 0:
        score += 0.15

    if score < 0.35:
        return None

    observed_conditions: list[str] = []
    if has_avail_collapse:
        observed_conditions.append("severe availability collapse")
    if has_tp_collapse:
        observed_conditions.append("near-zero throughput collapse")
    conditions_str = " and ".join(observed_conditions)

    if site_status == "operational":
        site_desc = f"while host site '{site_id}' appears operational"
        prefix = f"Isolated cell sector outage on '{target_cell_id}'"
    elif site_status == "wider_outage":
        site_desc = f"while evidence indicates wider outage on host site '{site_id}'"
        prefix = f"Cell sector outage on '{target_cell_id}' with potential wider site outage"
    else:
        site_desc = "while wider site status is unverified"
        prefix = f"Cell sector outage on '{target_cell_id}'"

    if unhealthy_sibling_count > 0:
        prefix = f"Cell sector outage on '{target_cell_id}'"
        explanation = (
            f"{prefix}: observed {conditions_str} on cell; "
            f"sibling degradation was observed and impact may extend beyond target cell, {site_desc}"
        )
    elif site_status == "wider_outage":
        explanation = f"{prefix}: observed {conditions_str} on cell {site_desc}"
    elif site_status == "operational" and observed_sibling_count == expected_sibling_count:
        explanation = f"{prefix}: observed {conditions_str} localized to single cell {site_desc}"
    else:
        explanation = f"{prefix}: observed {conditions_str} localized to single cell {site_desc}"

    return RootCauseHypothesis(
        hypothesis_id=f"HYP-OUTAGE-{target_cell_id}-{group.group_id}",
        cause_type=RootCauseType.CELL_OUTAGE,
        target_id=target_cell_id,
        target_type=TargetType.NODE,
        confidence_score=min(1.0, score),
        explanation=explanation,
        evidence_items=tuple(evidence_items),
        group_id=group.group_id,
    )
