"""Root Cause Analysis (RCA) Engine coordinator."""

from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional, Sequence

from nexus.correlation.models import CorrelationGroup, CorrelationResult
from nexus.rca.exceptions import (
    InsufficientTelemetryError,
    InvalidRCAConfigError,
    RCAError,
)
from nexus.rca.models import (
    EvidenceItem,
    RCAConfig,
    RCAResult,
    RootCauseHypothesis,
    RootCauseType,
    TargetType,
)
from nexus.rca.rules import (
    evaluate_backhaul_failure,
    evaluate_cell_congestion,
    evaluate_cell_outage,
    evaluate_radio_interference,
    evaluate_site_power_failure,
)
from nexus.telemetry.models import KPISnapshot
from nexus.topology.topology import Topology
from nexus.transport.network import TransportNetwork


RECOMMENDED_ACTIONS = {
    RootCauseType.BACKHAUL_FAILURE: "Inspect physical transport link and verify optical transceivers / fiber continuity.",
    RootCauseType.SITE_POWER_FAILURE: "Verify facility grid power supply, backup battery voltage, and generator transfer switch.",
    RootCauseType.RADIO_INTERFERENCE: "Initiate spectrum analysis sweep to identify and locate external RF interference sources.",
    RootCauseType.CELL_CONGESTION: "Activate carrier aggregation and dynamic traffic offload to mitigate PRB saturation.",
    RootCauseType.CELL_OUTAGE: "Power-cycle radio unit / baseband module and verify antenna feeder connections.",
    RootCauseType.UNKNOWN: "Gather detailed diagnostic traces and assign to Tier-2 operations for triage.",
}


def _select_relevant_snapshots(
    snapshots: Sequence[KPISnapshot],
    group: CorrelationGroup,
    max_staleness_seconds: float,
    analysis_timestamp: datetime,
) -> dict[str, KPISnapshot]:
    """Deterministically select the latest fresh, past/present snapshot for each node.

    Freshness Reference & Selection Policy:
    1. Reference Timestamp: All telemetry freshness is evaluated strictly relative to
       analysis_timestamp.
    2. Strict Past/Present Constraint (No Future Look-Ahead): Historical replay and
       online triage must never benefit from unobservable future information. Any snapshot
       with timestamp > analysis_timestamp is strictly discarded.
    3. Maximum Staleness Floor: A snapshot is fresh if and only if its timestamp satisfies:
       analysis_timestamp - max_staleness_seconds <= snapshot.timestamp <= analysis_timestamp.
       Snapshots older than this window are discarded as stale. If the latest past observation
       for a node is stale, it is discarded even if older observations exist.
    4. Deterministic Selection: For each node with one or more eligible fresh snapshots, the
       observation with the latest timestamp (closest to analysis_timestamp) is selected.
    5. Discard When Absent: If all observations for a node are in the future or stale, no
       snapshot is selected for that node (omitted from the returned mapping).
    """
    max_stale_delta = timedelta(seconds=max(0.0, float(max_staleness_seconds)))
    earliest_fresh_ts = analysis_timestamp - max_stale_delta

    by_node: dict[str, list[KPISnapshot]] = {}
    for s in snapshots:
        # Strictly past or present, and within configured maximum staleness
        if earliest_fresh_ts <= s.timestamp <= analysis_timestamp:
            by_node.setdefault(s.node_id, []).append(s)

    selected: dict[str, KPISnapshot] = {}
    for node_id, node_snaps in sorted(by_node.items()):
        # Select latest valid observation at or before analysis_timestamp
        best = max(node_snaps, key=lambda s: s.timestamp)
        selected[node_id] = best

    return selected


