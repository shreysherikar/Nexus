"""Statistical anomaly detection using Rolling Median and EWMA baselines."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import math
import statistics
from typing import Any, Mapping, Optional, Sequence

from nexus.detection.exceptions import InvalidDetectorConfigError
from nexus.detection.models import AnomalyEvent, DetectionSource, Severity
from nexus.detection.threshold_detector import extract_snapshot_metrics
from nexus.telemetry.models import KPISnapshot
from nexus.telemetry.profiles import DEFAULT_PROFILES, MetricRange, NodeOperatingProfile
from nexus.topology.enums import NodeType


# KPI Operational Directionality classification
HIGHER_IS_BETTER_KPIS: frozenset[str] = frozenset({
    "availability_pct",
    "throughput_mbps",
    "handover_success_rate_pct",
    "sinr_db",
    "rsrp_dbm",
})

LOWER_IS_BETTER_KPIS: frozenset[str] = frozenset({
    "connection_drop_rate_pct",
    "latency_ms",
})

RESOURCE_UTILIZATION_KPIS: frozenset[str] = frozenset({
    "prb_utilization_pct",
})


def is_metric_healthy(
    metric_name: str,
    val: float,
    node_type: Optional[NodeType] = None,
) -> bool:
    """Check whether a metric value is within healthy nominal operating bounds."""
    if node_type is not None:
        profile = DEFAULT_PROFILES.get(node_type)
        if profile is not None:
            r = getattr(profile, metric_name, None)
            if isinstance(r, MetricRange):
                return r.min_val <= val <= r.max_val

    if metric_name in HIGHER_IS_BETTER_KPIS:
        if metric_name == "availability_pct":
            return val >= 99.0
        elif metric_name == "handover_success_rate_pct":
            return val >= 98.0
        elif metric_name == "throughput_mbps":
            return val >= 50.0
        elif metric_name == "sinr_db":
            return val >= 5.0
        elif metric_name == "rsrp_dbm":
            return val >= -115.0
    elif metric_name in LOWER_IS_BETTER_KPIS:
        if metric_name == "connection_drop_rate_pct":
            return val <= 1.0
        elif metric_name == "latency_ms":
            return val <= 40.0
    elif metric_name in RESOURCE_UTILIZATION_KPIS:
        if metric_name == "prb_utilization_pct":
            return 5.0 <= val <= 80.0

    return False


def is_baseline_degraded(
    metric_name: str,
    baseline_val: float,
    node_type: Optional[NodeType] = None,
) -> bool:
    """Check whether a baseline (median or mean) has learned degraded/fault conditions."""
    if metric_name == "availability_pct":
        return baseline_val < 50.0
    elif metric_name == "handover_success_rate_pct":
        return baseline_val < 50.0
    elif metric_name == "throughput_mbps":
        return baseline_val < 5.0
    elif metric_name == "sinr_db":
        return baseline_val < -5.0
    elif metric_name == "rsrp_dbm":
        return baseline_val < -130.0
    elif metric_name == "connection_drop_rate_pct":
        return baseline_val > 20.0
    elif metric_name == "latency_ms":
        return baseline_val <= 0.0 or baseline_val > 80.0
    elif metric_name == "prb_utilization_pct":
        return baseline_val < 2.0

    return False


def _validate_numeric_param(name: str, val: Any, min_val: Optional[float] = None, max_val: Optional[float] = None) -> float:
    """Validate that val is a finite float within bounds, rejecting bools."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise InvalidDetectorConfigError(f"{name} must be a numeric value, got {type(val).__name__}")
    f_val = float(val)
    if not math.isfinite(f_val):
        raise InvalidDetectorConfigError(f"{name} must be a finite number, got {f_val}")
    if min_val is not None and f_val < min_val:
        raise InvalidDetectorConfigError(f"{name} ({f_val}) cannot be less than {min_val}")
    if max_val is not None and f_val > max_val:
        raise InvalidDetectorConfigError(f"{name} ({f_val}) cannot exceed {max_val}")
    return f_val


def _validate_int_param(name: str, val: Any, min_val: int) -> int:
    """Validate integer parameter, rejecting booleans and floats."""
    if isinstance(val, bool) or not isinstance(val, int):
        raise InvalidDetectorConfigError(f"{name} must be an integer, got {type(val).__name__}")
    if val < min_val:
        raise InvalidDetectorConfigError(f"{name} ({val}) cannot be less than {min_val}")
    return val


