"""Comprehensive unit and integration tests for NEXUS Alarm Correlation Subsystem."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import pytest

from nexus.correlation import (
    AlarmCorrelationEngine,
    CorrelationConfig,
    CorrelationError,
    CorrelationGroup,
    CorrelationResult,
    InvalidCorrelationConfigError,
    MalformedAlarmError,
)
from nexus.detection.models import Alarm, AlarmStatus, DetectionSource, Severity
from nexus.topology import NodeType, Topology, build_simulated_network


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def make_alarm(
    alarm_id: str,
    node_id: str,
    metric_name: str = "availability_pct",
    severity: Severity = Severity.CRITICAL,
    first_seen: Optional[datetime] = None,
    last_seen: Optional[datetime] = None,
    source: DetectionSource = DetectionSource.THRESHOLD,
    threshold: Optional[float] = 90.0,
    current_value: float = 0.0,
    rule_id: str = "rule-1",
) -> Alarm:
    """Helper to instantiate valid immutable Alarm instances for correlation testing."""
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    fs = first_seen or base_time
    ls = last_seen or fs
    return Alarm(
        alarm_id=alarm_id,
        node_id=node_id,
        rule_id=rule_id,
        metric_name=metric_name,
        source=source,
        severity=severity,
        current_value=current_value,
        threshold=threshold,
        first_seen=fs,
        last_seen=ls,
        observation_count=1,
        status=AlarmStatus.ACTIVE,
    )


# ---------------------------------------------------------------------------
# 1. Configuration Validation Tests
# ---------------------------------------------------------------------------

class TestCorrelationConfigValidation:
    """Test suite for CorrelationConfig validation and defaults."""

    def test_default_config(self) -> None:
        cfg = CorrelationConfig()
        assert cfg.time_window_seconds == 300.0
        assert cfg.max_ancestor_distance == 2
        assert cfg.group_singletons is True

    def test_custom_valid_config(self) -> None:
        cfg = CorrelationConfig(
            time_window_seconds=120.0,
            max_ancestor_distance=1,
            group_singletons=False,
        )
        assert cfg.time_window_seconds == 120.0
        assert cfg.max_ancestor_distance == 1
        assert cfg.group_singletons is False

    @pytest.mark.parametrize("invalid_window", [0.0, -10.0, float("nan"), float("inf"), "300", True, None])
    def test_invalid_time_window_raises(self, invalid_window: object) -> None:
        with pytest.raises(InvalidCorrelationConfigError):
            CorrelationConfig(time_window_seconds=invalid_window)  # type: ignore[arg-type]

    @pytest.mark.parametrize("invalid_dist", [0, -1, 1.5, "2", True, None])
    def test_invalid_max_ancestor_distance_raises(self, invalid_dist: object) -> None:
        with pytest.raises(InvalidCorrelationConfigError):
            CorrelationConfig(max_ancestor_distance=invalid_dist)  # type: ignore[arg-type]

    @pytest.mark.parametrize("invalid_singletons", ["True", 1, 0, None, []])
    def test_invalid_group_singletons_raises(self, invalid_singletons: object) -> None:
        with pytest.raises(InvalidCorrelationConfigError):
            CorrelationConfig(group_singletons=invalid_singletons)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Engine Initialization & Error Handling
# ---------------------------------------------------------------------------

class TestEngineInitialization:
    """Test suite for AlarmCorrelationEngine initialization."""

    def test_valid_init(self) -> None:
        topo = build_simulated_network()
        engine = AlarmCorrelationEngine(topology=topo)
        assert engine.topology is topo
        assert engine.config.time_window_seconds == 300.0

    def test_invalid_topology_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="Expected Topology instance"):
            AlarmCorrelationEngine(topology="not_a_topology")  # type: ignore[arg-type]

    def test_invalid_config_raises_type_error(self) -> None:
        topo = build_simulated_network()
        with pytest.raises(TypeError, match="Expected CorrelationConfig"):
            AlarmCorrelationEngine(topology=topo, config="invalid_config")  # type: ignore[arg-type]

    def test_correlate_non_alarm_raises_type_error(self) -> None:
        topo = build_simulated_network()
        engine = AlarmCorrelationEngine(topology=topo)
        with pytest.raises(TypeError, match="Expected Alarm instance"):
            engine.correlate(["not_an_alarm"])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# 3. Branch & Hierarchy Correlation Tests
# ---------------------------------------------------------------------------

class TestTopologyBranchCorrelation:
    """Test suite for topological grouping logic across hierarchy branches."""

    @pytest.fixture
    def network(self) -> Topology:
        return build_simulated_network()

    def test_same_site_cells_correlate_to_site(self, network: Topology) -> None:
        # CELL-01, CELL-02, CELL-03 belong to SITE-01
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-1", "CELL-01", "availability_pct", first_seen=base_time),
            make_alarm("alm-2", "CELL-02", "availability_pct", first_seen=base_time + timedelta(seconds=10)),
            make_alarm("alm-3", "CELL-03", "availability_pct", first_seen=base_time + timedelta(seconds=20)),
        ]
        engine = AlarmCorrelationEngine(topology=network)
        result = engine.correlate(alarms)

        assert result.total_alarms_processed == 3
        assert result.total_groups_formed == 1
        group = result.groups[0]
        assert group.anchor_node_id == "SITE-01"
        assert group.root_cause_tier == NodeType.SITE
        assert set(group.node_ids) == {"CELL-01", "CELL-02", "CELL-03"}
        assert len(group.alarms) == 3
        assert result.reduction_ratio == round((3 - 1) / 3, 4)

    def test_distant_ancestor_protection_rejects_core_merge(self, network: Topology) -> None:
        # CELL-01 (under SITE-01 -> AGG-01) and CELL-10 (under SITE-04 -> AGG-02)
        # Their LCA is CORE-01. Distant ancestor protection must prevent them from merging into core.
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-1", "CELL-01", "latency_ms", first_seen=base_time),
            make_alarm("alm-2", "CELL-10", "latency_ms", first_seen=base_time + timedelta(seconds=15)),
        ]
        engine = AlarmCorrelationEngine(topology=network)
        result = engine.correlate(alarms)

        # Distant ancestor protection should keep them in separate groups
        assert result.total_alarms_processed == 2
        assert result.total_groups_formed == 2
        group_anchors = {g.anchor_node_id for g in result.groups}
        assert "CORE-01" not in group_anchors

    def test_alarm_directly_on_core_can_merge_with_core_anchor(self, network: Topology) -> None:
        # An alarm directly on CORE-01 itself
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-core", "CORE-01", "throughput_mbps", first_seen=base_time),
            make_alarm("alm-agg", "AGG-01", "throughput_mbps", first_seen=base_time + timedelta(seconds=5)),
        ]
        engine = AlarmCorrelationEngine(topology=network)
        result = engine.correlate(alarms)

        assert result.total_groups_formed == 1
        group = result.groups[0]
        assert group.anchor_node_id == "CORE-01"
        assert group.root_cause_tier == NodeType.CORE

    def test_max_ancestor_distance_boundary(self, network: Topology) -> None:
        # CELL-01 (SITE-01) and CELL-04 (SITE-02) both sit under AGG-01.
        # Distance from cell to AGG-01 is 2 tiers (cell -> site -> agg).
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-1", "CELL-01", "throughput_mbps", first_seen=base_time),
            make_alarm("alm-2", "CELL-04", "throughput_mbps", first_seen=base_time + timedelta(seconds=10)),
        ]

        # With max_ancestor_distance=2, they can merge at AGG-01
        engine_dist2 = AlarmCorrelationEngine(topology=network, config=CorrelationConfig(max_ancestor_distance=2))
        res_dist2 = engine_dist2.correlate(alarms)
        assert res_dist2.total_groups_formed == 1
        assert res_dist2.groups[0].anchor_node_id == "AGG-01"

        # With max_ancestor_distance=1, distance 2 is forbidden, so they remain separate
        engine_dist1 = AlarmCorrelationEngine(topology=network, config=CorrelationConfig(max_ancestor_distance=1))
        res_dist1 = engine_dist1.correlate(alarms)
        assert res_dist1.total_groups_formed == 2


# ---------------------------------------------------------------------------
# 4. Temporal Clustering Tests
# ---------------------------------------------------------------------------

class TestTemporalClustering:
    """Test suite for time window correlation boundaries."""

    @pytest.fixture
    def network(self) -> Topology:
        return build_simulated_network()

    def test_alarms_within_time_window_merge(self, network: Topology) -> None:
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-1", "CELL-01", "availability_pct", first_seen=base_time),
            make_alarm("alm-2", "CELL-02", "availability_pct", first_seen=base_time + timedelta(seconds=299)),
        ]
        engine = AlarmCorrelationEngine(topology=network, config=CorrelationConfig(time_window_seconds=300.0))
        result = engine.correlate(alarms)
        assert result.total_groups_formed == 1

    def test_alarms_exceeding_time_window_do_not_merge(self, network: Topology) -> None:
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-1", "CELL-01", "availability_pct", first_seen=base_time),
            make_alarm("alm-2", "CELL-02", "availability_pct", first_seen=base_time + timedelta(seconds=301)),
        ]
        engine = AlarmCorrelationEngine(topology=network, config=CorrelationConfig(time_window_seconds=300.0))
        result = engine.correlate(alarms)
        assert result.total_groups_formed == 2


# ---------------------------------------------------------------------------
# 5. Symptom Compatibility Tests
# ---------------------------------------------------------------------------

class TestSymptomCompatibility:
    """Test suite for symptom compatibility checks preventing spurious merges."""

    @pytest.fixture
    def network(self) -> Topology:
        return build_simulated_network()

    def test_localized_interference_and_congestion_do_not_cross_merge(self, network: Topology) -> None:
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # CELL-01 has SINR degradation; CELL-02 has PRB spike
        alarms = [
            make_alarm("alm-rf", "CELL-01", "sinr_db", first_seen=base_time),
            make_alarm("alm-prb", "CELL-02", "prb_utilization_pct", first_seen=base_time + timedelta(seconds=5)),
        ]
        engine = AlarmCorrelationEngine(topology=network)
        result = engine.correlate(alarms)

        # Incompatible localized symptoms on different cells must remain separate
        assert result.total_groups_formed == 2
        assert result.singleton_groups_count == 2

    def test_same_cell_multiple_symptoms_merge(self, network: Topology) -> None:
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # Both alarms are on CELL-01
        alarms = [
            make_alarm("alm-rf", "CELL-01", "sinr_db", first_seen=base_time),
            make_alarm("alm-drop", "CELL-01", "connection_drop_rate_pct", first_seen=base_time + timedelta(seconds=5)),
        ]
        engine = AlarmCorrelationEngine(topology=network)
        result = engine.correlate(alarms)

        assert result.total_groups_formed == 1
        assert result.groups[0].anchor_node_id == "CELL-01"


# ---------------------------------------------------------------------------
# 6. Singleton Handling & Deduplication
# ---------------------------------------------------------------------------

class TestSingletonsAndDeduplication:
    """Test suite for singleton preservation and alarm deduplication."""

    @pytest.fixture
    def network(self) -> Topology:
        return build_simulated_network()

    def test_empty_alarms_returns_empty_result(self, network: Topology) -> None:
        engine = AlarmCorrelationEngine(topology=network)
        result = engine.correlate([])
        assert result.total_alarms_processed == 0
        assert result.total_groups_formed == 0
        assert result.singleton_groups_count == 0
        assert result.multi_alarm_groups_count == 0
        assert result.reduction_ratio == 0.0
        assert result.groups == ()

    def test_singleton_group_formation_when_enabled(self, network: Topology) -> None:
        engine = AlarmCorrelationEngine(topology=network, config=CorrelationConfig(group_singletons=True))
        alarm = make_alarm("alm-1", "CELL-01")
        result = engine.correlate([alarm])

        assert result.total_alarms_processed == 1
        assert result.total_groups_formed == 1
        assert result.singleton_groups_count == 1
        assert result.groups[0].is_singleton is True
        assert result.groups[0].alarm_count == 1
        assert result.reduction_ratio == 0.0

    def test_singleton_suppression_when_disabled(self, network: Topology) -> None:
        engine = AlarmCorrelationEngine(topology=network, config=CorrelationConfig(group_singletons=False))
        alarm = make_alarm("alm-1", "CELL-01")
        result = engine.correlate([alarm])

        assert result.total_alarms_processed == 1
        assert result.total_groups_formed == 0
        assert result.groups == ()

    def test_duplicate_alarm_ids_deduplicated(self, network: Topology) -> None:
        engine = AlarmCorrelationEngine(topology=network)
        alarm1 = make_alarm("alm-1", "CELL-01", "availability_pct")
        alarm2 = make_alarm("alm-1", "CELL-01", "availability_pct")  # duplicate ID
        result = engine.correlate([alarm1, alarm2])

        assert result.total_alarms_processed == 1
        assert result.total_groups_formed == 1


# ---------------------------------------------------------------------------
# 7. Determinism and Immutability Tests
# ---------------------------------------------------------------------------

class TestDeterminismAndImmutability:
    """Test suite verifying output immutability and order invariance."""

    @pytest.fixture
    def network(self) -> Topology:
        return build_simulated_network()

    def test_order_invariance(self, network: Topology) -> None:
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        a1 = make_alarm("alm-1", "CELL-01", first_seen=base_time)
        a2 = make_alarm("alm-2", "CELL-02", first_seen=base_time + timedelta(seconds=10))
        a3 = make_alarm("alm-3", "CELL-04", first_seen=base_time + timedelta(seconds=20))

        engine = AlarmCorrelationEngine(topology=network)
        res1 = engine.correlate([a1, a2, a3])
        res2 = engine.correlate([a3, a1, a2])

        assert res1.total_groups_formed == res2.total_groups_formed
        assert [g.group_id for g in res1.groups] == [g.group_id for g in res2.groups]
        assert [g.alarm_ids for g in res1.groups] == [g.alarm_ids for g in res2.groups]

    def test_immutability(self, network: Topology) -> None:
        engine = AlarmCorrelationEngine(topology=network)
        alarm = make_alarm("alm-1", "CELL-01")
        result = engine.correlate([alarm])
        group = result.groups[0]

        with pytest.raises(AttributeError):
            group.group_id = "new_id"  # type: ignore[misc]

        with pytest.raises(TypeError):
            group.evidence["new_key"] = "val"  # type: ignore[index]


# ---------------------------------------------------------------------------
# 8. Ground-Truth Isolation Verification
# ---------------------------------------------------------------------------

class TestGroundTruthIsolation:
    """Verify that nexus.correlation does not import or depend on nexus.fault."""

    def test_zero_imports_from_fault(self) -> None:
        correlation_dir = Path(__file__).resolve().parent.parent / "src" / "nexus" / "correlation"
        for py_file in correlation_dir.glob("*.py"):
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "nexus.fault" not in alias.name, f"Forbidden import in {py_file}: {alias.name}"
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    assert "nexus.fault" not in mod, f"Forbidden import in {py_file}: {mod}"


# ---------------------------------------------------------------------------
# 9. Time-Window Chaining Prevention Tests
# ---------------------------------------------------------------------------

class TestTimeWindowChainingPrevention:
    """Test suite verifying that transitive time-window chaining does not exceed max span."""

    def test_pairwise_within_window_transitive_exceeds_creates_two_groups(self) -> None:
        """Verify that three alarms where A-B <= window and B-C <= window but A-C > window
        are split into two groups and never chained across the full span."""
        topo = build_simulated_network()
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        engine = AlarmCorrelationEngine(
            topology=topo,
            config=CorrelationConfig(time_window_seconds=300.0),
        )

        # Alarm A at 0s, Alarm B at 200s, Alarm C at 400s
        a1 = make_alarm("alm-a", "CELL-01", "latency_ms", current_value=100.0, first_seen=base_time)
        a2 = make_alarm("alm-b", "CELL-01", "latency_ms", current_value=110.0, first_seen=base_time + timedelta(seconds=200))
        a3 = make_alarm("alm-c", "CELL-01", "latency_ms", current_value=120.0, first_seen=base_time + timedelta(seconds=400))

        result = engine.correlate([a1, a2, a3])
        assert result.total_alarms_processed == 3
        assert result.total_groups_formed == 2

        # Group 1 contains A and B; Group 2 contains C
        g1, g2 = result.groups
        assert g1.alarm_ids == ("alm-a", "alm-b")
        assert g2.alarm_ids == ("alm-c",)

        # Verify time-span invariant holds for both groups
        span1 = (g1.time_window_end - g1.time_window_start).total_seconds()
        span2 = (g2.time_window_end - g2.time_window_start).total_seconds()
        assert span1 <= 300.0
        assert span2 <= 300.0

