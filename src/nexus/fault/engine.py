"""Deterministic fault scenario evaluation and telemetry transformation engine."""

from collections import deque
from dataclasses import replace
from datetime import datetime
from typing import Iterable, Mapping, Optional, Sequence

from nexus.fault.exceptions import (
    ConflictingFaultError,
    IncompatibleTargetError,
    InvalidFaultStateError,
    ScenarioError,
)
from nexus.fault.models import (
    FAULT_EFFECT_DIMENSIONS,
    EffectDimension,
    Fault,
    FaultType,
    GroundTruthRecord,
    _normalize_utc_timestamp,
)
from nexus.telemetry.models import (
    KPISnapshot,
    PerformanceMetrics,
    RadioMetrics,
    ReliabilityMetrics,
)
from nexus.topology.enums import NodeType
from nexus.topology.topology import Topology
from nexus.transport.network import TransportNetwork


def _clamp(val: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, val))


class FaultScenarioEngine:
    """Manages deterministic fault evaluation, impact propagation, and telemetry transformation.

    Invariants:
    - Evaluates active faults in half-open interval: start_time <= timestamp < end_time.
    - Deterministic downstream impact propagation:
      * CELL_OUTAGE, RADIO_INTERFERENCE, CELL_CONGESTION: Target CELL node only.
      * BACKHAUL_FAILURE: Downstream node of transport link + all descendant nodes (BFS order).
      * SITE_POWER_FAILURE: Target SITE node + all descendant cell nodes (BFS order).
    - Impact-aware conflict detection rejects scenarios where faults exhibit:
      * Temporal overlap: Active time intervals intersect.
      * Shared affected nodes: Impacted node sets (blast radii) intersect.
      * Shared operational effect dimensions: Faults modulate competing operational dimensions
        (availability, radio signal, radio resource, performance, reliability).
    - Topology impact snapshot: The engine freezes the affected-node impact set for all faults at
      construction time. An engine uses a topology snapshot of fault impact at construction time.
      Reconstruct the engine to use a changed topology.
    - Non-destructive transformation: KPISnapshot instances are never mutated in place.
    - Ground truth recording: Pre-computes and provides immutable GroundTruthRecord instances.
    """

    def __init__(
        self,
        topology: Topology,
        transport: TransportNetwork,
        faults: Sequence[Fault],
        scenario_id: str = "DEFAULT-SCENARIO",
        description: Optional[str] = None,
    ) -> None:
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise ScenarioError("scenario_id must be a non-empty string")

        self._topology = topology
        self._transport = transport
        self._scenario_id = scenario_id.strip()
        self._description = description

        # 1. Validate fault IDs for uniqueness
        seen_fault_ids: set[str] = set()
        for f in faults:
            if not isinstance(f, Fault):
                raise ScenarioError(f"Expected Fault instance, got {type(f).__name__}")
            if f.fault_id in seen_fault_ids:
                raise InvalidFaultStateError(f"Duplicate fault_id '{f.fault_id}' in scenario")
            seen_fault_ids.add(f.fault_id)

        # 2. Validate target compatibility against topology & transport
        for f in faults:
            self._validate_fault_target(f)

        # 3. Calculate and freeze the affected-node tuple for every fault exactly once
        self._fault_affected_nodes: dict[str, tuple[str, ...]] = {
            f.fault_id: tuple(self._compute_affected_nodes(f)) for f in faults
        }

        # 4. Detect ambiguous conflicts between overlapping faults using frozen impact sets
        self._detect_conflicts(faults)

        self._faults: tuple[Fault, ...] = tuple(faults)

        # 5. Precompute ground truth records using frozen impact sets
        self._ground_truth: tuple[GroundTruthRecord, ...] = tuple(
            self._build_ground_truth(f) for f in self._faults
        )

    def _validate_fault_target(self, fault: Fault) -> None:
        """Validate target entity type against the required fault target tier."""
        if fault.fault_type == FaultType.BACKHAUL_FAILURE:
            if not self._transport.has_link(fault.target_id):
                raise IncompatibleTargetError(
                    f"BACKHAUL_FAILURE target '{fault.target_id}' does not exist in transport network"
                )
        elif fault.fault_type in (FaultType.CELL_OUTAGE, FaultType.RADIO_INTERFERENCE, FaultType.CELL_CONGESTION):
            if not self._topology.has_node(fault.target_id):
                raise IncompatibleTargetError(
                    f"{fault.fault_type.value} target '{fault.target_id}' does not exist in topology"
                )
            target_node = self._topology.get_node(fault.target_id)
            if target_node.node_type != NodeType.CELL:
                raise IncompatibleTargetError(
                    f"{fault.fault_type.value} requires a CELL node target, got {target_node.node_type.value} ('{fault.target_id}')"
                )
        elif fault.fault_type == FaultType.SITE_POWER_FAILURE:
            if not self._topology.has_node(fault.target_id):
                raise IncompatibleTargetError(
                    f"SITE_POWER_FAILURE target '{fault.target_id}' does not exist in topology"
                )
            target_node = self._topology.get_node(fault.target_id)
            if target_node.node_type != NodeType.SITE:
                raise IncompatibleTargetError(
                    f"SITE_POWER_FAILURE requires a SITE node target, got {target_node.node_type.value} ('{fault.target_id}')"
                )

    def _compute_affected_nodes(self, fault: Fault) -> list[str]:
        """Compute the deterministic list of topology nodes impacted by this fault."""
        affected: list[str] = []
        if fault.fault_type in (FaultType.CELL_OUTAGE, FaultType.RADIO_INTERFERENCE, FaultType.CELL_CONGESTION):
            affected.append(fault.target_id)
        elif fault.fault_type == FaultType.SITE_POWER_FAILURE:
            # Target site itself + all its descendants (deterministic BFS order)
            affected.append(fault.target_id)
            descendants = self._topology.get_descendants(fault.target_id)
            affected.extend(d.node_id for d in descendants)
        elif fault.fault_type == FaultType.BACKHAUL_FAILURE:
            # Target transport link downstream node + all descendants
            link = self._transport.get_link(fault.target_id)
            downstream_id = link.downstream_node_id
            affected.append(downstream_id)
            descendants = self._topology.get_descendants(downstream_id)
            affected.extend(d.node_id for d in descendants)

        return affected

    def _build_ground_truth(self, fault: Fault) -> GroundTruthRecord:
        """Create an immutable GroundTruthRecord for a fault using frozen impact nodes."""
        affected_nodes = self._fault_affected_nodes[fault.fault_id]
        return GroundTruthRecord(
            scenario_id=self._scenario_id,
            fault_id=fault.fault_id,
            fault_type=fault.fault_type,
            target_id=fault.target_id,
            start_time=fault.start_time,
            end_time=fault.end_time,
            severity=fault.severity,
            affected_node_ids=affected_nodes,
            description=fault.description,
        )

    def _detect_conflicts(self, faults: Sequence[Fault]) -> None:
        """Check for conflicting overlapping faults affecting the same nodes and effect dimensions.

        Uses the precalculated affected nodes frozen during initialization.
        """
        for i in range(len(faults)):
            for j in range(i + 1, len(faults)):
                f1, f2 = faults[i], faults[j]
                # Check for temporal overlap: not (f1.end <= f2.start or f2.end <= f1.start)
                overlaps = not (f1.end_time <= f2.start_time or f2.end_time <= f1.start_time)
                if not overlaps:
                    continue

                # Find overlapping affected nodes
                nodes_f1 = set(self._fault_affected_nodes[f1.fault_id])
                nodes_f2 = set(self._fault_affected_nodes[f2.fault_id])
                common_nodes = nodes_f1 & nodes_f2
                if not common_nodes:
                    continue

                shared_dims = FAULT_EFFECT_DIMENSIONS[f1.fault_type] & FAULT_EFFECT_DIMENSIONS[f2.fault_type]
                if shared_dims:
                    nodes_str = ", ".join(sorted(common_nodes))
                    dims_str = ", ".join(sorted(d.value for d in shared_dims))
                    raise ConflictingFaultError(
                        f"Conflicting overlapping faults '{f1.fault_id}' ({f1.fault_type.value}) and "
                        f"'{f2.fault_id}' ({f2.fault_type.value}) concurrently affect node(s) [{nodes_str}] "
                        f"on operational dimension(s): {dims_str}"
                    )

    @property
    def scenario_id(self) -> str:
        return self._scenario_id

    @property
    def description(self) -> Optional[str]:
        return self._description

    @property
    def faults(self) -> tuple[Fault, ...]:
        return self._faults

    def get_ground_truth(self) -> tuple[GroundTruthRecord, ...]:
        """Return the precomputed ground truth records for this scenario."""
        return self._ground_truth

    def get_active_faults(self, timestamp: datetime) -> list[Fault]:
        """Return all faults active at the given timestamp."""
        norm_ts = _normalize_utc_timestamp("timestamp", timestamp)
        return [f for f in self._faults if f.is_active_at(norm_ts)]

    def get_active_affected_nodes(self, timestamp: datetime) -> dict[str, list[Fault]]:
        """Map each currently affected node_id to the list of active faults impacting it.

        Uses the frozen affected-node sets computed at engine initialization time.
        """
        active_faults = self.get_active_faults(timestamp)
        node_fault_map: dict[str, list[Fault]] = {}
        for f in active_faults:
            for node_id in self._fault_affected_nodes[f.fault_id]:
                node_fault_map.setdefault(node_id, []).append(f)
        return node_fault_map

    def apply_faults(
        self,
        base_snapshots: Iterable[KPISnapshot],
        timestamp: datetime,
    ) -> list[KPISnapshot]:
        """Transform base telemetry snapshots by applying active fault effects.

        Does not mutate the input snapshots; returns a new list of transformed KPISnapshot instances.
        If no faults are active, returns unmodified copies of the base snapshots.

        Args:
            base_snapshots: Unmodified base telemetry snapshots (e.g. from SyntheticTelemetryGenerator).
            timestamp: Simulation timestamp to evaluate active faults.

        Returns:
            List of effective KPISnapshot instances.
        """
        norm_ts = _normalize_utc_timestamp("timestamp", timestamp)
        active_faults = self.get_active_faults(norm_ts)
        if not active_faults:
            return list(base_snapshots)

        node_fault_map = self.get_active_affected_nodes(norm_ts)
        effective_snapshots: list[KPISnapshot] = []

        for snap in base_snapshots:
            node_id = snap.node_id
            if node_id not in node_fault_map:
                effective_snapshots.append(snap)
                continue

            impact_faults = node_fault_map[node_id]
            effective_snap = snap

            # Determine dominant impact on this node
            # Priority: Outage / Link failure / Power failure > Congestion / Interference
            is_outage = any(
                f.fault_type in (FaultType.CELL_OUTAGE, FaultType.SITE_POWER_FAILURE, FaultType.BACKHAUL_FAILURE)
                for f in impact_faults
            )

            if is_outage:
                effective_snap = self._apply_outage(snap)
            else:
                for f in impact_faults:
                    if f.fault_type == FaultType.RADIO_INTERFERENCE:
                        effective_snap = self._apply_interference(effective_snap, f.severity)
                    elif f.fault_type == FaultType.CELL_CONGESTION:
                        effective_snap = self._apply_congestion(effective_snap, f.severity)

            effective_snapshots.append(effective_snap)

        return effective_snapshots

    def _apply_outage(self, snap: KPISnapshot) -> KPISnapshot:
        """Apply complete service outage to a snapshot (0 throughput, 0 availability, 100% drop)."""
        new_perf = replace(
            snap.performance,
            throughput_mbps=0.0,
            # Under outage, latency represents maximum timeout / unreachable penalty
            latency_ms=round(snap.performance.latency_ms * 3.0, 2),
        )
        new_rel = replace(
            snap.reliability,
            connection_drop_rate_pct=100.0,
            availability_pct=0.0,
            handover_success_rate_pct=0.0 if snap.reliability.handover_success_rate_pct is not None else None,
        )
        new_radio = None
        if snap.radio is not None:
            new_radio = replace(
                snap.radio,
                # Outage: minimal power and severely degraded SNR
                rsrp_dbm=-145.0,
                sinr_db=-25.0,
                prb_utilization_pct=0.0,
            )

        return replace(
            snap,
            performance=new_perf,
            reliability=new_rel,
            radio=new_radio,
        )

    def _apply_interference(self, snap: KPISnapshot, severity: float) -> KPISnapshot:
        """Apply radio interference to a CELL node snapshot: degrades SINR, throughput, and handover."""
        if snap.radio is None:
            return snap

        # Degrade SINR proportional to severity (up to -20 dB degradation)
        sinr_penalty = severity * 20.0
        new_sinr = _clamp(snap.radio.sinr_db - sinr_penalty, -25.0, 50.0)

        # Throughput reduces proportional to SINR reduction
        tp_reduction = severity * 0.65
        new_tp = _clamp(snap.performance.throughput_mbps * (1.0 - tp_reduction), 0.0, 10000.0)

        # Handover success rate slightly drops
        new_hosr = None
        if snap.reliability.handover_success_rate_pct is not None:
            new_hosr = _clamp(
                snap.reliability.handover_success_rate_pct - (severity * 15.0),
                0.0,
                100.0,
            )

        new_drop = _clamp(
            snap.reliability.connection_drop_rate_pct + (severity * 5.0),
            0.0,
            100.0,
        )

        new_radio = replace(snap.radio, sinr_db=round(new_sinr, 2))
        new_perf = replace(snap.performance, throughput_mbps=round(new_tp, 2))
        new_rel = replace(
            snap.reliability,
            connection_drop_rate_pct=round(new_drop, 3),
            handover_success_rate_pct=round(new_hosr, 2) if new_hosr is not None else None,
        )

        return replace(
            snap,
            performance=new_perf,
            reliability=new_rel,
            radio=new_radio,
        )

    def _apply_congestion(self, snap: KPISnapshot, severity: float) -> KPISnapshot:
        """Apply cell congestion: pushes PRB utilization towards 100%, raises queue latency, restricts throughput."""
        if snap.radio is None:
            return snap

        # Boost PRB utilization towards saturation
        prb_boost = severity * (100.0 - snap.radio.prb_utilization_pct)
        new_prb = _clamp(snap.radio.prb_utilization_pct + prb_boost, 0.0, 100.0)

        # Congestion queue delays increase latency
        lat_penalty = severity * 20.0
        new_lat = _clamp(snap.performance.latency_ms + lat_penalty, 0.0, 1000.0)

        # Congestion puts downward pressure on per-session throughput
        tp_factor = 1.0 - (0.4 * severity)
        new_tp = _clamp(snap.performance.throughput_mbps * tp_factor, 0.0, 10000.0)

        new_radio = replace(snap.radio, prb_utilization_pct=round(new_prb, 2))
        new_perf = replace(
            snap.performance,
            latency_ms=round(new_lat, 2),
            throughput_mbps=round(new_tp, 2),
        )

        return replace(
            snap,
            performance=new_perf,
            radio=new_radio,
        )
