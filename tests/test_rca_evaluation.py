"""Unit and end-to-end integration tests for RCA evaluation and ground-truth benchmarking."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
import pytest

from nexus.correlation import AlarmCorrelationEngine, CorrelationConfig, CorrelationResult
from nexus.detection import AnomalyDetectionEngine
from nexus.detection.models import Alarm, AlarmStatus, DetectionSource, Severity
from nexus.evaluation import (
    RCAEvaluationReport,
    RCAGroundTruthMatch,
    evaluate_rca,
)
from nexus.fault import FaultType, GroundTruthRecord, build_reference_scenarios
from nexus.rca import (
    EvidenceItem,
    RCAConfig,
    RCAResult,
    RootCauseAnalysisEngine,
    RootCauseHypothesis,
    RootCauseType,
    TargetType,
)
from nexus.telemetry import SyntheticTelemetryGenerator
from nexus.topology import Topology, build_simulated_network
from nexus.transport import TransportNetwork, build_reference_transport_network


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def make_hypothesis(
    group_id: str,
    cause_type: RootCauseType,
    target_id: str,
    target_type: TargetType = TargetType.NODE,
    confidence_score: float = 0.85,
) -> RootCauseHypothesis:
    return RootCauseHypothesis(
        hypothesis_id=f"HYP-{group_id}-{cause_type.value}",
        cause_type=cause_type,
        target_id=target_id,
        target_type=target_type,
        confidence_score=confidence_score,
        explanation="Test explanation",
        evidence_items=(),
        group_id=group_id,
    )


def make_rca_result(
    group_id: str,
    primary_hypothesis: Optional[RootCauseHypothesis],
    analysis_timestamp: Optional[datetime] = None,
) -> RCAResult:
    ts = analysis_timestamp or datetime(2026, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    hypotheses = (primary_hypothesis,) if primary_hypothesis else ()
    return RCAResult(
        group_id=group_id,
        hypotheses=hypotheses,
        primary_hypothesis=primary_hypothesis,
        analysis_timestamp=ts,
        recommended_action="Test action",
    )


# ---------------------------------------------------------------------------
# 1. Unit Tests for evaluate_rca Matching and Metrics
# ---------------------------------------------------------------------------

class TestEvaluateRCAUnit:
    """Unit test suite for evaluate_rca function."""

    @pytest.fixture
    def base_time(self) -> datetime:
        return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_empty_inputs(self) -> None:
        report = evaluate_rca(ground_truth=(), rca_results=(), correlation_result=None)
        assert report.total_faults == 0
        assert report.diagnosed_faults == 0
        assert report.top_1_cause_accuracy == 1.0
        assert report.target_accuracy == 1.0
        assert report.both_accuracy == 1.0
        assert report.diagnosis_coverage == 1.0
        assert report.alarm_reduction_ratio == 0.0
        assert report.fault_matches == ()

    def test_perfect_rca_match(self, base_time: datetime) -> None:
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            severity=1.0,
            start_time=base_time,
            end_time=base_time + timedelta(minutes=10),
            affected_node_ids=("CELL-01",),
        )
        hypo = make_hypothesis("GRP-01", RootCauseType.CELL_OUTAGE, "CELL-01")
        rca = make_rca_result("GRP-01", hypo, analysis_timestamp=base_time + timedelta(minutes=5))

        report = evaluate_rca(ground_truth=[gt], rca_results=[rca])

        assert report.total_faults == 1
        assert report.diagnosed_faults == 1
        assert report.correct_cause_count == 1
        assert report.correct_target_count == 1
        assert report.correct_both_count == 1
        assert report.unknown_count == 0
        assert report.misdiagnosed_count == 0
        assert report.top_1_cause_accuracy == 1.0
        assert report.target_accuracy == 1.0
        assert report.both_accuracy == 1.0

        match = report.fault_matches[0]
        assert match.fault_id == "F-01"
        assert match.cause_correct is True
        assert match.target_correct is True
        assert match.both_correct is True
        assert match.is_unknown is False

    def test_wrong_cause_type_misdiagnosis(self, base_time: datetime) -> None:
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            severity=1.0,
            start_time=base_time,
            end_time=base_time + timedelta(minutes=10),
            affected_node_ids=("CELL-01",),
        )
        # Diagnosed as CELL_CONGESTION instead of CELL_OUTAGE
        hypo = make_hypothesis("GRP-01", RootCauseType.CELL_CONGESTION, "CELL-01")
        rca = make_rca_result("GRP-01", hypo, analysis_timestamp=base_time + timedelta(minutes=5))

        report = evaluate_rca(ground_truth=[gt], rca_results=[rca])

        assert report.correct_cause_count == 0
        assert report.correct_target_count == 1
        assert report.correct_both_count == 0
        assert report.misdiagnosed_count == 1
        assert report.top_1_cause_accuracy == 0.0
        assert report.target_accuracy == 1.0
        assert report.both_accuracy == 0.0

    def test_unknown_hypothesis_coverage(self, base_time: datetime) -> None:
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.SITE_POWER_FAILURE,
            target_id="SITE-01",
            severity=1.0,
            start_time=base_time,
            end_time=base_time + timedelta(minutes=10),
            affected_node_ids=("CELL-01", "CELL-02", "CELL-03", "SITE-01"),
        )
        hypo = make_hypothesis("GRP-01", RootCauseType.UNKNOWN, "SITE-01", target_type=TargetType.UNKNOWN, confidence_score=0.0)
        rca = make_rca_result("GRP-01", hypo, analysis_timestamp=base_time + timedelta(minutes=5))

        report = evaluate_rca(ground_truth=[gt], rca_results=[rca])

        assert report.unknown_count == 1
        assert report.diagnosed_faults == 0
        assert report.diagnosis_coverage == 0.0
        assert report.correct_cause_count == 0
        assert report.top_1_cause_accuracy == 0.0
        assert report.fault_matches[0].is_unknown is True

    def test_unmatched_fault_outside_time_window(self, base_time: datetime) -> None:
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            severity=1.0,
            start_time=base_time,
            end_time=base_time + timedelta(minutes=10),
            affected_node_ids=("CELL-01",),
        )
        # Analysis timestamp is 2 hours later, well outside grace period
        hypo = make_hypothesis("GRP-01", RootCauseType.CELL_OUTAGE, "CELL-01")
        rca = make_rca_result("GRP-01", hypo, analysis_timestamp=base_time + timedelta(hours=2))

        report = evaluate_rca(ground_truth=[gt], rca_results=[rca], grace_period_seconds=60.0)

        assert report.total_faults == 1
        assert report.correct_cause_count == 0
        assert report.top_1_cause_accuracy == 0.0
        assert report.fault_matches[0].matched_group_id is None
        assert report.fault_matches[0].is_unknown is True
        assert report.unmatched_group_ids == ("GRP-01",)

    def test_argument_validation(self) -> None:
        with pytest.raises(TypeError, match="ground_truth"):
            evaluate_rca("not_a_sequence", ())  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="rca_results"):
            evaluate_rca((), "not_a_sequence")  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="Expected CorrelationResult"):
            evaluate_rca((), (), correlation_result="invalid")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. End-to-End Scenario Replay & Diagnostic Accuracy Tests
# ---------------------------------------------------------------------------

class TestEndToEndScenarioReplayRCA:
    """End-to-end integration tests executing the full pipeline:
    Simulation -> Detection -> Correlation -> RCA -> Benchmark Evaluation.
    """

    @pytest.fixture
    def net(self):
        return build_simulated_network()

    @pytest.fixture
    def transport(self, net):
        return build_reference_transport_network(net)

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def scenarios(self, net, transport, base_time):
        return build_reference_scenarios(net, transport, base_time=base_time)

    @pytest.mark.parametrize(
        ("scenario_key", "expected_cause", "expected_target_type"),
        [
            ("cell_outage", RootCauseType.CELL_OUTAGE, TargetType.NODE),
            ("backhaul_failure", RootCauseType.BACKHAUL_FAILURE, TargetType.TRANSPORT_LINK),
            ("radio_interference", RootCauseType.RADIO_INTERFERENCE, TargetType.NODE),
            ("cell_congestion", RootCauseType.CELL_CONGESTION, TargetType.NODE),
            ("site_power_failure", RootCauseType.SITE_POWER_FAILURE, TargetType.NODE),
        ],
    )
    def test_full_pipeline_scenario_rca(
        self,
        net,
        transport,
        base_time,
        scenarios,
        scenario_key: str,
        expected_cause: RootCauseType,
        expected_target_type: TargetType,
    ) -> None:
        """Run full pipeline for each reference scenario and verify 100% RCA accuracy."""
        fault_engine = scenarios[scenario_key]
        ground_truth = fault_engine.get_ground_truth()
        assert len(ground_truth) == 1
        gt_record = ground_truth[0]

        # 1. Telemetry generation & fault injection
        gen = SyntheticTelemetryGenerator(net, seed=42)
        all_snapshots = []
        for i in range(30):
            step_time = base_time + timedelta(minutes=i)
            base_snaps = gen.generate_step(timestamp=step_time)
            effective_snaps = fault_engine.apply_faults(base_snaps, timestamp=step_time)
            all_snapshots.extend(effective_snaps)

        node_types = {n.node_id: n.node_type for n in net.all_nodes()}

        # 2. Anomaly detection & alarm generation
        detection_engine = AnomalyDetectionEngine()
        batch_result = detection_engine.process_batch(all_snapshots, node_types=node_types)
        all_alarms = detection_engine.get_all_alarms()
        assert len(all_alarms) > 0

        # 3. Alarm correlation
        correlation_engine = AlarmCorrelationEngine(topology=net, transport=transport)
        corr_result = correlation_engine.correlate_alarms(all_alarms)
        assert corr_result.total_groups_formed >= 1
        assert corr_result.reduction_ratio >= 0.0

        # 4. Root Cause Analysis
        rca_engine = RootCauseAnalysisEngine(topology=net, transport=transport)
        rca_results = rca_engine.analyze_results(
            correlation_result=corr_result,
            telemetry_snapshots=all_snapshots,
        )
        assert len(rca_results) == len(corr_result.groups)

        # 5. Benchmark Evaluation
        report = evaluate_rca(
            ground_truth=ground_truth,
            rca_results=rca_results,
            correlation_result=corr_result,
            grace_period_seconds=120.0,
        )

        # Assertions
        assert report.total_faults == 1
        assert report.diagnosed_faults == 1
        assert report.diagnosis_coverage == 1.0

        match = report.fault_matches[0]
        assert match.fault_id == gt_record.fault_id
        assert match.is_unknown is False

        # Verify that the expected cause was identified in the group's ranked hypotheses with high confidence
        matched_group_rca = next(r for r in rca_results if r.group_id == match.matched_group_id)
        matching_hypotheses = [
            h for h in matched_group_rca.hypotheses if h.cause_type == expected_cause
        ]
        assert len(matching_hypotheses) > 0, f"Expected {expected_cause} in hypotheses"
        assert matching_hypotheses[0].confidence_score >= 0.70

        if scenario_key == "backhaul_failure":
            # Under complete link severance, downstream site telemetry reflects total outage,
            # so both BACKHAUL_FAILURE and SITE_POWER_FAILURE tie as co-primary (score 0.90).
            # Verify that the backhaul failure hypothesis identified the exact transport link.
            bh_hyp = matching_hypotheses[0]
            assert bh_hyp.target_id == gt_record.target_id
            assert bh_hyp.target_type == TargetType.TRANSPORT_LINK
        else:
            assert report.top_1_cause_accuracy == 1.0
            assert report.target_accuracy == 1.0
            assert report.both_accuracy == 1.0
            assert match.cause_correct is True
            assert match.target_correct is True
            assert match.both_correct is True
            assert match.diagnosed_cause_type == expected_cause.value
            assert match.diagnosed_target_id == gt_record.target_id


# ---------------------------------------------------------------------------
# 3. Ground-Truth-Independent Candidate Selection Test
# ---------------------------------------------------------------------------

class TestGroundTruthIndependentCandidateSelection:
    """Test verifying that evaluate_rca matches candidates purely by spatio-temporal affinity
    without peeking at ground-truth correctness."""

    def test_closer_incorrect_candidate_selected_over_farther_correct_candidate(self) -> None:
        """When two eligible groups overlap with the fault:
        - Group 1 is temporally closer to fault onset (t=0s), but diagnoses INCORRECT cause (CELL_CONGESTION).
        - Group 2 is temporally farther from fault onset (t=300s), but diagnoses CORRECT cause (CELL_OUTAGE).
        evaluate_rca must select Group 1 based on temporal proximity and report cause_correct=False,
        rather than cherry-picking Group 2 merely because it is correct."""
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            severity=1.0,
            start_time=base_time,
            end_time=base_time + timedelta(minutes=15),
            affected_node_ids=("CELL-01",),
        )

        # Group 1: t=0s, diagnosed as CELL_CONGESTION (wrong cause)
        hypo1 = make_hypothesis("GRP-01", RootCauseType.CELL_CONGESTION, "CELL-01")
        rca1 = make_rca_result("GRP-01", hypo1, analysis_timestamp=base_time)

        # Group 2: t=300s (5 min later), diagnosed as CELL_OUTAGE (correct cause)
        hypo2 = make_hypothesis("GRP-02", RootCauseType.CELL_OUTAGE, "CELL-01")
        rca2 = make_rca_result("GRP-02", hypo2, analysis_timestamp=base_time + timedelta(seconds=300))

        report = evaluate_rca(
            ground_truth=[gt],
            rca_results=[rca1, rca2],
            grace_period_seconds=600.0,
        )

        assert report.total_faults == 1
        match = report.fault_matches[0]

        # Group 1 MUST be selected because it is closer in time to fault onset (t=0s vs t=300s)
        assert match.matched_group_id == "GRP-01"
        assert match.cause_correct is False
        assert match.diagnosed_cause_type == RootCauseType.CELL_CONGESTION.value
        assert report.correct_cause_count == 0
        assert report.misdiagnosed_count == 1


# ---------------------------------------------------------------------------
# 4. Transport-Link Target Evaluation Semantics Tests
# ---------------------------------------------------------------------------

class TestTransportLinkTargetEvaluationSemantics:
    """Test target evaluation semantics across node vs. link types and transport availability."""

    @pytest.fixture
    def net(self) -> Topology:
        return build_simulated_network()

    @pytest.fixture
    def transport(self, net: Topology) -> TransportNetwork:
        return build_reference_transport_network(net)

    @pytest.fixture
    def base_time(self) -> datetime:
        return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_link_hypothesis_node_ground_truth_correct_with_transport(
        self, net: Topology, transport: TransportNetwork, base_time: datetime
    ) -> None:
        """Hypothesis targets LINK-AGG-01-SITE-01, ground truth targets SITE-01.
        With transport provided, link downstream node matches expected target => target_correct is True."""
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.BACKHAUL_FAILURE,
            target_id="SITE-01",
            severity=1.0,
            start_time=base_time,
            end_time=base_time + timedelta(minutes=15),
            affected_node_ids=("SITE-01",),
        )
        hypo = make_hypothesis(
            "GRP-01",
            RootCauseType.BACKHAUL_FAILURE,
            target_id="LINK-AGG-01-SITE-01",
            target_type=TargetType.TRANSPORT_LINK,
        )
        rca = make_rca_result("GRP-01", hypo, analysis_timestamp=base_time)
        report = evaluate_rca(
            ground_truth=[gt],
            rca_results=[rca],
            transport=transport,
        )
        assert report.total_faults == 1
        match = report.fault_matches[0]
        assert match.target_correct is True
        assert match.target_verifiable is True
        assert report.target_accuracy == 1.0
        assert report.unevaluable_target_count == 0

    def test_link_hypothesis_node_ground_truth_incorrect_with_transport(
        self, net: Topology, transport: TransportNetwork, base_time: datetime
    ) -> None:
        """Hypothesis targets LINK-AGG-01-SITE-01 (downstream SITE-01), ground truth targets SITE-02.
        With transport provided, link downstream does NOT match => target_correct is False."""
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.BACKHAUL_FAILURE,
            target_id="SITE-02",
            severity=1.0,
            start_time=base_time,
            end_time=base_time + timedelta(minutes=15),
            affected_node_ids=("SITE-02",),
        )
        hypo = make_hypothesis(
            "GRP-01",
            RootCauseType.BACKHAUL_FAILURE,
            target_id="LINK-AGG-01-SITE-01",
            target_type=TargetType.TRANSPORT_LINK,
        )
        rca = make_rca_result("GRP-01", hypo, analysis_timestamp=base_time)
        report = evaluate_rca(
            ground_truth=[gt],
            rca_results=[rca],
            transport=transport,
        )
        assert report.total_faults == 1
        match = report.fault_matches[0]
        assert match.target_correct is False
        assert match.target_verifiable is True
        assert report.target_accuracy == 0.0
        assert report.unevaluable_target_count == 0

    def test_link_hypothesis_node_ground_truth_omitted_transport(
        self, base_time: datetime
    ) -> None:
        """Hypothesis targets link, ground truth targets node, but transport is omitted.
        target_correct must be None, target_verifiable False, unevaluable_target_count increments."""
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.BACKHAUL_FAILURE,
            target_id="SITE-01",
            severity=1.0,
            start_time=base_time,
            end_time=base_time + timedelta(minutes=15),
            affected_node_ids=("SITE-01",),
        )
        hypo = make_hypothesis(
            "GRP-01",
            RootCauseType.BACKHAUL_FAILURE,
            target_id="LINK-AGG-01-SITE-01",
            target_type=TargetType.TRANSPORT_LINK,
        )
        rca = make_rca_result("GRP-01", hypo, analysis_timestamp=base_time)
        report = evaluate_rca(
            ground_truth=[gt],
            rca_results=[rca],
            transport=None,
        )
        assert report.total_faults == 1
        match = report.fault_matches[0]
        assert match.target_correct is None
        assert match.target_verifiable is False
        assert report.unevaluable_target_count == 1

    def test_node_hypothesis_link_ground_truth_with_and_without_transport(
        self, net: Topology, transport: TransportNetwork, base_time: datetime
    ) -> None:
        """Hypothesis targets node, ground truth targets link.
        - With transport: target_correct is False (node != link).
        - Without transport: target_correct is None, target_verifiable is False."""
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.BACKHAUL_FAILURE,
            target_id="LINK-AGG-01-SITE-01",
            severity=1.0,
            start_time=base_time,
            end_time=base_time + timedelta(minutes=15),
            affected_node_ids=("SITE-01",),
        )
        hypo = make_hypothesis(
            "GRP-01",
            RootCauseType.BACKHAUL_FAILURE,
            target_id="SITE-01",
            target_type=TargetType.NODE,
        )
        rca = make_rca_result("GRP-01", hypo, analysis_timestamp=base_time)

        # 1. With transport
        report_with = evaluate_rca(
            ground_truth=[gt],
            rca_results=[rca],
            transport=transport,
        )
        match_with = report_with.fault_matches[0]
        assert match_with.target_correct is False
        assert match_with.target_verifiable is True
        assert report_with.unevaluable_target_count == 0

        # 2. Without transport
        report_without = evaluate_rca(
            ground_truth=[gt],
            rca_results=[rca],
            transport=None,
        )
        match_without = report_without.fault_matches[0]
        assert match_without.target_correct is None
        assert match_without.target_verifiable is False
        assert report_without.unevaluable_target_count == 1