@dataclass(frozen=True)
class StatisticalDetectorConfig:
    """Configuration for statistical anomaly detectors.

    Attributes:
        window_size: Maximum history points preserved per node and metric for rolling median (>= 3).
        warmup_count: Minimum observations required before anomalies can be flagged (>= 1, <= window_size).
        median_deviation_threshold: Number of MAD scale deviations to trigger rolling median anomaly (> 0.0).
        ewma_alpha: Exponential decay weighting factor (0.0 < alpha < 1.0).
        ewma_sensitivity: Number of standard deviations from EWMA baseline to trigger anomaly (> 0.0).
        severity: Severity assigned to statistical alarms (default MAJOR).
        enable_rolling_median: Whether to evaluate rolling median deviations.
        enable_ewma: Whether to evaluate EWMA deviations.
        directional_mode: Whether to enforce KPI operational directionality (higher-is-better / lower-is-better).
        consecutive_recovery_count: Consecutive normal observations required to clear an active alarm (>= 1).
        recovery_hysteresis_factor: Multiplier applied to deviation thresholds for alarm recovery (0.1 <= factor <= 1.0).
        surge_ratio_threshold: Minimum fold increase (e.g. 2.0x) for throughput to trigger a positive surge anomaly (> 1.0).
        two_sided: Whether to enforce two-sided anomaly detection, overriding directional suppression.
    """

    window_size: int = 20
    warmup_count: int = 5
    median_deviation_threshold: float = 3.0
    ewma_alpha: float = 0.2
    ewma_sensitivity: float = 3.0
    severity: Severity = Severity.MAJOR
    enable_rolling_median: bool = True
    enable_ewma: bool = True
    directional_mode: bool = False
    consecutive_recovery_count: int = 1
    recovery_hysteresis_factor: float = 0.8
    surge_ratio_threshold: float = 2.0
    two_sided: bool = False

    def __post_init__(self) -> None:
        win = _validate_int_param("window_size", self.window_size, min_val=3)
        warm = _validate_int_param("warmup_count", self.warmup_count, min_val=1)
        if warm > win:
            raise InvalidDetectorConfigError(
                f"warmup_count ({warm}) cannot be greater than window_size ({win})"
            )
        object.__setattr__(self, "window_size", win)
        object.__setattr__(self, "warmup_count", warm)

        med_thresh = _validate_numeric_param("median_deviation_threshold", self.median_deviation_threshold, min_val=0.001)
        object.__setattr__(self, "median_deviation_threshold", med_thresh)

        alpha = _validate_numeric_param("ewma_alpha", self.ewma_alpha, min_val=0.0001, max_val=0.9999)
        object.__setattr__(self, "ewma_alpha", alpha)

        ewma_sens = _validate_numeric_param("ewma_sensitivity", self.ewma_sensitivity, min_val=0.001)
        object.__setattr__(self, "ewma_sensitivity", ewma_sens)

        if not isinstance(self.severity, Severity):
            try:
                object.__setattr__(self, "severity", Severity(self.severity))
            except (ValueError, TypeError) as exc:
                raise InvalidDetectorConfigError(f"Invalid severity: {self.severity}") from exc

        if not isinstance(self.enable_rolling_median, bool):
            raise InvalidDetectorConfigError("enable_rolling_median must be a boolean")
        if not isinstance(self.enable_ewma, bool):
            raise InvalidDetectorConfigError("enable_ewma must be a boolean")
        if not isinstance(self.directional_mode, bool):
            raise InvalidDetectorConfigError("directional_mode must be a boolean")
        if not isinstance(self.two_sided, bool):
            raise InvalidDetectorConfigError("two_sided must be a boolean")

        consec = _validate_int_param("consecutive_recovery_count", self.consecutive_recovery_count, min_val=1)
        object.__setattr__(self, "consecutive_recovery_count", consec)

        hyst = _validate_numeric_param("recovery_hysteresis_factor", self.recovery_hysteresis_factor, min_val=0.1, max_val=1.0)
        object.__setattr__(self, "recovery_hysteresis_factor", hyst)

        surge_thresh = _validate_numeric_param("surge_ratio_threshold", self.surge_ratio_threshold, min_val=1.01)
        object.__setattr__(self, "surge_ratio_threshold", surge_thresh)


