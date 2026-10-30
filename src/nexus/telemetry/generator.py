"""Synthetic telemetry generator modeling normal network baseline measurements."""

from datetime import datetime, timezone
import math
import random
from typing import Mapping, Optional

from nexus.telemetry.exceptions import (
    IncompatibleNodeError,
    InvalidProfileError,
)
from nexus.telemetry.models import (
    KPISnapshot,
    PerformanceMetrics,
    RadioMetrics,
    ReliabilityMetrics,
)
from nexus.telemetry.profiles import (
    DEFAULT_PROFILES,
    MetricRange,
    NodeOperatingProfile,
)
from nexus.topology.enums import NodeType
from nexus.topology.topology import Topology


def _clamp(val: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, val))


class SyntheticTelemetryGenerator:
    """Generates synthetic, deterministic time-series KPI snapshots for a network topology.

    Features:
    - Reproducible output across runs when using the same seed and explicit timestamps.
    - Basic temporal continuity: successive steps smoothly fluctuate around previous values
      via first-order exponential smoothing.
    - Simplified synthetic cross-KPI relationships:
      * Radio (CELL): Higher SINR positively influences throughput; higher PRB utilization
        models radio scheduling congestion, reducing available throughput and increasing latency.
        Poor SINR and elevated latency slightly degrade handover success and increase drop rate.
      * Transport (CORE/AGG/SITE): Throughput serves as a simplified traffic load proxy where
        higher load slightly increases queueing latency.
      * Availability: Synthetic measurement-window availability percentage (not an instantaneous
        physical sensor value or long-term historical uptime calculation).
    - Strict node-type profile alignment (Radio KPIs generated only for CELL nodes).
    """

    def __init__(
        self,
        topology: Topology,
        seed: Optional[int] = 42,
        profiles: Optional[Mapping[NodeType, NodeOperatingProfile]] = None,
        alpha: float = 0.65,
    ) -> None:
        """Initialize the synthetic generator.

        Args:
            topology: The network topology instance to generate metrics for.
            seed: Initial random seed for deterministic generation (default 42). Must be int or None.
            profiles: Mapping from NodeType to custom NodeOperatingProfile. Explicitly supports partial
                      mappings. Nodes whose NodeType lacks a profile will raise IncompatibleNodeError
                      during generation. Defaults to DEFAULT_PROFILES.
            alpha: Temporal smoothing weight [0.0, 1.0]. A value of 0.65 retains 65% of the previous
                   state and incorporates 35% of the new innovation per step.

        Raises:
            TypeError: If seed is not an int or None (e.g. booleans or floats).
            ValueError: If alpha is not a finite float within [0.0, 1.0] or if it is a boolean.
            InvalidProfileError: If custom profiles contain mismatched keys or invalid profile instances.
        """
        # Validate seed: must be int or None; reject bool (since bool is a subclass of int)
        if seed is not None:
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise TypeError(f"seed must be an integer or None, got {type(seed).__name__}")

        # Validate alpha
        if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
            raise ValueError(f"alpha must be a numeric value, got {type(alpha).__name__}")
        f_alpha = float(alpha)
        if not math.isfinite(f_alpha) or not (0.0 <= f_alpha <= 1.0):
            raise ValueError(f"alpha must be a finite number between 0.0 and 1.0, got {f_alpha}")

        # Validate custom profiles mapping (partial mappings explicitly supported)
        if profiles is not None:
            validated_profiles: dict[NodeType, NodeOperatingProfile] = {}
            for k, prof in profiles.items():
                if not isinstance(k, NodeType):
                    try:
                        k_coerced = NodeType(k)
                    except (ValueError, TypeError) as exc:
                        raise InvalidProfileError(f"Invalid NodeType key in profiles: {k}") from exc
                else:
                    k_coerced = k

                if not isinstance(prof, NodeOperatingProfile):
                    raise InvalidProfileError(
                        f"Expected NodeOperatingProfile for {k_coerced.value}, got {type(prof).__name__}"
                    )
                if prof.node_type != k_coerced:
                    raise InvalidProfileError(
                        f"Profile key {k_coerced.value} does not match profile.node_type {prof.node_type.value}"
                    )
                validated_profiles[k_coerced] = prof
            self._profiles = validated_profiles
        else:
            self._profiles = dict(DEFAULT_PROFILES)

        self._topology = topology
        self._rng = random.Random(seed)
        self._alpha = f_alpha
        # Internal state tracking per node_id: dict[node_id, dict[metric_name, float]]
        self._state: dict[str, dict[str, float]] = {}

    def _sample_range(self, r: MetricRange) -> float:
        """Sample a value from normal distribution around nominal value, bounded by [min, max]."""
        std = (r.max_val - r.min_val) / 6.0  # 99.7% of values fall within [min, max]
        val = self._rng.gauss(r.nominal, std)
        return _clamp(val, r.min_val, r.max_val)

    def _smooth(self, node_id: str, key: str, target: float, min_val: float, max_val: float) -> float:
        """Apply first-order exponential smoothing for temporal continuity."""
        node_hist = self._state.setdefault(node_id, {})
        if key in node_hist:
            prev = node_hist[key]
            smoothed = self._alpha * prev + (1.0 - self._alpha) * target
        else:
            smoothed = target
        smoothed = _clamp(smoothed, min_val, max_val)
        node_hist[key] = smoothed
        return smoothed

    def generate_node_snapshot(self, node_id: str, timestamp: Optional[datetime] = None) -> KPISnapshot:
        """Generate a single KPI snapshot for the specified node.

        Args:
            node_id: Identifier of the node in the topology.
            timestamp: Measurement timestamp (defaults to current UTC time).

        Returns:
            A validated KPISnapshot instance.

        Raises:
            NodeNotFoundError: If node_id does not exist in the topology.
            IncompatibleNodeError: If no operating profile exists for the node's type.
            InvalidProfileError: If the profile configuration lacks required ranges.
        """
        node = self._topology.get_node(node_id)
        if node.node_type not in self._profiles:
            raise IncompatibleNodeError(
                f"No operating profile configured for node type: {node.node_type.value}"
            )

        prof = self._profiles[node.node_type]
        ts = timestamp or datetime.now(timezone.utc)

        if node.node_type == NodeType.CELL:
            # Explicit domain validation replacing runtime assertions
            if (
                prof.rsrp_dbm is None
                or prof.sinr_db is None
                or prof.prb_utilization_pct is None
                or prof.handover_success_rate_pct is None
            ):
                raise InvalidProfileError(
                    f"CELL profile for {node_id} is missing required radio or handover ranges"
                )

            # 1. Sample radio parameters
            target_rsrp = self._sample_range(prof.rsrp_dbm)
            target_sinr = self._sample_range(prof.sinr_db)
            target_prb = self._sample_range(prof.prb_utilization_pct)

            rsrp = self._smooth(node_id, "rsrp", target_rsrp, prof.rsrp_dbm.min_val, prof.rsrp_dbm.max_val)
            sinr = self._smooth(node_id, "sinr", target_sinr, prof.sinr_db.min_val, prof.sinr_db.max_val)
            prb = self._smooth(node_id, "prb", target_prb, prof.prb_utilization_pct.min_val, prof.prb_utilization_pct.max_val)

            radio_metrics = RadioMetrics(
                rsrp_dbm=round(rsrp, 2),
                sinr_db=round(sinr, 2),
                prb_utilization_pct=round(prb, 2),
            )

            # 2. Correlated Performance measurements for CELL:
            # Absolute channel quality factor mapped across standard cellular operational span [-10.0 dB, 30.0 dB]
            # Higher absolute SINR improves modulation and coding scheme (MCS) efficiency, increasing throughput
            sinr_factor = _clamp((sinr - (-10.0)) / 40.0, 0.0, 1.0)

            # High PRB utilization reduces available throughput headroom [0.7, 1.0]
            prb_congestion_factor = 1.0 - 0.3 * (prb / 100.0)

            raw_tp_range = prof.throughput_mbps.max_val - prof.throughput_mbps.min_val
            target_throughput = (
                prof.throughput_mbps.min_val
                + raw_tp_range * (0.3 + 0.7 * sinr_factor) * prb_congestion_factor
                + self._rng.uniform(-5.0, 5.0)
            )

            # High PRB congestion increases radio scheduling queue delay
            raw_lat_range = prof.latency_ms.max_val - prof.latency_ms.min_val
            prb_latency_factor = prb / 100.0
            target_latency = (
                prof.latency_ms.min_val
                + raw_lat_range * (0.2 + 0.8 * prb_latency_factor)
                + self._rng.uniform(-0.5, 0.5)
            )

            throughput = self._smooth(
                node_id, "throughput", target_throughput, prof.throughput_mbps.min_val, prof.throughput_mbps.max_val
            )
            latency = self._smooth(
                node_id, "latency", target_latency, prof.latency_ms.min_val, prof.latency_ms.max_val
            )

            perf_metrics = PerformanceMetrics(
                throughput_mbps=round(throughput, 2),
                latency_ms=round(latency, 2),
            )

            # 3. Correlated Reliability measurements for CELL:
            # - Handover success rate: Slightly penalised by poor SINR or high latency
            lat_span = max(0.001, prof.latency_ms.max_val - prof.latency_ms.min_val)
            norm_lat = _clamp((latency - prof.latency_ms.min_val) / lat_span, 0.0, 1.0)
            hosr_range = prof.handover_success_rate_pct.max_val - prof.handover_success_rate_pct.min_val
            target_hosr = (
                prof.handover_success_rate_pct.nominal
                + hosr_range * 0.25 * (sinr_factor - norm_lat)
                + self._rng.uniform(-0.1, 0.1)
            )

            # - Connection drop rate: Modestly increases under poor SINR and elevated latency
            drop_range = prof.connection_drop_rate_pct.max_val - prof.connection_drop_rate_pct.min_val
            target_drop = (
                prof.connection_drop_rate_pct.nominal
                + drop_range * 0.35 * (norm_lat - sinr_factor)
                + self._rng.uniform(-0.01, 0.01)
            )

            # Synthetic measurement-window availability percentage (not calculated historical uptime)
            target_avail = self._sample_range(prof.availability_pct)

            hosr = self._smooth(
                node_id, "hosr", target_hosr, prof.handover_success_rate_pct.min_val, prof.handover_success_rate_pct.max_val
            )
            drop = self._smooth(
                node_id, "drop", target_drop, prof.connection_drop_rate_pct.min_val, prof.connection_drop_rate_pct.max_val
            )
            avail = self._smooth(
                node_id, "avail", target_avail, prof.availability_pct.min_val, prof.availability_pct.max_val
            )

            rel_metrics = ReliabilityMetrics(
                connection_drop_rate_pct=round(drop, 3),
                availability_pct=round(avail, 3),
                handover_success_rate_pct=round(hosr, 2),
            )

        else:
            # Non-radio transport nodes (CORE, AGGREGATION, SITE)
            radio_metrics = None

            # Sample performance using throughput as a simplified traffic load proxy
            target_tp = self._sample_range(prof.throughput_mbps)
            throughput = self._smooth(
                node_id, "throughput", target_tp, prof.throughput_mbps.min_val, prof.throughput_mbps.max_val
            )

            # Higher throughput load slightly increases queueing delay
            load_factor = (throughput - prof.throughput_mbps.min_val) / max(
                1.0, (prof.throughput_mbps.max_val - prof.throughput_mbps.min_val)
            )
            target_lat = prof.latency_ms.min_val + (prof.latency_ms.max_val - prof.latency_ms.min_val) * (
                0.2 + 0.8 * load_factor
            )
            latency = self._smooth(
                node_id, "latency", target_lat, prof.latency_ms.min_val, prof.latency_ms.max_val
            )

            perf_metrics = PerformanceMetrics(
                throughput_mbps=round(throughput, 2),
                latency_ms=round(latency, 2),
            )

            target_drop = self._sample_range(prof.connection_drop_rate_pct)
            # Synthetic measurement-window availability percentage (not calculated historical uptime)
            target_avail = self._sample_range(prof.availability_pct)

            drop = self._smooth(
                node_id, "drop", target_drop, prof.connection_drop_rate_pct.min_val, prof.connection_drop_rate_pct.max_val
            )
            avail = self._smooth(
                node_id, "avail", target_avail, prof.availability_pct.min_val, prof.availability_pct.max_val
            )

            rel_metrics = ReliabilityMetrics(
                connection_drop_rate_pct=round(drop, 4),
                availability_pct=round(avail, 4),
                handover_success_rate_pct=None,
            )

        return KPISnapshot(
            node_id=node_id,
            timestamp=ts,
            performance=perf_metrics,
            reliability=rel_metrics,
            radio=radio_metrics,
        )

    def generate_step(self, timestamp: Optional[datetime] = None) -> list[KPISnapshot]:
        """Generate snapshots for all nodes currently registered in the topology for this time step.

        Args:
            timestamp: Optional explicit timestamp for this step (defaults to current UTC time).
                       Providing explicit timestamps ensures complete snapshot reproducibility.

        Returns:
            List of KPISnapshot instances, one per topology node.
        """
        ts = timestamp or datetime.now(timezone.utc)
        snapshots: list[KPISnapshot] = []
        for node in self._topology.all_nodes():
            snapshots.append(self.generate_node_snapshot(node.node_id, timestamp=ts))
        return snapshots