class RootCauseAnalysisEngine:
    """Evaluates correlation groups against explainable diagnostic rules to determine root cause hypotheses.

    Invariants and Policies:
    - Ground-Truth Isolation: Never imports, consumes, or inspects fault definitions or ground-truth records.
    - Determinism: Identical inputs and configuration always produce identical hypothesis rankings.
    - Explicit UNKNOWN: Generates an explicit UNKNOWN hypothesis when diagnostic evidence is inadequate.
    - No Automatic Remediation: Produces explainable recommendations without mutating network topology or state.
    """

    def __init__(
        self,
        config: Optional[RCAConfig] = None,
        topology: Optional[Topology] = None,
        transport: Optional[TransportNetwork] = None,
    ) -> None:
        if config is not None and not isinstance(config, RCAConfig):
            raise TypeError(f"Expected RCAConfig instance, got {type(config).__name__}")
        if topology is not None and not isinstance(topology, Topology):
            raise TypeError(f"Expected Topology instance, got {type(topology).__name__}")
        if transport is not None and not isinstance(transport, TransportNetwork):
            raise TypeError(f"Expected TransportNetwork instance, got {type(transport).__name__}")
        self._config = config if config is not None else RCAConfig()
        self._topology = topology
        self._transport = transport

    @property
    def config(self) -> RCAConfig:
        return self._config

    @property
    def topology(self) -> Optional[Topology]:
        return self._topology

    @property
    def transport(self) -> Optional[TransportNetwork]:
        return self._transport

    def analyze_group(
        self,
        group: CorrelationGroup,
        topology: Optional[Topology] = None,
        transport: Optional[TransportNetwork] = None,
        telemetry_snapshots: Optional[Sequence[KPISnapshot]] = None,
        analysis_timestamp: Optional[datetime] = None,
    ) -> RCAResult:
        """Perform root-cause analysis on a single correlation group.

        Args:
            group: CorrelationGroup containing correlated alarms.
            topology: Optional validated network topology graph (falls back to engine topology).
            transport: Optional transport network for link dependency resolution (falls back to engine transport).
            telemetry_snapshots: Optional observed telemetry snapshots for additional context.
            analysis_timestamp: Optional UTC timestamp for the analysis.

        Returns:
            RCAResult containing ranked hypotheses and primary diagnosis.

        Raises:
            RCAError: If input arguments are malformed or invalid.
        """
        if not isinstance(group, CorrelationGroup):
            raise RCAError(f"group must be a CorrelationGroup instance, got {type(group).__name__}")

        eff_topology = topology if topology is not None else self._topology
        if not isinstance(eff_topology, Topology):
            raise RCAError(f"topology must be a Topology instance, got {type(eff_topology).__name__}")

        eff_transport = transport if transport is not None else self._transport
        if eff_transport is not None and not isinstance(eff_transport, TransportNetwork):
            raise RCAError(f"transport must be a TransportNetwork instance, got {type(eff_transport).__name__}")

        now = analysis_timestamp if analysis_timestamp is not None else group.time_window_end

        ts_map: dict[str, KPISnapshot] = {}
        if telemetry_snapshots is not None:
            if isinstance(telemetry_snapshots, (str, bytes)) or not isinstance(telemetry_snapshots, Sequence):
                raise InsufficientTelemetryError("telemetry_snapshots must be a Sequence")
            for s in telemetry_snapshots:
                if not isinstance(s, KPISnapshot):
                    raise InsufficientTelemetryError(f"Expected KPISnapshot, got {type(s).__name__}")
            ts_map = _select_relevant_snapshots(
                telemetry_snapshots, group, self._config.max_telemetry_staleness_seconds, now
            )

        # 1. Evaluate all diagnostic rules
        rule_evaluators = [
            evaluate_site_power_failure,
            evaluate_backhaul_failure,
            evaluate_radio_interference,
            evaluate_cell_congestion,
            evaluate_cell_outage,
        ]

        candidate_hypotheses: list[RootCauseHypothesis] = []
        for rule_fn in rule_evaluators:
            hyp = rule_fn(group, eff_topology, eff_transport, ts_map)
            if hyp is not None:
                candidate_hypotheses.append(hyp)

        # 2. Deduplicate candidate hypotheses by (cause_type, target_id) retaining highest score
        best_by_key: dict[tuple[RootCauseType, str], RootCauseHypothesis] = {}
        for h in candidate_hypotheses:
            key = (h.cause_type, h.target_id)
            if key not in best_by_key or h.confidence_score > best_by_key[key].confidence_score:
                best_by_key[key] = h

        ranked_candidates = list(best_by_key.values())

        # 3. Deterministic ranking:
        # Primary: confidence_score descending
        # Secondary: evidence items count descending
        # Tertiary: target_id alphabetical
        # Quaternary: cause_type alphabetical
        ranked_candidates.sort(
            key=lambda h: (
                -h.confidence_score,
                -len(h.evidence_items),
                h.target_id,
                h.cause_type.value,
            )
        )

        # Limit to configured maximum hypotheses
        ranked_candidates = ranked_candidates[: self._config.max_hypotheses_per_group]

        # 4. Primary hypothesis selection
        primary: Optional[RootCauseHypothesis] = None
        if ranked_candidates and ranked_candidates[0].confidence_score >= self._config.min_confidence_threshold:
            primary = ranked_candidates[0]
        else:
            # Explicit UNKNOWN / INSUFFICIENT_EVIDENCE hypothesis
            unknown_hyp = RootCauseHypothesis(
                hypothesis_id=f"HYP-UNKNOWN-{group.group_id}",
                cause_type=RootCauseType.UNKNOWN,
                target_id=group.anchor_node_id or "UNKNOWN",
                target_type=TargetType.UNKNOWN,
                confidence_score=0.0,
                explanation="Insufficient diagnostic evidence to establish a definitive root cause hypothesis.",
                evidence_items=(),
                group_id=group.group_id,
            )
            primary = unknown_hyp
            # Include unknown hypothesis in list if no candidates found
            if not ranked_candidates:
                ranked_candidates = [unknown_hyp]

        rec_action = RECOMMENDED_ACTIONS.get(primary.cause_type, "Perform manual diagnostic triage.")

        return RCAResult(
            group_id=group.group_id,
            hypotheses=tuple(ranked_candidates),
            primary_hypothesis=primary,
            analysis_timestamp=now,
            recommended_action=rec_action,
        )

    def analyze_results(
        self,
        correlation_result: CorrelationResult,
        topology: Optional[Topology] = None,
        transport: Optional[TransportNetwork] = None,
        telemetry_snapshots: Optional[Sequence[KPISnapshot]] = None,
        analysis_timestamp: Optional[datetime] = None,
    ) -> list[RCAResult]:
        """Perform root-cause analysis on all correlation groups in a CorrelationResult."""
        if not isinstance(correlation_result, CorrelationResult):
            raise RCAError(f"Expected CorrelationResult instance, got {type(correlation_result).__name__}")

        eff_topology = topology if topology is not None else self._topology
        if not isinstance(eff_topology, Topology):
            raise RCAError(f"topology must be a Topology instance, got {type(eff_topology).__name__}")

        eff_transport = transport if transport is not None else self._transport
        if eff_transport is not None and not isinstance(eff_transport, TransportNetwork):
            raise RCAError(f"transport must be a TransportNetwork instance, got {type(eff_transport).__name__}")

        results: list[RCAResult] = []
        for group in correlation_result.groups:
            res = self.analyze_group(
                group=group,
                topology=eff_topology,
                transport=eff_transport,
                telemetry_snapshots=telemetry_snapshots,
                analysis_timestamp=analysis_timestamp,
            )
            results.append(res)
        return results

    analyze = analyze_results