class StatisticalDetector:
    """Maintains independent time-series baselines per (node, metric) and flags anomalies.

    Methods:
    - Rolling Median: Uses Median Absolute Deviation (MAD) scaled by 1.4826 for normal consistency.
    - EWMA: Exponentially Weighted Moving Average with recursive variance tracking.

    Contamination Prevention & Healing:
    - When an observation is flagged as an anomaly, it is excluded from baseline updates.
    - If a baseline was contaminated during a fault, healthy recovered telemetry is recognized,
      does not raise spurious anomalies, and safely updates/heals the baseline.
    - Deterministic pre-seeding is supported via seed_from_profile() and seed_baselines().
    """

    def __init__(self, config: Optional[StatisticalDetectorConfig] = None) -> None:
        self._config = config if config is not None else StatisticalDetectorConfig()

        # State mapping: (node_id, metric_name) -> deque of floats (bounded by window_size)
        self._median_histories: dict[tuple[str, str], deque[float]] = {}

        # State mapping: (node_id, metric_name) -> {"mean": float, "var": float, "count": float}
        self._ewma_states: dict[tuple[str, str], dict[str, float]] = {}

        # Recovery tracking: (node_id, metric_name, source) -> consecutive healthy observation count
        self._recovery_counters: dict[tuple[str, str, DetectionSource], int] = {}

        # Expected metric spread from profile ranges: (node_id, metric_name) -> profile spread (sigma)
        self._profile_spreads: dict[tuple[str, str], float] = {}

    @property
    def config(self) -> StatisticalDetectorConfig:
        return self._config

    def reset(self) -> None:
        """Clear all internal history, baseline states, and recovery counters."""
        self._median_histories.clear()
        self._ewma_states.clear()
        self._recovery_counters.clear()
        self._profile_spreads.clear()

    def reset_node(self, node_id: str) -> None:
        """Clear internal states and recovery counters for a specific node."""
        med_keys = [k for k in self._median_histories if k[0] == node_id]
        for k in med_keys:
            del self._median_histories[k]

        ewma_keys = [k for k in self._ewma_states if k[0] == node_id]
        for k in ewma_keys:
            del self._ewma_states[k]

        rec_keys = [k for k in self._recovery_counters if k[0] == node_id]
        for k in rec_keys:
            del self._recovery_counters[k]

        spread_keys = [k for k in self._profile_spreads if k[0] == node_id]
        for k in spread_keys:
            del self._profile_spreads[k]

    def _resolve_profile_spread(
        self,
        node_id: str,
        metric_name: str,
        baseline_val: float,
        node_type: Optional[NodeType] = None,
    ) -> float:
        """Resolve expected metric spread from seeded profile or default NodeType profiles.

        Falls back to 5% of baseline value (min 1.0) if no profile is available.
        """
        key = (node_id, metric_name)
        if key in self._profile_spreads:
            return self._profile_spreads[key]

        if node_type is None:
            prefix = node_id.split("-")[0].upper()
            if prefix == "CELL":
                node_type = NodeType.CELL
            elif prefix in ("SITE", "ENB", "GNB"):
                node_type = NodeType.SITE
            elif prefix == "AGG":
                node_type = NodeType.AGGREGATION
            elif prefix == "CORE":
                node_type = NodeType.CORE

        if node_type is not None:
            profile = DEFAULT_PROFILES.get(node_type)
            if profile is not None:
                r = getattr(profile, metric_name, None)
                if isinstance(r, MetricRange):
                    spread = max(abs(r.max_val - r.min_val) / 6.0, 0.05 * abs(r.nominal), 1.0)
                    self._profile_spreads[key] = spread
                    return spread

        return 0.05 * max(abs(baseline_val), 1.0)

    def seed_from_profile(
        self,
        node_id: str,
        profile: NodeOperatingProfile,
        count: Optional[int] = None,
    ) -> None:
        """Seed rolling median and EWMA baselines from a node operating profile."""
        seed_count = count if count is not None else self._config.warmup_count
        seed_count = max(1, min(seed_count, self._config.window_size))

        ranges: dict[str, MetricRange] = {
            "throughput_mbps": profile.throughput_mbps,
            "latency_ms": profile.latency_ms,
            "connection_drop_rate_pct": profile.connection_drop_rate_pct,
            "availability_pct": profile.availability_pct,
        }
        if profile.handover_success_rate_pct is not None:
            ranges["handover_success_rate_pct"] = profile.handover_success_rate_pct
        if profile.rsrp_dbm is not None:
            ranges["rsrp_dbm"] = profile.rsrp_dbm
        if profile.sinr_db is not None:
            ranges["sinr_db"] = profile.sinr_db
        if profile.prb_utilization_pct is not None:
            ranges["prb_utilization_pct"] = profile.prb_utilization_pct

        for metric_name, r in ranges.items():
            key = (node_id, metric_name)
            nominal = float(r.nominal)
            self._median_histories[key] = deque([nominal] * seed_count, maxlen=self._config.window_size)
            spread = max(abs(r.max_val - r.min_val) / 6.0, 0.05 * abs(nominal), 1.0)
            self._profile_spreads[key] = spread
            self._ewma_states[key] = {
                "mean": nominal,
                "var": spread ** 2,
                "count": float(seed_count),
            }

    def seed_baselines(
        self,
        node_id: str,
        node_type: NodeType,
        count: Optional[int] = None,
        overwrite: bool = False,
    ) -> bool:
        """Seed baselines from DEFAULT_PROFILES for the given NodeType. Returns True if seeded."""
        if not overwrite and (node_id, "availability_pct") in self._median_histories:
            return False
        if not isinstance(node_type, NodeType):
            try:
                node_type = NodeType(node_type)
            except Exception:
                return False
        profile = DEFAULT_PROFILES.get(node_type)
        if profile is not None:
            self.seed_from_profile(node_id, profile, count=count)
            return True
        return False

    def evaluate_snapshot(
        self,
        snapshot: KPISnapshot,
        node_type: Optional[NodeType] = None,
    ) -> list[AnomalyEvent]:
        """Evaluate snapshot metrics against statistical baselines.

        Returns detected AnomalyEvent instances. Updates internal baselines only for non-anomalous samples.
        If either enabled detector flags a sample, the sample is excluded from both baselines.
        """
        if node_type is None:
            prefix = snapshot.node_id.split("-")[0].upper()
            if prefix == "CELL":
                node_type = NodeType.CELL
            elif prefix in ("SITE", "ENB", "GNB"):
                node_type = NodeType.SITE
            elif prefix == "AGG":
                node_type = NodeType.AGGREGATION
            elif prefix == "CORE":
                node_type = NodeType.CORE

        metrics = extract_snapshot_metrics(snapshot)
        anomalies: list[AnomalyEvent] = []

        for metric_name, val in metrics.items():
            key = (snapshot.node_id, metric_name)
            med_event: Optional[AnomalyEvent] = None
            ewma_event: Optional[AnomalyEvent] = None

            # 1. Evaluate Rolling Median against pre-observation state (read-only)
            if self._config.enable_rolling_median:
                med_event = self._eval_rolling_median(
                    snapshot.node_id, metric_name, snapshot.timestamp, val, node_type=node_type
                )

            # 2. Evaluate EWMA against pre-observation state (read-only)
            if self._config.enable_ewma:
                ewma_event = self._eval_ewma(
                    snapshot.node_id, metric_name, snapshot.timestamp, val, node_type=node_type
                )

            # 3. Contamination prevention & baseline healing:
            is_anomalous = (med_event is not None) or (ewma_event is not None)

            if is_anomalous:
                if med_event is not None:
                    anomalies.append(med_event)
                if ewma_event is not None:
                    anomalies.append(ewma_event)
            else:
                # Clean sample: update all enabled detector baselines
                if self._config.enable_rolling_median:
                    self._update_rolling_median(snapshot.node_id, metric_name, val)
                if self._config.enable_ewma:
                    self._update_ewma(snapshot.node_id, metric_name, val)

        return anomalies

    def _eval_rolling_median(
        self,
        node_id: str,
        metric_name: str,
        timestamp: datetime,
        val: float,
        node_type: Optional[NodeType] = None,
    ) -> Optional[AnomalyEvent]:
        key = (node_id, metric_name)
        history = self._median_histories.get(key)
        if history is None or len(history) < self._config.warmup_count:
            return None

        # Compute median of history
        hist_list = list(history)
        med = float(statistics.median(hist_list))

        # 1. Recovery from contaminated baseline:
        # If baseline learned severe outage/fault condition and current sample is healthy, do NOT flag.
        if is_baseline_degraded(metric_name, med, node_type) and is_metric_healthy(metric_name, val, node_type):
            return None

        # 2. Operational Directionality (unless two_sided mode is enabled):
        if self._config.directional_mode and not self._config.two_sided:
            # Strictly higher-is-better (availability, handover, RF signal): increases are improvements
            if metric_name in ("availability_pct", "handover_success_rate_pct", "sinr_db", "rsrp_dbm"):
                if val >= med:
                    return None
            # Lower-is-better (drop rate, latency): decreases are improvements
            elif metric_name in LOWER_IS_BETTER_KPIS:
                if val <= med:
                    return None
            # Throughput: drops are degradations. Moderate increases are normal traffic variation.
            # Extreme positive surges (>= baseline * surge_ratio_threshold) are flagged as surges!
            elif metric_name == "throughput_mbps":
                if val >= med and val < med * self._config.surge_ratio_threshold:
                    return None
            # PRB utilization: load increases or collapses are evaluated statistically without broad suppression

        # Compute Median Absolute Deviation (MAD)
        residuals = [abs(x - med) for x in hist_list]
        mad = float(statistics.median(residuals))

        # Normal-consistent scale: 1.4826 * MAD
        raw_scale = 1.4826 * mad
        deviation = abs(val - med)

        # Minimum scale floor (5% of median or 1.0) ensures constant baselines handle deviations gracefully.
        # Profile range spread (when available from profile seeding) ensures zero-variance seeded baselines
        # handle realistic operating deviations without artificial scale squeeze.
        min_scale = 0.05 * max(abs(med), 1.0)
        profile_spread = self._profile_spreads.get(key, 0.0)
        effective_scale = max(raw_scale, min_scale, profile_spread)
        score = deviation / effective_scale

        if score >= self._config.median_deviation_threshold:
            desc_prefix = "Rolling median positive surge anomaly" if (metric_name == "throughput_mbps" and val > med) else "Rolling median anomaly"
            return AnomalyEvent(
                node_id=node_id,
                metric_name=metric_name,
                timestamp=timestamp,
                source=DetectionSource.STATISTICAL_MEDIAN,
                rule_id=f"STAT-MEDIAN-{metric_name}",
                severity=self._config.severity,
                current_value=val,
                threshold=round(med, 4),
                description=(
                    f"{desc_prefix} on {metric_name}: observed {round(val, 2)} "
                    f"deviates {round(deviation, 2)} from median {round(med, 2)} "
                    f"(score {round(score, 4)} >= {self._config.median_deviation_threshold}, "
                    f"effective scale {round(effective_scale, 4)})"
                ),
                evidence={
                    "method": "rolling_median",
                    "median": round(med, 4),
                    "mad": round(mad, 4),
                    "raw_scale": round(raw_scale, 4),
                    "effective_scale": round(effective_scale, 4),
                    "scale": round(effective_scale, 4),
                    "min_scale_floor": round(min_scale, 4),
                    "deviation": round(deviation, 4),
                    "score": round(score, 4),
                    "threshold": self._config.median_deviation_threshold,
                    "window_samples": len(history),
                },
            )
        return None

    def _update_rolling_median(
        self,
        node_id: str,
        metric_name: str,
        val: float,
    ) -> None:
        key = (node_id, metric_name)
        history = self._median_histories.setdefault(key, deque(maxlen=self._config.window_size))
        history.append(val)

    def _eval_ewma(
        self,
        node_id: str,
        metric_name: str,
        timestamp: datetime,
        val: float,
        node_type: Optional[NodeType] = None,
    ) -> Optional[AnomalyEvent]:
        key = (node_id, metric_name)
        state = self._ewma_states.get(key)
        if state is None:
            return None

        count = int(state.get("count", 0))
        if count < self._config.warmup_count:
            return None

        prev_mean = state["mean"]
        prev_var = state["var"]

        # 1. Recovery from contaminated baseline
        if is_baseline_degraded(metric_name, prev_mean, node_type) and is_metric_healthy(metric_name, val, node_type):
            return None

        # 2. Operational Directionality
        if self._config.directional_mode and not self._config.two_sided:
            if metric_name in ("availability_pct", "handover_success_rate_pct", "sinr_db", "rsrp_dbm"):
                if val >= prev_mean:
                    return None
            elif metric_name in LOWER_IS_BETTER_KPIS:
                if val <= prev_mean:
                    return None
            elif metric_name == "throughput_mbps":
                if val >= prev_mean and val < prev_mean * self._config.surge_ratio_threshold:
                    return None

        diff = val - prev_mean
        raw_spread = math.sqrt(max(0.0, prev_var))

        min_spread = 0.05 * max(abs(prev_mean), 1.0)
        effective_spread = max(raw_spread, min_spread)
        score = abs(diff) / effective_spread

        if score >= self._config.ewma_sensitivity:
            desc_prefix = "EWMA positive surge anomaly" if (metric_name == "throughput_mbps" and val > prev_mean) else "EWMA deviation anomaly"
            return AnomalyEvent(
                node_id=node_id,
                metric_name=metric_name,
                timestamp=timestamp,
                source=DetectionSource.STATISTICAL_EWMA,
                rule_id=f"STAT-EWMA-{metric_name}",
                severity=self._config.severity,
                current_value=val,
                threshold=round(prev_mean, 4),
                description=(
                    f"{desc_prefix} on {metric_name}: observed {round(val, 2)} "
                    f"deviates {round(abs(diff), 2)} from baseline {round(prev_mean, 2)} "
                    f"(score {round(score, 4)} >= {self._config.ewma_sensitivity}, "
                    f"effective spread {round(effective_spread, 4)})"
                ),
                evidence={
                    "method": "ewma",
                    "ewma_mean": round(prev_mean, 4),
                    "raw_spread": round(raw_spread, 4),
                    "effective_spread": round(effective_spread, 4),
                    "ewma_spread": round(effective_spread, 4),
                    "min_spread_floor": round(min_spread, 4),
                    "diff": round(diff, 4),
                    "score": round(score, 4),
                    "sensitivity": self._config.ewma_sensitivity,
                    "sample_count": count,
                },
            )
        return None

    def _update_ewma(
        self,
        node_id: str,
        metric_name: str,
        val: float,
    ) -> None:
        key = (node_id, metric_name)
        state = self._ewma_states.get(key)
        if state is None:
            self._ewma_states[key] = {"mean": val, "var": 0.0, "count": 1.0}
            return

        count = int(state["count"])
        alpha = self._config.ewma_alpha
        prev_mean = state["mean"]
        prev_var = state["var"]
        diff = val - prev_mean

        new_mean = alpha * val + (1.0 - alpha) * prev_mean
        new_var = alpha * (diff ** 2) + (1.0 - alpha) * prev_var
        state["mean"] = new_mean
        state["var"] = new_var
        state["count"] = float(count + 1)

    def snapshot_state(self) -> tuple[
        dict[tuple[str, str], list[float]],
        dict[tuple[str, str], dict[str, float]],
        dict[tuple[str, str, DetectionSource], int],
    ]:
        """Snapshot internal detector baseline state and recovery counters for transactional rollback."""
        histories_copy = {k: list(v) for k, v in self._median_histories.items()}
        ewma_copy = {k: dict(v) for k, v in self._ewma_states.items()}
        rec_copy = dict(self._recovery_counters)
        return (histories_copy, ewma_copy, rec_copy)

    def restore_state(
        self,
        state: tuple[
            dict[tuple[str, str], list[float]],
            dict[tuple[str, str], dict[str, float]],
            dict[tuple[str, str, DetectionSource], int],
        ] | tuple[dict[tuple[str, str], list[float]], dict[tuple[str, str], dict[str, float]]],
    ) -> None:
        """Restore internal detector baseline state from a snapshot."""
        if len(state) == 3:
            histories_data, ewma_data, rec_data = state  # type: ignore[misc]
            self._recovery_counters = dict(rec_data)
        else:
            histories_data, ewma_data = state  # type: ignore[misc]
            self._recovery_counters.clear()

        self._median_histories = {
            k: deque(v, maxlen=self._config.window_size) for k, v in histories_data.items()
        }
        self._ewma_states = {k: dict(v) for k, v in ewma_data.items()}

    def check_recovery(
        self,
        snapshot: KPISnapshot,
        source: DetectionSource,
        metric_name: str,
        node_type: Optional[NodeType] = None,
    ) -> Optional[bool]:
        """Check whether the metric in snapshot has returned to normal deviation bounds.

        Requires consecutive normal observations matching config.consecutive_recovery_count.
        Returns True if recovered, False if still anomalous, or None if metric is not present.
        """
        metrics = extract_snapshot_metrics(snapshot)
        if metric_name not in metrics:
            return None

        if node_type is None:
            prefix = snapshot.node_id.split("-")[0].upper()
            if prefix == "CELL":
                node_type = NodeType.CELL
            elif prefix in ("SITE", "ENB", "GNB"):
                node_type = NodeType.SITE
            elif prefix == "AGG":
                node_type = NodeType.AGGREGATION
            elif prefix == "CORE":
                node_type = NodeType.CORE

        val = metrics[metric_name]
        key = (snapshot.node_id, metric_name)
        rec_key = (snapshot.node_id, metric_name, source)

        is_normal = False

        if source == DetectionSource.STATISTICAL_MEDIAN:
            history = self._median_histories.get(key)
            if not history or len(history) < self._config.warmup_count:
                is_normal = True
            else:
                hist_list = list(history)
                med = float(statistics.median(hist_list))
                residuals = [abs(x - med) for x in hist_list]
                mad = float(statistics.median(residuals))
                scale = 1.4826 * mad
                profile_spread = self._resolve_profile_spread(snapshot.node_id, metric_name, med, node_type)
                min_scale = max(profile_spread, 0.05 * max(abs(med), 1.0))
                effective_scale = max(scale, min_scale)
                deviation = abs(val - med)
                score = deviation / effective_scale
                recovery_thresh = self._config.median_deviation_threshold * self._config.recovery_hysteresis_factor

                # Case 1: Recovery from degraded/contaminated baseline
                if is_baseline_degraded(metric_name, med, node_type):
                    is_normal = is_metric_healthy(metric_name, val, node_type)
                # Case 2: Directional higher-is-better metrics (availability, handover, sinr, rsrp)
                elif self._config.directional_mode and not self._config.two_sided and metric_name in ("availability_pct", "handover_success_rate_pct", "sinr_db", "rsrp_dbm"):
                    is_normal = val >= med or score < recovery_thresh
                # Case 3: Throughput
                elif self._config.directional_mode and not self._config.two_sided and metric_name == "throughput_mbps":
                    is_normal = (val >= med and val <= med * self._config.surge_ratio_threshold) or score < recovery_thresh
                # Case 4: Lower-is-better metrics (latency, drop-rate)
                elif self._config.directional_mode and not self._config.two_sided and metric_name in LOWER_IS_BETTER_KPIS:
                    is_normal = val <= med or score < recovery_thresh or (is_metric_healthy(metric_name, val, node_type) and score < self._config.median_deviation_threshold)
                # Case 5: Other metrics / two-sided mode
                else:
                    is_normal = score < recovery_thresh

        elif source == DetectionSource.STATISTICAL_EWMA:
            state = self._ewma_states.get(key)
            if not state or int(state.get("count", 0)) < self._config.warmup_count:
                is_normal = True
            else:
                prev_mean = state["mean"]
                prev_var = state["var"]
                spread = math.sqrt(max(0.0, prev_var))
                profile_spread = self._resolve_profile_spread(snapshot.node_id, metric_name, prev_mean, node_type)
                min_spread = max(profile_spread, 0.05 * max(abs(prev_mean), 1.0))
                effective_spread = max(spread, min_spread)
                diff = abs(val - prev_mean)
                score = diff / effective_spread
                recovery_thresh = self._config.ewma_sensitivity * self._config.recovery_hysteresis_factor

                if is_baseline_degraded(metric_name, prev_mean, node_type):
                    is_normal = is_metric_healthy(metric_name, val, node_type)
                elif self._config.directional_mode and not self._config.two_sided and metric_name in ("availability_pct", "handover_success_rate_pct", "sinr_db", "rsrp_dbm"):
                    is_normal = val >= prev_mean or score < recovery_thresh
                elif self._config.directional_mode and not self._config.two_sided and metric_name == "throughput_mbps":
                    is_normal = (val >= prev_mean and val <= prev_mean * self._config.surge_ratio_threshold) or score < recovery_thresh
                elif self._config.directional_mode and not self._config.two_sided and metric_name in LOWER_IS_BETTER_KPIS:
                    is_normal = val <= prev_mean or score < recovery_thresh or (is_metric_healthy(metric_name, val, node_type) and score < self._config.ewma_sensitivity)
                else:
                    is_normal = score < recovery_thresh

        if is_normal:
            current_count = self._recovery_counters.get(rec_key, 0) + 1
            self._recovery_counters[rec_key] = current_count
            if current_count >= self._config.consecutive_recovery_count:
                self._recovery_counters.pop(rec_key, None)
                return True
            return False
        else:
            self._recovery_counters[rec_key] = 0
            return False
