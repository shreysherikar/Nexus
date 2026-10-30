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
    """

    window_size: int = 20
    warmup_count: int = 5
    median_deviation_threshold: float = 3.0
    ewma_alpha: float = 0.2
    ewma_sensitivity: float = 3.0
    severity: Severity = Severity.MAJOR
    enable_rolling_median: bool = True
    enable_ewma: bool = True

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


class StatisticalDetector:
    """Maintains independent time-series baselines per (node, metric) and flags anomalies.

    Methods:
    - Rolling Median: Uses Median Absolute Deviation (MAD) scaled by 1.4826 for normal consistency.
    - EWMA: Exponentially Weighted Moving Average with recursive variance tracking.

    Contamination Prevention:
    When an observation is flagged as an anomaly, it is excluded from baseline history updates to prevent
    severe faults from distorting future expected baselines.
    """

    def __init__(self, config: Optional[StatisticalDetectorConfig] = None) -> None:
        self._config = config if config is not None else StatisticalDetectorConfig()

        # State mapping: (node_id, metric_name) -> deque of floats (bounded by window_size)
        self._median_histories: dict[tuple[str, str], deque[float]] = {}

        # State mapping: (node_id, metric_name) -> {"mean": float, "var": float, "count": int}
        self._ewma_states: dict[tuple[str, str], dict[str, float]] = {}

    @property
    def config(self) -> StatisticalDetectorConfig:
        return self._config

    def reset(self) -> None:
        """Clear all internal history and baseline states."""
        self._median_histories.clear()
        self._ewma_states.clear()

    def reset_node(self, node_id: str) -> None:
        """Clear internal states for a specific node."""
        med_keys = [k for k in self._median_histories if k[0] == node_id]
        for k in med_keys:
            del self._median_histories[k]

        ewma_keys = [k for k in self._ewma_states if k[0] == node_id]
        for k in ewma_keys:
            del self._ewma_states[k]

    def evaluate_snapshot(self, snapshot: KPISnapshot) -> list[AnomalyEvent]:
        """Evaluate snapshot metrics against statistical baselines.

        Returns detected AnomalyEvent instances. Updates internal baselines only for non-anomalous samples.
        If either enabled detector flags a sample, the sample is excluded from both baselines.
        """
        metrics = extract_snapshot_metrics(snapshot)
        anomalies: list[AnomalyEvent] = []

        for metric_name, val in metrics.items():
            key = (snapshot.node_id, metric_name)
            med_event: Optional[AnomalyEvent] = None
            ewma_event: Optional[AnomalyEvent] = None

            # 1. Evaluate Rolling Median against pre-observation state (read-only)
            if self._config.enable_rolling_median:
                med_event = self._eval_rolling_median(snapshot.node_id, metric_name, snapshot.timestamp, val)

            # 2. Evaluate EWMA against pre-observation state (read-only)
            if self._config.enable_ewma:
                ewma_event = self._eval_ewma(snapshot.node_id, metric_name, snapshot.timestamp, val)

            # 3. Contamination prevention: if either flags an anomaly, exclude from BOTH updates
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
    ) -> Optional[AnomalyEvent]:
        key = (node_id, metric_name)
        history = self._median_histories.get(key)
        if history is None or len(history) < self._config.warmup_count:
            return None

        # Compute median of history
        hist_list = list(history)
        med = float(statistics.median(hist_list))

        # Compute Median Absolute Deviation (MAD)
        residuals = [abs(x - med) for x in hist_list]
        mad = float(statistics.median(residuals))

        # Normal-consistent scale: 1.4826 * MAD
        raw_scale = 1.4826 * mad
        deviation = abs(val - med)

        # Minimum scale floor (5% of median or 1.0) ensures constant baselines handle deviations gracefully
        min_scale = 0.05 * max(abs(med), 1.0)
        effective_scale = max(raw_scale, min_scale)
        score = deviation / effective_scale

        if score >= self._config.median_deviation_threshold:
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
                    f"Rolling median anomaly on {metric_name}: observed {round(val, 2)} "
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

        diff = val - prev_mean
        raw_spread = math.sqrt(max(0.0, prev_var))

        min_spread = 0.05 * max(abs(prev_mean), 1.0)
        effective_spread = max(raw_spread, min_spread)
        score = abs(diff) / effective_spread

        if score >= self._config.ewma_sensitivity:
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
                    f"EWMA deviation anomaly on {metric_name}: observed {round(val, 2)} "
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

    def snapshot_state(self) -> tuple[dict[tuple[str, str], list[float]], dict[tuple[str, str], dict[str, float]]]:
        """Snapshot internal detector baseline state for transactional rollback."""
        histories_copy = {k: list(v) for k, v in self._median_histories.items()}
        ewma_copy = {k: dict(v) for k, v in self._ewma_states.items()}
        return (histories_copy, ewma_copy)

    def restore_state(
        self,
        state: tuple[dict[tuple[str, str], list[float]], dict[tuple[str, str], dict[str, float]]],
    ) -> None:
        """Restore internal detector baseline state from a snapshot."""
        histories_data, ewma_data = state
        self._median_histories = {
            k: deque(v, maxlen=self._config.window_size) for k, v in histories_data.items()
        }
        self._ewma_states = {k: dict(v) for k, v in ewma_data.items()}

    def check_recovery(
        self,
        snapshot: KPISnapshot,
        source: DetectionSource,
        metric_name: str,
    ) -> Optional[bool]:
        """Check whether the metric in snapshot has returned to normal deviation bounds.

        Returns True if recovered, False if still anomalous, or None if metric is not present.
        """
        metrics = extract_snapshot_metrics(snapshot)
        if metric_name not in metrics:
            return None

        val = metrics[metric_name]
        key = (snapshot.node_id, metric_name)

        if source == DetectionSource.STATISTICAL_MEDIAN:
            history = self._median_histories.get(key)
            if not history or len(history) < self._config.warmup_count:
                return True
            hist_list = list(history)
            med = float(statistics.median(hist_list))
            residuals = [abs(x - med) for x in hist_list]
            mad = float(statistics.median(residuals))
            scale = 1.4826 * mad
            min_scale = 0.05 * max(abs(med), 1.0)
            effective_scale = max(scale, min_scale)
            deviation = abs(val - med)
            score = deviation / effective_scale
            return score < self._config.median_deviation_threshold

        elif source == DetectionSource.STATISTICAL_EWMA:
            state = self._ewma_states.get(key)
            if not state or int(state["count"]) < self._config.warmup_count:
                return True
            prev_mean = state["mean"]
            prev_var = state["var"]
            spread = math.sqrt(max(0.0, prev_var))
            min_spread = 0.05 * max(abs(prev_mean), 1.0)
            effective_spread = max(spread, min_spread)
            diff = abs(val - prev_mean)
            score = diff / effective_spread
            return score < self._config.ewma_sensitivity

        return None
