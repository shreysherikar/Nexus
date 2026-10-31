"""Comprehensive unit and integration tests for NEXUS Root Cause Analysis (RCA) Subsystem."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import pytest

from nexus.correlation import AlarmCorrelationEngine, CorrelationConfig, CorrelationGroup
from nexus.detection.models import Alarm, AlarmStatus, DetectionSource, Severity
from nexus.rca import (
    EvidenceItem,
    InsufficientTelemetryError,
    InvalidRCAConfigError,
    RCAConfig,
    RCAError,
    RCAResult,
    RootCauseAnalysisEngine,
    RootCauseHypothesis,
    RootCauseType,
    TargetType,
)
from nexus.telemetry import (
    KPISnapshot,
    PerformanceMetrics,
    RadioMetrics,
    ReliabilityMetrics,
)
from nexus.topology import NodeType, Topology, build_simulated_network
from nexus.transport import TransportNetwork, build_reference_transport_network


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
    """Helper to instantiate valid immutable Alarm instances for RCA testing."""
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


def make_cell_snapshot(
    node_id: str = "CELL-01",
    timestamp: Optional[datetime] = None,
    throughput_mbps: float = 100.0,
    latency_ms: float = 20.0,
    connection_drop_rate_pct: float = 0.5,
    availability_pct: float = 99.9,
    handover_success_rate_pct: float = 99.0,
    rsrp_dbm: float = -85.0,
    sinr_db: float = 18.0,
    prb_utilization_pct: float = 45.0,
) -> KPISnapshot:
    """Helper creating a valid cell snapshot with customizable KPI values."""
    ts = timestamp or datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return KPISnapshot(
        node_id=node_id,
        timestamp=ts,
        performance=PerformanceMetrics(
            throughput_mbps=throughput_mbps,
            latency_ms=latency_ms,
        ),
        reliability=ReliabilityMetrics(
            connection_drop_rate_pct=connection_drop_rate_pct,
            availability_pct=availability_pct,
            handover_success_rate_pct=handover_success_rate_pct,
        ),
        radio=RadioMetrics(
            rsrp_dbm=rsrp_dbm,
            sinr_db=sinr_db,
            prb_utilization_pct=prb_utilization_pct,
        ),
    )


# ---------------------------------------------------------------------------
# 1. Configuration Validation Tests
# ---------------------------------------------------------------------------

class TestRCAConfigValidation:
    """Test suite for RCAConfig parameter validation."""

    def test_default_config(self) -> None:
        cfg = RCAConfig()
        assert cfg.min_confidence_threshold == 0.35
        assert cfg.max_hypotheses_per_group == 5

    def test_custom_valid_config(self) -> None:
        cfg = RCAConfig(min_confidence_threshold=0.5, max_hypotheses_per_group=3)
        assert cfg.min_confidence_threshold == 0.5
        assert cfg.max_hypotheses_per_group == 3

    @pytest.mark.parametrize("invalid_thresh", [-0.1, 1.1, float("nan"), float("inf"), "0.35", True, None])
    def test_invalid_confidence_threshold_raises(self, invalid_thresh: object) -> None:
        with pytest.raises(InvalidRCAConfigError):
            RCAConfig(min_confidence_threshold=invalid_thresh)  # type: ignore[arg-type]

    @pytest.mark.parametrize("invalid_max", [0, -1, 1.5, "5", True, None])
    def test_invalid_max_hypotheses_raises(self, invalid_max: object) -> None:
        with pytest.raises(InvalidRCAConfigError):
            RCAConfig(max_hypotheses_per_group=invalid_max)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Engine Initialization & Error Handling
# ---------------------------------------------------------------------------

class TestRCAEngineInitialization:
    """Test suite for RootCauseAnalysisEngine initialization and parameter handling."""

    def test_valid_init(self) -> None:
        topo = build_simulated_network()
        trans = build_reference_transport_network(topo)
        engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        assert engine.topology is topo
        assert engine.transport is trans
        assert engine.config.min_confidence_threshold == 0.35

    def test_invalid_topology_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="Expected Topology instance"):
            RootCauseAnalysisEngine(topology="not_a_topology")  # type: ignore[arg-type]

    def test_invalid_transport_raises_type_error(self) -> None:
        topo = build_simulated_network()
        with pytest.raises(TypeError, match="Expected TransportNetwork instance"):
            RootCauseAnalysisEngine(topology=topo, transport="not_a_transport")  # type: ignore[arg-type]

    def test_invalid_config_raises_type_error(self) -> None:
        topo = build_simulated_network()
        with pytest.raises(TypeError, match="Expected RCAConfig instance"):
            RootCauseAnalysisEngine(topology=topo, config="invalid_config")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. Diagnostic Rules & Root Cause Pattern Tests
# ---------------------------------------------------------------------------

class TestDiagnosticPatterns:
    """Test suite covering the 5 canonical fault diagnostic patterns."""

    @pytest.fixture
    def setup_network(self) -> tuple[Topology, TransportNetwork]:
        topo = build_simulated_network()
        trans = build_reference_transport_network(topo)
        return topo, trans

    def test_backhaul_failure_pattern(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Multi-cell latency and throughput alarms under SITE-01
        alarms = [
            make_alarm("alm-1", "CELL-01", "latency_ms", current_value=120.0, threshold=50.0, first_seen=base_time),
            make_alarm("alm-2", "CELL-01", "throughput_mbps", current_value=10.0, threshold=50.0, first_seen=base_time),
            make_alarm("alm-3", "CELL-02", "latency_ms", current_value=140.0, threshold=50.0, first_seen=base_time),
            make_alarm("alm-4", "CELL-03", "throughput_mbps", current_value=8.0, threshold=50.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        assert corr_result.total_groups_formed == 1
        group = corr_result.groups[0]

        snapshots = [
            make_cell_snapshot("CELL-01", latency_ms=120.0, throughput_mbps=10.0),
            make_cell_snapshot("CELL-02", latency_ms=140.0, throughput_mbps=12.0),
            make_cell_snapshot("CELL-03", latency_ms=135.0, throughput_mbps=8.0),
        ]

        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        result = rca_engine.analyze_group(group, telemetry_snapshots=snapshots)

        assert result.primary_hypothesis is not None
        primary = result.primary_hypothesis
        assert primary.cause_type == RootCauseType.BACKHAUL_FAILURE
        assert primary.target_type == TargetType.TRANSPORT_LINK
        assert primary.confidence_score >= 0.70
        assert "optical" in result.recommended_action.lower() or "transport" in result.recommended_action.lower()

    def test_site_power_failure_pattern(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # All 3 cells under SITE-01 experience 0% availability simultaneously
        alarms = [
            make_alarm("alm-1", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time),
            make_alarm("alm-2", "CELL-02", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time),
            make_alarm("alm-3", "CELL-03", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        assert corr_result.total_groups_formed == 1
        group = corr_result.groups[0]

        snapshots = [
            make_cell_snapshot("CELL-01", availability_pct=0.0),
            make_cell_snapshot("CELL-02", availability_pct=0.0),
            make_cell_snapshot("CELL-03", availability_pct=0.0),
        ]

        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        result = rca_engine.analyze_group(group, telemetry_snapshots=snapshots)

        assert result.primary_hypothesis is not None
        primary = result.primary_hypothesis
        assert primary.cause_type == RootCauseType.SITE_POWER_FAILURE
        assert primary.target_id == "SITE-01"
        assert primary.target_type == TargetType.NODE
        assert primary.confidence_score >= 0.80
        assert "power" in result.recommended_action.lower() or "battery" in result.recommended_action.lower()

    def test_radio_interference_pattern(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Single cell RF degradation on CELL-01
        alarms = [
            make_alarm("alm-rf", "CELL-01", "sinr_db", current_value=-5.0, threshold=0.0, first_seen=base_time),
            make_alarm("alm-drop", "CELL-01", "connection_drop_rate_pct", current_value=8.0, threshold=2.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        assert corr_result.total_groups_formed == 1
        group = corr_result.groups[0]

        # Sibling cells CELL-02 and CELL-03 are completely healthy
        snapshots = [
            make_cell_snapshot("CELL-01", sinr_db=-5.0, connection_drop_rate_pct=8.0),
            make_cell_snapshot("CELL-02", sinr_db=18.0, connection_drop_rate_pct=0.2),
            make_cell_snapshot("CELL-03", sinr_db=19.0, connection_drop_rate_pct=0.3),
        ]

        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        result = rca_engine.analyze_group(group, telemetry_snapshots=snapshots)

        assert result.primary_hypothesis is not None
        primary = result.primary_hypothesis
        assert primary.cause_type == RootCauseType.RADIO_INTERFERENCE
        assert primary.target_id == "CELL-01"
        assert primary.target_type == TargetType.NODE
        assert primary.confidence_score >= 0.70
        assert "spectrum" in result.recommended_action.lower() or "rf" in result.recommended_action.lower()

    def test_cell_congestion_pattern(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Heavy PRB utilization spike on CELL-01
        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=96.0, threshold=85.0, first_seen=base_time),
            make_alarm("alm-tp", "CELL-01", "throughput_mbps", current_value=15.0, threshold=40.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        assert corr_result.total_groups_formed == 1
        group = corr_result.groups[0]

        # Radio metrics are healthy (no interference)
        snapshots = [
            make_cell_snapshot("CELL-01", prb_utilization_pct=96.0, throughput_mbps=15.0, sinr_db=18.0),
            make_cell_snapshot("CELL-02", prb_utilization_pct=40.0, throughput_mbps=90.0, sinr_db=19.0),
        ]

        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        result = rca_engine.analyze_group(group, telemetry_snapshots=snapshots)

        assert result.primary_hypothesis is not None
        primary = result.primary_hypothesis
        assert primary.cause_type == RootCauseType.CELL_CONGESTION
        assert primary.target_id == "CELL-01"
        assert primary.target_type == TargetType.NODE
        assert primary.confidence_score >= 0.70
        assert "congestion" in result.recommended_action.lower() or "offload" in result.recommended_action.lower()

    def test_cell_outage_pattern(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Isolated total availability collapse on CELL-01
        alarms = [
            make_alarm("alm-avail", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        assert corr_result.total_groups_formed == 1
        group = corr_result.groups[0]

        # Sibling cells CELL-02 and CELL-03 are healthy
        snapshots = [
            make_cell_snapshot("CELL-01", availability_pct=0.0),
            make_cell_snapshot("CELL-02", availability_pct=99.9),
            make_cell_snapshot("CELL-03", availability_pct=99.8),
        ]

        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        result = rca_engine.analyze_group(group, telemetry_snapshots=snapshots)

        assert result.primary_hypothesis is not None
        primary = result.primary_hypothesis
        assert primary.cause_type == RootCauseType.CELL_OUTAGE
        assert primary.target_id == "CELL-01"
        assert primary.target_type == TargetType.NODE
        assert primary.confidence_score >= 0.70
        assert "radio unit" in result.recommended_action.lower() or "feeder" in result.recommended_action.lower()


# ---------------------------------------------------------------------------
# 4. Ambiguity, UNKNOWN Fallback, and Action Guidance
# ---------------------------------------------------------------------------

class TestAmbiguityAndFallback:
    """Test suite for insufficient evidence handling and UNKNOWN fallback."""

    @pytest.fixture
    def setup_network(self) -> tuple[Topology, TransportNetwork]:
        topo = build_simulated_network()
        trans = build_reference_transport_network(topo)
        return topo, trans

    def test_low_confidence_produces_unknown_hypothesis(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # An isolated, non-standard metric alarm with ambiguous symptoms
        alarms = [
            make_alarm("alm-misc", "CELL-01", "unknown_metric", current_value=5.0, threshold=4.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        group = corr_result.groups[0]

        rca_engine = RootCauseAnalysisEngine(
            topology=topo,
            transport=trans,
            config=RCAConfig(min_confidence_threshold=0.5),
        )
        result = rca_engine.analyze_group(group)

        assert result.primary_hypothesis is not None
        assert result.primary_hypothesis.cause_type == RootCauseType.UNKNOWN
        assert result.primary_hypothesis.target_type == TargetType.UNKNOWN
        assert "triage" in result.recommended_action.lower()

    def test_analyze_results_batch_coordinator(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        alarms = [
            make_alarm("alm-1", "CELL-01", "availability_pct", current_value=0.0, first_seen=base_time),
            make_alarm("alm-2", "CELL-10", "availability_pct", current_value=0.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        assert corr_result.total_groups_formed == 2

        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        results = rca_engine.analyze_results(corr_result)

        assert len(results) == 2
        assert {r.group_id for r in results} == {g.group_id for g in corr_result.groups}


# ---------------------------------------------------------------------------
# 5. Determinism, Tie-Breaking, and Immutability
# ---------------------------------------------------------------------------

class TestDeterminismAndTieBreaking:
    """Test suite verifying hypothesis ranking tie-breakers and dataclass immutability."""

    def test_hypothesis_immutability(self) -> None:
        hyp = RootCauseHypothesis(
            hypothesis_id="hyp-1",
            cause_type=RootCauseType.CELL_OUTAGE,
            target_id="CELL-01",
            target_type=TargetType.NODE,
            confidence_score=0.85,
            explanation="Explanation",
            evidence_items=(),
            group_id="group-1",
        )
        with pytest.raises(AttributeError):
            hyp.confidence_score = 0.90  # type: ignore[misc]

    def test_tie_breaking_order(self) -> None:
        # Construct two hypotheses with identical confidence score
        h1 = RootCauseHypothesis(
            hypothesis_id="hyp-1",
            cause_type=RootCauseType.SITE_POWER_FAILURE,
            target_id="SITE-01",
            target_type=TargetType.NODE,
            confidence_score=0.75,
            explanation="Power failure",
            evidence_items=(),
            group_id="group-1",
        )
        h2 = RootCauseHypothesis(
            hypothesis_id="hyp-2",
            cause_type=RootCauseType.BACKHAUL_FAILURE,
            target_id="LINK-01",
            target_type=TargetType.TRANSPORT_LINK,
            confidence_score=0.75,
            explanation="Backhaul failure",
            evidence_items=(),
            group_id="group-1",
        )

        # Primary sort: confidence desc (-score).
        # Tie-breaker 1: cause_type.value asc ('BACKHAUL_FAILURE' < 'SITE_POWER_FAILURE')
        items = [h1, h2]
        items.sort(key=lambda h: (-h.confidence_score, h.cause_type.value, h.target_id))
        assert items[0].cause_type == RootCauseType.BACKHAUL_FAILURE
        assert items[1].cause_type == RootCauseType.SITE_POWER_FAILURE


# ---------------------------------------------------------------------------
# 6. Ground-Truth Isolation Verification
# ---------------------------------------------------------------------------

class TestRCAGroundTruthIsolation:
    """Verify that nexus.rca does not import or depend on nexus.fault."""

    def test_zero_imports_from_fault(self) -> None:
        rca_dir = Path(__file__).resolve().parent.parent / "src" / "nexus" / "rca"
        for py_file in rca_dir.glob("*.py"):
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
# 7. Remediation & Diagnostic Evidence Regression Tests
# ---------------------------------------------------------------------------

class TestRCACorrectnessRemediation:
    """Regression test suite for Milestone 5 Focused Correctness Review."""

    @pytest.fixture
    def setup_network(self) -> tuple[Topology, TransportNetwork]:
        topo = build_simulated_network()
        trans = build_reference_transport_network(topo)
        return topo, trans

    def test_rca_changes_when_telemetry_changes_with_identical_alarms(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Verify that RCA confidence score and evidence differ when telemetry changes,
        even though input alarms remain completely identical."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Identical PRB alarm on CELL-01
        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=95.0, threshold=85.0, first_seen=base_time),
            make_alarm("alm-tp", "CELL-01", "throughput_mbps", current_value=15.0, threshold=40.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        group = corr_result.groups[0]

        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)

        # Telemetry A: Confirms clean RF environment (sinr_db = 18 dB >= 10 dB)
        snaps_a = [make_cell_snapshot("CELL-01", prb_utilization_pct=95.0, sinr_db=18.0, throughput_mbps=15.0)]
        res_a = rca_engine.analyze_group(group, telemetry_snapshots=snaps_a, analysis_timestamp=base_time)

        # Telemetry B: No snapshot provided (unverified radio health)
        res_b = rca_engine.analyze_group(group, telemetry_snapshots=None, analysis_timestamp=base_time)

        assert res_a.primary_hypothesis is not None
        assert res_b.primary_hypothesis is not None
        assert res_a.primary_hypothesis.cause_type == RootCauseType.CELL_CONGESTION
        assert res_b.primary_hypothesis.cause_type == RootCauseType.CELL_CONGESTION

        # Telemetry A achieves higher confidence and includes SNAPSHOT evidence
        assert res_a.primary_hypothesis.confidence_score > res_b.primary_hypothesis.confidence_score
        assert any(e.evidence_source == "SNAPSHOT" for e in res_a.primary_hypothesis.evidence_items)
        assert not any(e.evidence_source == "SNAPSHOT" for e in res_b.primary_hypothesis.evidence_items)

    def test_stale_telemetry_rejected(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        """Verify that telemetry snapshots outside the freshness window are rejected as stale."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=95.0, threshold=85.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        group = corr_result.groups[0]

        rca_engine = RootCauseAnalysisEngine(
            topology=topo,
            transport=trans,
            config=RCAConfig(max_telemetry_staleness_seconds=60.0),
        )

        # Snapshot is 2 hours before the incident (stale)
        stale_snaps = [
            make_cell_snapshot("CELL-01", timestamp=base_time - timedelta(hours=2), prb_utilization_pct=95.0, sinr_db=18.0)
        ]
        res = rca_engine.analyze_group(group, telemetry_snapshots=stale_snaps, analysis_timestamp=base_time)

        assert res.primary_hypothesis is not None
        # Stale snapshot must NOT appear in evidence
        assert not any(e.evidence_source == "SNAPSHOT" for e in res.primary_hypothesis.evidence_items)

    def test_rsrp_degradation_without_sinr_does_not_prove_interference(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Verify that RSRP degradation alone without degraded SINR does NOT trigger radio interference."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Alarm on RSRP only (low signal / coverage hole, not interference)
        alarms = [
            make_alarm("alm-rsrp", "CELL-01", "rsrp_dbm", current_value=-118.0, threshold=-110.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        group = corr_result.groups[0]

        # Snapshot shows healthy SINR (18 dB)
        snaps = [make_cell_snapshot("CELL-01", rsrp_dbm=-118.0, sinr_db=18.0)]

        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        res = rca_engine.analyze_group(group, telemetry_snapshots=snaps, analysis_timestamp=base_time)

        # Must NOT diagnose RADIO_INTERFERENCE
        assert res.primary_hypothesis is not None
        assert res.primary_hypothesis.cause_type != RootCauseType.RADIO_INTERFERENCE

    def test_mild_prb_does_not_qualify_as_congestion(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Verify that PRB utilization below 80% is rejected and does not qualify as cell congestion."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Alarm on PRB at 65% (below 80% threshold)
        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=65.0, threshold=60.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        group = corr_result.groups[0]

        snaps = [make_cell_snapshot("CELL-01", prb_utilization_pct=65.0, sinr_db=18.0)]

        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        res = rca_engine.analyze_group(group, telemetry_snapshots=snaps, analysis_timestamp=base_time)

        assert res.primary_hypothesis is not None
        assert res.primary_hypothesis.cause_type != RootCauseType.CELL_CONGESTION

    def test_mild_availability_reduction_does_not_qualify_as_site_power_failure(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Verify that mild availability reduction (> 10%) does not qualify as site power failure."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Mild availability drops across cells under SITE-01 (e.g. 85%)
        alarms = [
            make_alarm("alm-1", "CELL-01", "availability_pct", current_value=85.0, threshold=95.0, first_seen=base_time),
            make_alarm("alm-2", "CELL-02", "availability_pct", current_value=85.0, threshold=95.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        group = corr_result.groups[0]

        snaps = [
            make_cell_snapshot("CELL-01", availability_pct=85.0),
            make_cell_snapshot("CELL-02", availability_pct=85.0),
        ]

        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        res = rca_engine.analyze_group(group, telemetry_snapshots=snaps, analysis_timestamp=base_time)

        assert res.primary_hypothesis is not None
        assert res.primary_hypothesis.cause_type != RootCauseType.SITE_POWER_FAILURE

    def test_cell_outage_does_not_claim_sibling_health_without_telemetry(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Verify that cell outage marks sibling health as unverified and reduces score when telemetry is absent."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        alarms = [
            make_alarm("alm-avail", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        group = corr_result.groups[0]

        # Case 1: Telemetry available for siblings CELL-02 and CELL-03
        snaps_with_siblings = [
            make_cell_snapshot("CELL-01", availability_pct=0.0),
            make_cell_snapshot("CELL-02", availability_pct=99.9),
            make_cell_snapshot("CELL-03", availability_pct=99.8),
        ]
        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        res_with = rca_engine.analyze_group(group, telemetry_snapshots=snaps_with_siblings, analysis_timestamp=base_time)

        # Case 2: No sibling telemetry provided
        snaps_no_siblings = [
            make_cell_snapshot("CELL-01", availability_pct=0.0),
        ]
        res_without = rca_engine.analyze_group(group, telemetry_snapshots=snaps_no_siblings, analysis_timestamp=base_time)

        assert res_with.primary_hypothesis is not None
        assert res_without.primary_hypothesis is not None

        # Sibling health verified yields higher score than unverified
        assert res_with.primary_hypothesis.confidence_score > res_without.primary_hypothesis.confidence_score
        assert any("unverified" in e.reasoning.lower() for e in res_without.primary_hypothesis.evidence_items)

    def test_backhaul_does_not_score_high_merely_because_transport_link_exists(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Verify that an anchor node with an upstream link does not diagnose backhaul failure
        when symptoms do not reflect transport degradation (e.g. throughput surge)."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Alarm on throughput surge (360 Mbps), not collapse!
        alarms = [
            make_alarm("alm-tp", "CELL-01", "throughput_mbps", current_value=360.0, threshold=150.0, first_seen=base_time),
        ]
        corr_result = corr_engine.correlate(alarms)
        group = corr_result.groups[0]

        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        res = rca_engine.analyze_group(group, analysis_timestamp=base_time)

        assert res.primary_hypothesis is not None
        assert res.primary_hypothesis.cause_type != RootCauseType.BACKHAUL_FAILURE


# ---------------------------------------------------------------------------
# 8. Milestone 5 Final Correctness Pass Regression Tests
# ---------------------------------------------------------------------------

class TestRCAFinalCorrectnessPass:
    """Regression test suite for Milestone 5 Final Correctness Pass."""

    @pytest.fixture
    def setup_network(self) -> tuple[Topology, TransportNetwork]:
        topo = build_simulated_network()
        trans = build_reference_transport_network(topo)
        return topo, trans

    # 1. Prevent future telemetry look-ahead tests
    def test_lookahead_only_future_snapshots_exist(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=95.0, threshold=85.0, first_seen=base_time),
            make_alarm("alm-tp", "CELL-01", "throughput_mbps", current_value=20.0, threshold=50.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        # Only future snapshots exist (e.g. 5 minutes in the future)
        future_snaps = [
            make_cell_snapshot("CELL-01", timestamp=base_time + timedelta(minutes=5), prb_utilization_pct=95.0, throughput_mbps=20.0)
        ]
        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        res = rca_engine.analyze_group(group, telemetry_snapshots=future_snaps, analysis_timestamp=base_time)
        assert res.primary_hypothesis is not None
        # Future snapshot must be completely ignored - no SNAPSHOT evidence
        assert not any(e.evidence_source == "SNAPSHOT" for e in res.primary_hypothesis.evidence_items)

    def test_lookahead_past_and_future_snapshots_exist(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=95.0, threshold=85.0, first_seen=base_time),
            make_alarm("alm-tp", "CELL-01", "throughput_mbps", current_value=20.0, threshold=50.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        past_snap = make_cell_snapshot("CELL-01", timestamp=base_time - timedelta(seconds=30), latency_ms=45.0, throughput_mbps=20.0, prb_utilization_pct=95.0)
        future_snap = make_cell_snapshot("CELL-01", timestamp=base_time + timedelta(seconds=60), latency_ms=10.0, throughput_mbps=20.0, prb_utilization_pct=95.0)
        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        res = rca_engine.analyze_group(group, telemetry_snapshots=[past_snap, future_snap], analysis_timestamp=base_time)
        assert res.primary_hypothesis is not None
        # Past snapshot (latency 45.0) must be selected, NOT future snapshot (latency 10.0)
        snap_evs = [e for e in res.primary_hypothesis.evidence_items if e.evidence_source == "SNAPSHOT" and e.metric_name == "latency_ms"]
        assert len(snap_evs) == 1
        assert snap_evs[0].observed_value == 45.0

    def test_lookahead_latest_past_stale_but_older_exists(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=95.0, threshold=85.0, first_seen=base_time),
            make_alarm("alm-tp", "CELL-01", "throughput_mbps", current_value=20.0, threshold=50.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        # Max staleness is 60s. Latest past is 5 min old, older is 10 min old. Both are stale.
        older_stale = make_cell_snapshot("CELL-01", timestamp=base_time - timedelta(minutes=10))
        latest_past_stale = make_cell_snapshot("CELL-01", timestamp=base_time - timedelta(minutes=5))
        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans, config=RCAConfig(max_telemetry_staleness_seconds=60.0))
        res = rca_engine.analyze_group(group, telemetry_snapshots=[older_stale, latest_past_stale], analysis_timestamp=base_time)
        assert res.primary_hypothesis is not None
        assert not any(e.evidence_source == "SNAPSHOT" for e in res.primary_hypothesis.evidence_items)

    def test_lookahead_snapshot_exactly_at_analysis_timestamp(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=95.0, threshold=85.0, first_seen=base_time),
            make_alarm("alm-tp", "CELL-01", "throughput_mbps", current_value=20.0, threshold=50.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        exact_snap = make_cell_snapshot("CELL-01", timestamp=base_time, latency_ms=45.0, throughput_mbps=20.0, prb_utilization_pct=95.0)
        rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
        res = rca_engine.analyze_group(group, telemetry_snapshots=[exact_snap], analysis_timestamp=base_time)
        assert res.primary_hypothesis is not None
        snap_evs = [e for e in res.primary_hypothesis.evidence_items if e.evidence_source == "SNAPSHOT"]
        assert len(snap_evs) > 0

    # 2. Congestion requirements tests
    def test_congestion_high_prb_normal_performance_rejected(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        """High PRB (>=80%) with normal latency (<=30ms) and throughput (>=50Mbps) returns None."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=90.0, threshold=80.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        snaps = [make_cell_snapshot("CELL-01", prb_utilization_pct=90.0, latency_ms=15.0, throughput_mbps=80.0)]
        from nexus.rca.rules import evaluate_cell_congestion
        snap_map = {"CELL-01": snaps[0]}
        hyp = evaluate_cell_congestion(group, topo, trans, snap_map)
        assert hyp is None

    def test_congestion_high_prb_degraded_latency_accepted(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        """High PRB (>=80%) with degraded latency (>30ms) produces CELL_CONGESTION."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=90.0, threshold=80.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        snaps = [make_cell_snapshot("CELL-01", prb_utilization_pct=90.0, latency_ms=45.0, throughput_mbps=80.0)]
        from nexus.rca.rules import evaluate_cell_congestion
        snap_map = {"CELL-01": snaps[0]}
        hyp = evaluate_cell_congestion(group, topo, trans, snap_map)
        assert hyp is not None
        assert hyp.cause_type == RootCauseType.CELL_CONGESTION

    def test_congestion_high_prb_degraded_throughput_accepted(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        """High PRB (>=80%) with degraded throughput (<50Mbps) produces CELL_CONGESTION."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=90.0, threshold=80.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        snaps = [make_cell_snapshot("CELL-01", prb_utilization_pct=90.0, latency_ms=15.0, throughput_mbps=35.0)]
        from nexus.rca.rules import evaluate_cell_congestion
        snap_map = {"CELL-01": snaps[0]}
        hyp = evaluate_cell_congestion(group, topo, trans, snap_map)
        assert hyp is not None
        assert hyp.cause_type == RootCauseType.CELL_CONGESTION

    def test_congestion_high_prb_no_performance_observation_rejected(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        """High PRB without any latency or throughput observation returns None."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=90.0, threshold=80.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        from nexus.rca.rules import evaluate_cell_congestion
        hyp = evaluate_cell_congestion(group, topo, trans, {})
        assert hyp is None

    def test_congestion_low_prb_degraded_performance_rejected(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        """Low PRB (<80%) even with degraded performance returns None."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=65.0, threshold=60.0, first_seen=base_time),
            make_alarm("alm-lat", "CELL-01", "latency_ms", current_value=60.0, threshold=30.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        snaps = [make_cell_snapshot("CELL-01", prb_utilization_pct=65.0, latency_ms=60.0)]
        from nexus.rca.rules import evaluate_cell_congestion
        snap_map = {"CELL-01": snaps[0]}
        hyp = evaluate_cell_congestion(group, topo, trans, snap_map)
        assert hyp is None

    # 3. Radio interference validation & contradictory evidence tests
    def test_radio_interference_sinr_alarm_normal_value_rejected(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        """sinr_db alarm with normal value (>= 10 dB) returns None."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-sinr", "CELL-01", "sinr_db", current_value=12.0, threshold=15.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        from nexus.rca.rules import evaluate_radio_interference
        hyp = evaluate_radio_interference(group, topo, trans, {})
        assert hyp is None

    def test_radio_interference_severe_availability_rejected(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        """Severe availability drop (<= 10%) observed in telemetry returns None (contradictory outage evidence)."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-sinr", "CELL-01", "sinr_db", current_value=2.0, threshold=10.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        snaps = [make_cell_snapshot("CELL-01", sinr_db=2.0, availability_pct=0.0)]
        from nexus.rca.rules import evaluate_radio_interference
        snap_map = {"CELL-01": snaps[0]}
        hyp = evaluate_radio_interference(group, topo, trans, snap_map)
        assert hyp is None

    def test_radio_interference_high_prb_in_telemetry_no_credit(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        """High PRB (>= 80%) observed in telemetry does not award PRB counter-indicator credit."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-sinr", "CELL-01", "sinr_db", current_value=2.0, threshold=10.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        snap_low_prb = make_cell_snapshot("CELL-01", sinr_db=2.0, prb_utilization_pct=40.0, availability_pct=99.0)
        snap_high_prb = make_cell_snapshot("CELL-01", sinr_db=2.0, prb_utilization_pct=90.0, availability_pct=99.0)
        from nexus.rca.rules import evaluate_radio_interference
        hyp_low = evaluate_radio_interference(group, topo, trans, {"CELL-01": snap_low_prb})
        hyp_high = evaluate_radio_interference(group, topo, trans, {"CELL-01": snap_high_prb})
        assert hyp_low is not None and hyp_high is not None
        assert hyp_low.confidence_score > hyp_high.confidence_score

    # 4. Backhaul evidence consistency tests
    def test_backhaul_availability_only_evidence_included(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        """Availability-only degradation includes explicit availability evidence item (ALARM / SNAPSHOT)."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-avail-1", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time),
            make_alarm("alm-avail-2", "CELL-02", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        from nexus.rca.rules import evaluate_backhaul_failure
        hyp = evaluate_backhaul_failure(group, topo, trans, {})
        assert hyp is not None
        assert any(e.metric_name == "availability_pct" and e.evidence_source == "ALARM" for e in hyp.evidence_items)
        assert "availability collapse" in hyp.explanation.lower()

    def test_backhaul_single_cell_availability_collapse_rejected(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        """Single-cell availability collapse with upstream link scores < 0.35 and is rejected."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-avail-1", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        from nexus.rca.rules import evaluate_backhaul_failure
        hyp = evaluate_backhaul_failure(group, topo, trans, {})
        assert hyp is None

    def test_backhaul_genuine_multi_node_degradation_scores_high(self, setup_network: tuple[Topology, TransportNetwork]) -> None:
        """Genuine multi-node degradation scores >= 0.75."""
        topo, trans = setup_network
        corr_engine = AlarmCorrelationEngine(topology=topo)
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarms = [
            make_alarm("alm-lat-1", "CELL-01", "latency_ms", current_value=75.0, threshold=50.0, first_seen=base_time),
            make_alarm("alm-lat-2", "CELL-02", "latency_ms", current_value=80.0, threshold=50.0, first_seen=base_time),
            make_alarm("alm-tp-1", "CELL-01", "throughput_mbps", current_value=5.0, threshold=20.0, first_seen=base_time),
            make_alarm("alm-tp-2", "CELL-02", "throughput_mbps", current_value=4.0, threshold=20.0, first_seen=base_time),
        ]
        group = corr_engine.correlate(alarms).groups[0]
        from nexus.rca.rules import evaluate_backhaul_failure
        hyp = evaluate_backhaul_failure(group, topo, trans, {})
        assert hyp is not None
        assert hyp.confidence_score >= 0.75

    # 5. Backhaul multi-node evidence tests
    def test_backhaul_site_anchor_one_affected_node_no_multi_node_credit(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """SITE anchor with only one affected descendant node does NOT receive multi-node credit."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-lat-1", "CELL-01", "latency_ms", current_value=75.0, threshold=50.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-SITE-SINGLE",
            anchor_node_id="SITE-01",
            root_cause_tier=NodeType.SITE,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        from nexus.rca.rules import evaluate_backhaul_failure
        hyp = evaluate_backhaul_failure(group, topo, trans, {})
        assert hyp is not None
        # Does NOT receive multi-node credit (no branch_impact evidence item)
        assert not any(e.metric_name == "branch_impact" for e in hyp.evidence_items)

    def test_backhaul_aggregation_anchor_one_affected_node_no_multi_node_credit(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """AGGREGATION anchor with only one affected descendant node does NOT receive multi-node credit."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-lat-1", "CELL-01", "latency_ms", current_value=75.0, threshold=50.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-AGG-SINGLE",
            anchor_node_id="AGG-01",
            root_cause_tier=NodeType.AGGREGATION,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        from nexus.rca.rules import evaluate_backhaul_failure
        hyp = evaluate_backhaul_failure(group, topo, trans, {})
        assert hyp is not None
        assert not any(e.metric_name == "branch_impact" for e in hyp.evidence_items)

    def test_backhaul_two_distinct_affected_descendants_receive_multi_node_credit(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Two distinct affected descendant nodes under anchor receive multi-node credit."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm1 = make_alarm("alm-lat-1", "CELL-01", "latency_ms", current_value=75.0, threshold=50.0, first_seen=base_time)
        alarm2 = make_alarm("alm-lat-2", "CELL-02", "latency_ms", current_value=70.0, threshold=50.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-SITE-MULTI",
            anchor_node_id="SITE-01",
            root_cause_tier=NodeType.SITE,
            alarms=(alarm1, alarm2),
            alarm_ids=(alarm1.alarm_id, alarm2.alarm_id),
            node_ids=("CELL-01", "CELL-02"),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        from nexus.rca.rules import evaluate_backhaul_failure
        hyp = evaluate_backhaul_failure(group, topo, trans, {})
        assert hyp is not None
        # Does receive multi-node credit
        branch_ev = [e for e in hyp.evidence_items if e.metric_name == "branch_impact"]
        assert len(branch_ev) == 1
        assert branch_ev[0].observed_value == 2.0

    def test_backhaul_duplicate_alarms_on_one_node_no_multi_node_credit(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Duplicate alarms on a single node do not count as multiple affected nodes."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm1 = make_alarm("alm-lat-1", "CELL-01", "latency_ms", current_value=75.0, threshold=50.0, first_seen=base_time)
        alarm2 = make_alarm("alm-tp-1", "CELL-01", "throughput_mbps", current_value=5.0, threshold=20.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-SITE-DUP",
            anchor_node_id="SITE-01",
            root_cause_tier=NodeType.SITE,
            alarms=(alarm1, alarm2),
            alarm_ids=(alarm1.alarm_id, alarm2.alarm_id),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        from nexus.rca.rules import evaluate_backhaul_failure
        hyp = evaluate_backhaul_failure(group, topo, trans, {})
        assert hyp is not None
        assert not any(e.metric_name == "branch_impact" for e in hyp.evidence_items)

    # 6. Cell outage evidence and scoring consistency tests
    def test_cell_outage_severe_availability_normal_throughput(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Severe availability collapse with normal throughput emits availability evidence and no throughput evidence."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-avail", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-OUTAGE-AVAIL",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        # Snapshot has normal throughput (100.0 Mbps) and collapsed availability (0.0%)
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=0.0, throughput_mbps=100.0),
            "CELL-02": make_cell_snapshot("CELL-02", availability_pct=99.9),
            "CELL-03": make_cell_snapshot("CELL-03", availability_pct=99.9),
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is not None
        assert hyp.cause_type == RootCauseType.CELL_OUTAGE
        # Availability evidence emitted
        assert any(e.metric_name == "availability_pct" for e in hyp.evidence_items)
        # No throughput evidence emitted
        assert not any(e.metric_name == "throughput_mbps" for e in hyp.evidence_items)
        # Explanation describes availability collapse only
        assert "severe availability collapse" in hyp.explanation
        assert "throughput collapse" not in hyp.explanation

    def test_cell_outage_near_zero_throughput_normal_availability(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Near-zero throughput with normal availability emits throughput evidence and no availability evidence."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-tp", "CELL-01", "throughput_mbps", current_value=0.1, threshold=20.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-OUTAGE-TP",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        # Snapshot has near-zero throughput (0.1 Mbps) and normal availability (99.5%)
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=99.5, throughput_mbps=0.1),
            "CELL-02": make_cell_snapshot("CELL-02", availability_pct=99.9),
            "CELL-03": make_cell_snapshot("CELL-03", availability_pct=99.9),
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is not None
        assert hyp.cause_type == RootCauseType.CELL_OUTAGE
        # Throughput evidence emitted
        assert any(e.metric_name == "throughput_mbps" for e in hyp.evidence_items)
        # No availability evidence emitted
        assert not any(e.metric_name == "availability_pct" for e in hyp.evidence_items)
        # Explanation describes throughput collapse only
        assert "near-zero throughput collapse" in hyp.explanation
        assert "severe availability collapse" not in hyp.explanation

    def test_cell_outage_both_severe_availability_and_near_zero_throughput(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Both severe availability collapse and near-zero throughput emit both evidence types and achieve higher score."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm1 = make_alarm("alm-avail", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time)
        alarm2 = make_alarm("alm-tp", "CELL-01", "throughput_mbps", current_value=0.0, threshold=20.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-OUTAGE-BOTH",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm1, alarm2),
            alarm_ids=(alarm1.alarm_id, alarm2.alarm_id),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=0.0, throughput_mbps=0.0),
            "CELL-02": make_cell_snapshot("CELL-02", availability_pct=99.9),
            "CELL-03": make_cell_snapshot("CELL-03", availability_pct=99.9),
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is not None
        assert any(e.metric_name == "availability_pct" for e in hyp.evidence_items)
        assert any(e.metric_name == "throughput_mbps" for e in hyp.evidence_items)
        assert "severe availability collapse" in hyp.explanation
        assert "near-zero throughput collapse" in hyp.explanation
        assert hyp.confidence_score == 1.0

    def test_cell_outage_neither_condition_qualifies(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Normal availability and normal throughput return None from evaluate_cell_outage."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # Alarm on something else (e.g. prb at 50%)
        alarm = make_alarm("alm-prb", "CELL-01", "prb_utilization_pct", current_value=50.0, threshold=40.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-OUTAGE-NEITHER",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=99.9, throughput_mbps=85.0),
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is None

    def test_cell_outage_evidence_items_and_explanations_accurate(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Verify that evidence items and explanations accurately reflect observed values and sources."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-tp", "CELL-01", "throughput_mbps", current_value=0.5, threshold=10.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-OUTAGE-ACC",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=98.0, throughput_mbps=0.5),
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is not None
        # Check alarm evidence
        alarm_ev = next(e for e in hyp.evidence_items if e.evidence_source == "ALARM" and e.metric_name == "throughput_mbps")
        assert alarm_ev.observed_value == 0.5
        # Check snapshot evidence
        snap_ev = next(e for e in hyp.evidence_items if e.evidence_source == "SNAPSHOT" and e.metric_name == "throughput_mbps")
        assert snap_ev.observed_value == 0.5
        # Unverified sibling telemetry
        sib_ev = next(e for e in hyp.evidence_items if e.metric_name == "sibling_health_isolation")
        assert "unverified" in sib_ev.reasoning.lower()
        # Explanation
        assert "observed near-zero throughput collapse" in hyp.explanation
        assert "availability collapse" not in hyp.explanation

    # 7. Final Evidence Integrity Fixes Regression Tests

    # 1. Backhaul branch impact transport-relevant symptoms only
    def test_backhaul_latency_alarm_plus_unrelated_sinr_alarm_no_multi_node_credit(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """One qualifying latency alarm on CELL-01 plus an unrelated SINR alarm on CELL-02 must NOT receive multi-node transport credit."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm_lat = make_alarm("alm-lat", "CELL-01", "latency_ms", current_value=75.0, threshold=50.0, first_seen=base_time)
        alarm_sinr = make_alarm("alm-sinr", "CELL-02", "sinr_db", current_value=2.0, threshold=10.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-BH-UNRELATED",
            anchor_node_id="SITE-01",
            root_cause_tier=NodeType.SITE,
            alarms=(alarm_lat, alarm_sinr),
            alarm_ids=(alarm_lat.alarm_id, alarm_sinr.alarm_id),
            node_ids=("CELL-01", "CELL-02"),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        from nexus.rca.rules import evaluate_backhaul_failure
        hyp = evaluate_backhaul_failure(group, topo, trans, {})
        # Without multi-node credit and with RF counter-indicator, score is 0.30 < 0.35 => None
        assert hyp is None

        # When symptom score is boosted to produce a candidate, verify multi-node credit is still absent
        alarm_tp = make_alarm("alm-tp", "CELL-01", "throughput_mbps", current_value=5.0, threshold=20.0, first_seen=base_time)
        group2 = CorrelationGroup(
            group_id="GRP-BH-UNRELATED-2",
            anchor_node_id="SITE-01",
            root_cause_tier=NodeType.SITE,
            alarms=(alarm_lat, alarm_tp, alarm_sinr),
            alarm_ids=(alarm_lat.alarm_id, alarm_tp.alarm_id, alarm_sinr.alarm_id),
            node_ids=("CELL-01", "CELL-02"),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        hyp2 = evaluate_backhaul_failure(group2, topo, trans, {})
        assert hyp2 is not None
        assert not any(e.metric_name == "branch_impact" for e in hyp2.evidence_items)

    def test_backhaul_two_qualifying_transport_symptoms_distinct_descendants_receives_credit(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Two qualifying transport symptoms on distinct descendants (CELL-01 latency, CELL-02 throughput) receive multi-node credit."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm1 = make_alarm("alm-lat", "CELL-01", "latency_ms", current_value=80.0, threshold=50.0, first_seen=base_time)
        alarm2 = make_alarm("alm-tp", "CELL-02", "throughput_mbps", current_value=5.0, threshold=20.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-BH-QUAL-MULTI",
            anchor_node_id="SITE-01",
            root_cause_tier=NodeType.SITE,
            alarms=(alarm1, alarm2),
            alarm_ids=(alarm1.alarm_id, alarm2.alarm_id),
            node_ids=("CELL-01", "CELL-02"),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        from nexus.rca.rules import evaluate_backhaul_failure
        hyp = evaluate_backhaul_failure(group, topo, trans, {})
        assert hyp is not None
        branch_ev = [e for e in hyp.evidence_items if e.metric_name == "branch_impact"]
        assert len(branch_ev) == 1
        assert branch_ev[0].observed_value == 2.0

    def test_backhaul_duplicate_qualifying_alarms_one_node_counts_once(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Duplicate qualifying transport alarms on one node (CELL-01 latency + throughput) count as only 1 affected node."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm1 = make_alarm("alm-lat", "CELL-01", "latency_ms", current_value=80.0, threshold=50.0, first_seen=base_time)
        alarm2 = make_alarm("alm-tp", "CELL-01", "throughput_mbps", current_value=5.0, threshold=20.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-BH-DUP-QUAL",
            anchor_node_id="SITE-01",
            root_cause_tier=NodeType.SITE,
            alarms=(alarm1, alarm2),
            alarm_ids=(alarm1.alarm_id, alarm2.alarm_id),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        from nexus.rca.rules import evaluate_backhaul_failure
        hyp = evaluate_backhaul_failure(group, topo, trans, {})
        assert hyp is not None
        assert not any(e.metric_name == "branch_impact" for e in hyp.evidence_items)

    # 2. Site operational claim evidence tests
    def test_cell_outage_verified_healthy_site_explanation(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """When site-level telemetry verifies the site is healthy, the explanation states the site appears operational."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-avail", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        from nexus.telemetry import PerformanceMetrics, ReliabilityMetrics
        group = CorrelationGroup(
            group_id="GRP-SITE-HEALTHY",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        site_snap = KPISnapshot(
            node_id="SITE-01",
            timestamp=base_time,
            performance=PerformanceMetrics(throughput_mbps=1000.0, latency_ms=10.0),
            reliability=ReliabilityMetrics(connection_drop_rate_pct=0.0, availability_pct=99.9),
            radio=None,
        )
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=0.0),
            "CELL-02": make_cell_snapshot("CELL-02", availability_pct=99.9),
            "CELL-03": make_cell_snapshot("CELL-03", availability_pct=99.9),
            "SITE-01": site_snap,
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is not None
        assert "appears operational" in hyp.explanation
        assert "SITE-01" in hyp.explanation

    def test_cell_outage_missing_site_telemetry_explanation(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """When site-level telemetry is absent, the explanation explicitly states wider site status is unverified."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-avail", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-SITE-MISSING",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        # No SITE-01 snapshot in telemetry
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=0.0),
            "CELL-02": make_cell_snapshot("CELL-02", availability_pct=99.9),
            "CELL-03": make_cell_snapshot("CELL-03", availability_pct=99.9),
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is not None
        assert "wider site status is unverified" in hyp.explanation
        assert "remains operational" not in hyp.explanation

    def test_cell_outage_evidence_of_wider_site_outage_explanation(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """When site-level evidence indicates a wider outage, do not describe the event as an isolated cell outage without qualification."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-avail", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        from nexus.telemetry import PerformanceMetrics, ReliabilityMetrics
        group = CorrelationGroup(
            group_id="GRP-SITE-OUTAGE",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        # SITE-01 has collapsed availability (0.0%)
        site_snap = KPISnapshot(
            node_id="SITE-01",
            timestamp=base_time,
            performance=PerformanceMetrics(throughput_mbps=0.0, latency_ms=60.0),
            reliability=ReliabilityMetrics(connection_drop_rate_pct=100.0, availability_pct=0.0),
            radio=None,
        )
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=0.0),
            "CELL-02": make_cell_snapshot("CELL-02", availability_pct=99.9),
            "CELL-03": make_cell_snapshot("CELL-03", availability_pct=99.9),
            "SITE-01": site_snap,
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is not None
        # Must be qualified and not described as purely isolated
        assert "wider outage" in hyp.explanation.lower()
        assert not hyp.explanation.startswith("Isolated cell sector outage")

    # 3. Sibling coverage handling tests
    def test_cell_outage_full_sibling_coverage(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """All siblings observed and healthy awards full verification score and records 2/2 coverage in evidence."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-avail", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-SIB-FULL",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        # CELL-01 has 2 siblings under SITE-01: CELL-02 and CELL-03. Both observed and healthy.
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=0.0),
            "CELL-02": make_cell_snapshot("CELL-02", availability_pct=99.9),
            "CELL-03": make_cell_snapshot("CELL-03", availability_pct=99.8),
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is not None
        sib_ev = next(e for e in hyp.evidence_items if e.metric_name == "sibling_health_isolation")
        assert sib_ev.observed_value == 2.0
        assert sib_ev.threshold_or_baseline == 2.0
        assert "2/2 observed" in sib_ev.reasoning
        assert "confirming cell isolation" in sib_ev.reasoning
        assert hyp.confidence_score == 0.80

    def test_cell_outage_partial_sibling_coverage(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Some siblings observed healthy, others missing: awards partial score (0.10) and reports 1/2 coverage."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-avail", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-SIB-PARTIAL",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        # Only CELL-02 observed, CELL-03 missing
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=0.0),
            "CELL-02": make_cell_snapshot("CELL-02", availability_pct=99.9),
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is not None
        sib_ev = next(e for e in hyp.evidence_items if e.metric_name == "sibling_health_isolation")
        assert sib_ev.observed_value == 1.0
        assert sib_ev.threshold_or_baseline == 2.0
        assert "1/2 observed" in sib_ev.reasoning
        assert "unverified" in sib_ev.reasoning.lower()
        assert hyp.confidence_score == 0.65

    def test_cell_outage_unhealthy_sibling_no_isolation_credit(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """An observed sibling that is unhealthy contradicts isolation: awards 0 sibling credit and notes contradiction."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-avail", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-SIB-UNHEALTHY",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        # CELL-02 is degraded (50.0% availability < 90.0%)
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=0.0),
            "CELL-02": make_cell_snapshot("CELL-02", availability_pct=50.0),
            "CELL-03": make_cell_snapshot("CELL-03", availability_pct=99.9),
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is not None
        sib_ev = next(e for e in hyp.evidence_items if e.metric_name == "sibling_health_isolation")
        assert "contradicting cell isolation" in sib_ev.reasoning
        assert "1/2 observed degraded" in sib_ev.reasoning
        assert hyp.confidence_score == 0.40

    def test_cell_outage_no_sibling_telemetry(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """No sibling telemetry retains unverified score (0.05) and reports 0/2 observed."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-avail", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        group = CorrelationGroup(
            group_id="GRP-SIB-NONE",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=0.0),
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is not None
        sib_ev = next(e for e in hyp.evidence_items if e.metric_name == "sibling_health_isolation")
        assert sib_ev.observed_value == 0.0
        assert sib_ev.threshold_or_baseline == 2.0
        assert "0/2 observed" in sib_ev.reasoning
        assert "unverified" in sib_ev.reasoning.lower()
        assert hyp.confidence_score == 0.60

    def test_cell_outage_unhealthy_sibling_healthy_site_explanation(
        self, setup_network: tuple[Topology, TransportNetwork]
    ) -> None:
        """Target cell availability at 0%, host site at 95%, and one sibling at 70%.
        Explanation must not claim isolation or single-cell localization and must accurately describe sibling degradation."""
        topo, trans = setup_network
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        alarm = make_alarm("alm-avail", "CELL-01", "availability_pct", current_value=0.0, threshold=95.0, first_seen=base_time)
        from nexus.correlation.models import CorrelationGroup
        from nexus.topology import NodeType
        from nexus.telemetry import PerformanceMetrics, ReliabilityMetrics
        group = CorrelationGroup(
            group_id="GRP-SIB-UNHEALTHY-SITE-HEALTHY",
            anchor_node_id="CELL-01",
            root_cause_tier=NodeType.CELL,
            alarms=(alarm,),
            alarm_ids=(alarm.alarm_id,),
            node_ids=("CELL-01",),
            time_window_start=base_time,
            time_window_end=base_time,
        )
        site_snap = KPISnapshot(
            node_id="SITE-01",
            timestamp=base_time,
            performance=PerformanceMetrics(throughput_mbps=1000.0, latency_ms=10.0),
            reliability=ReliabilityMetrics(connection_drop_rate_pct=0.0, availability_pct=95.0),
            radio=None,
        )
        snaps = {
            "CELL-01": make_cell_snapshot("CELL-01", availability_pct=0.0),
            "CELL-02": make_cell_snapshot("CELL-02", availability_pct=70.0),
            "CELL-03": make_cell_snapshot("CELL-03", availability_pct=99.9),
            "SITE-01": site_snap,
        }
        from nexus.rca.rules import evaluate_cell_outage
        hyp = evaluate_cell_outage(group, topo, trans, snaps)
        assert hyp is not None

        # Assert explanation does not claim isolation or single-cell localization
        assert not hyp.explanation.lower().startswith("isolated")
        assert "isolated" not in hyp.explanation.lower()
        assert "localized to single cell" not in hyp.explanation.lower()

        # Assert explanation accurately describes sibling degradation and extension beyond target cell
        assert "sibling degradation was observed" in hyp.explanation
        assert "impact may extend beyond target cell" in hyp.explanation

        # Assert host site health is kept separate and stated to appear operational
        assert "while host site 'SITE-01' appears operational" in hyp.explanation

        # Assert does not claim complete site outage
        assert "wider outage" not in hyp.explanation.lower()
        assert "complete site outage" not in hyp.explanation.lower()



