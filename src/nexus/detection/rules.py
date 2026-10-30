"""Configurable threshold rules and default telecom rule definitions."""

from dataclasses import dataclass
import math
from typing import Any, Iterable, Optional

from nexus.detection.exceptions import InvalidRuleError
from nexus.detection.models import ComparisonOperator, Severity
from nexus.topology.enums import NodeType

SUPPORTED_METRICS: frozenset[str] = frozenset({
    "throughput_mbps",
    "latency_ms",
    "connection_drop_rate_pct",
    "availability_pct",
    "handover_success_rate_pct",
    "rsrp_dbm",
    "sinr_db",
    "prb_utilization_pct",
})

RADIO_METRICS: frozenset[str] = frozenset({
    "rsrp_dbm",
    "sinr_db",
    "prb_utilization_pct",
    "handover_success_rate_pct",
})


def _validate_numeric(name: str, val: Any) -> float:
    """Validate that val is a finite real number, rejecting booleans, NaN, and inf."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise InvalidRuleError(f"{name} must be a numeric value, got {type(val).__name__}")
    f_val = float(val)
    if not math.isfinite(f_val):
        raise InvalidRuleError(f"{name} must be a finite number, got {f_val}")
    return f_val


@dataclass(frozen=True)
class ThresholdRule:
    """Configurable rule specifying an operational threshold condition.

    Attributes:
        rule_id: Unique string identifier for the rule.
        metric_name: Target KPI metric name.
        operator: Relational comparison operator (GT, GTE, LT, LTE).
        threshold: Boundary value triggering an anomaly.
        severity: Alarm severity classification (WARNING, MAJOR, CRITICAL).
        node_types: Optional subset of NodeTypes this rule applies to (None = all applicable).
        clear_threshold: Optional recovery threshold enforcing hysteresis.
        enabled: Whether the rule is actively evaluated.
        description: Human-readable diagnostic description.
    """

    rule_id: str
    metric_name: str
    operator: ComparisonOperator
    threshold: float
    severity: Severity
    node_types: Optional[frozenset[NodeType]] = None
    clear_threshold: Optional[float] = None
    enabled: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not self.rule_id.strip():
            raise InvalidRuleError("rule_id must be a non-empty string")

        if not isinstance(self.metric_name, str) or self.metric_name not in SUPPORTED_METRICS:
            raise InvalidRuleError(
                f"Invalid metric_name '{self.metric_name}'. Supported metrics: {', '.join(sorted(SUPPORTED_METRICS))}"
            )

        if not isinstance(self.operator, ComparisonOperator):
            try:
                object.__setattr__(self, "operator", ComparisonOperator(self.operator))
            except (ValueError, TypeError) as exc:
                raise InvalidRuleError(f"Invalid operator '{self.operator}'") from exc

        t_val = _validate_numeric("threshold", self.threshold)
        object.__setattr__(self, "threshold", t_val)

        if not isinstance(self.severity, Severity):
            try:
                object.__setattr__(self, "severity", Severity(self.severity))
            except (ValueError, TypeError) as exc:
                raise InvalidRuleError(f"Invalid severity '{self.severity}'") from exc

        if self.node_types is not None:
            if not isinstance(self.node_types, (frozenset, set, list, tuple)):
                raise InvalidRuleError(f"node_types must be a collection of NodeType, got {type(self.node_types).__name__}")
            validated_types: set[NodeType] = set()
            for nt in self.node_types:
                if not isinstance(nt, NodeType):
                    try:
                        validated_types.add(NodeType(nt))
                    except (ValueError, TypeError) as exc:
                        raise InvalidRuleError(f"Invalid NodeType '{nt}' in rule node_types") from exc
                else:
                    validated_types.add(nt)
            object.__setattr__(self, "node_types", frozenset(validated_types))

        if self.clear_threshold is not None:
            c_val = _validate_numeric("clear_threshold", self.clear_threshold)
            object.__setattr__(self, "clear_threshold", c_val)

            # Hysteresis validation:
            # For upper bounds (GT, GTE), trigger is value > threshold. Recovery must happen when value <= clear_threshold.
            # Thus clear_threshold must be <= threshold to prevent inverted / impossible hysteresis.
            if self.operator in (ComparisonOperator.GT, ComparisonOperator.GTE):
                if c_val > t_val:
                    raise InvalidRuleError(
                        f"For operator {self.operator.value}, clear_threshold ({c_val}) must be <= threshold ({t_val})"
                    )
            # For lower bounds (LT, LTE), trigger is value < threshold. Recovery must happen when value >= clear_threshold.
            # Thus clear_threshold must be >= threshold.
            elif self.operator in (ComparisonOperator.LT, ComparisonOperator.LTE):
                if c_val < t_val:
                    raise InvalidRuleError(
                        f"For operator {self.operator.value}, clear_threshold ({c_val}) must be >= threshold ({t_val})"
                    )

        if not isinstance(self.enabled, bool):
            raise InvalidRuleError(f"enabled must be a boolean, got {type(self.enabled).__name__}")

        if not isinstance(self.description, str):
            raise InvalidRuleError(f"description must be a string, got {type(self.description).__name__}")

    def applies_to_node_type(self, node_type: Optional[NodeType]) -> bool:
        """Check if this rule applies to the specified node type."""
        if not self.enabled:
            return False
        if self.node_types is None:
            return True
        if node_type is None:
            return True
        return node_type in self.node_types

    def evaluate(self, value: float) -> bool:
        """Check whether the given metric value triggers an anomaly violation."""
        if not self.enabled:
            return False
        f_val = float(value)
        if self.operator == ComparisonOperator.GT:
            return f_val > self.threshold
        elif self.operator == ComparisonOperator.GTE:
            return f_val >= self.threshold
        elif self.operator == ComparisonOperator.LT:
            return f_val < self.threshold
        elif self.operator == ComparisonOperator.LTE:
            return f_val <= self.threshold
        return False

    def is_cleared(self, value: float) -> bool:
        """Check whether the given metric value satisfies the recovery condition."""
        f_val = float(value)
        # If clear_threshold is explicitly defined, use hysteresis boundary
        if self.clear_threshold is not None:
            if self.operator in (ComparisonOperator.GT, ComparisonOperator.GTE):
                return f_val <= self.clear_threshold
            else:
                return f_val >= self.clear_threshold

        # Default recovery is the inverse of the trigger condition
        if self.operator == ComparisonOperator.GT:
            return f_val <= self.threshold
        elif self.operator == ComparisonOperator.GTE:
            return f_val < self.threshold
        elif self.operator == ComparisonOperator.LT:
            return f_val >= self.threshold
        elif self.operator == ComparisonOperator.LTE:
            return f_val > self.threshold
        return False


def get_default_rules() -> list[ThresholdRule]:
    """Factory creating a standard baseline suite of telecom threshold detection rules."""
    return [
        ThresholdRule(
            rule_id="RULE-AVAIL-CRIT",
            metric_name="availability_pct",
            operator=ComparisonOperator.LT,
            threshold=95.0,
            severity=Severity.CRITICAL,
            clear_threshold=98.0,
            description="Service availability dropped below critical threshold (95.0%)",
        ),
        ThresholdRule(
            rule_id="RULE-DROP-CRIT",
            metric_name="connection_drop_rate_pct",
            operator=ComparisonOperator.GT,
            threshold=5.0,
            severity=Severity.CRITICAL,
            clear_threshold=2.0,
            description="Call/session drop rate spiked above critical threshold (5.0%)",
        ),
        ThresholdRule(
            rule_id="RULE-LAT-MAJOR",
            metric_name="latency_ms",
            operator=ComparisonOperator.GT,
            threshold=80.0,
            severity=Severity.MAJOR,
            clear_threshold=60.0,
            description="Round-trip latency exceeded major threshold (80.0 ms)",
        ),
        ThresholdRule(
            rule_id="RULE-PRB-MAJOR",
            metric_name="prb_utilization_pct",
            operator=ComparisonOperator.GT,
            threshold=85.0,
            severity=Severity.MAJOR,
            clear_threshold=75.0,
            node_types=frozenset({NodeType.CELL}),
            description="Cell PRB utilization saturated above major threshold (85.0%)",
        ),
        ThresholdRule(
            rule_id="RULE-SINR-MAJOR",
            metric_name="sinr_db",
            operator=ComparisonOperator.LT,
            threshold=5.0,
            severity=Severity.MAJOR,
            clear_threshold=8.0,
            node_types=frozenset({NodeType.CELL}),
            description="Radio Signal-to-Interference-plus-Noise ratio degraded below 5.0 dB",
        ),
        ThresholdRule(
            rule_id="RULE-RSRP-WARN",
            metric_name="rsrp_dbm",
            operator=ComparisonOperator.LT,
            threshold=-115.0,
            severity=Severity.WARNING,
            clear_threshold=-110.0,
            node_types=frozenset({NodeType.CELL}),
            description="Radio signal received power degraded below warning threshold (-115.0 dBm)",
        ),
        ThresholdRule(
            rule_id="RULE-TP-WARN",
            metric_name="throughput_mbps",
            operator=ComparisonOperator.LT,
            threshold=5.0,
            severity=Severity.WARNING,
            clear_threshold=10.0,
            node_types=frozenset({NodeType.CELL}),
            description="Cell throughput degraded below warning threshold (5.0 Mbps)",
        ),
        ThresholdRule(
            rule_id="RULE-HOSR-MAJOR",
            metric_name="handover_success_rate_pct",
            operator=ComparisonOperator.LT,
            threshold=90.0,
            severity=Severity.MAJOR,
            clear_threshold=95.0,
            node_types=frozenset({NodeType.CELL}),
            description="Handover success rate dropped below major threshold (90.0%)",
        ),
    ]
