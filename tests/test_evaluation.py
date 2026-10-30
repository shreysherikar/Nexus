"""Unit and integration tests for the evaluation subsystem and ground truth benchmarking."""

from datetime import datetime, timedelta, timezone
from typing import Optional
import pytest

from nexus.detection import AnomalyDetectionEngine, DetectionSource, Severity
from nexus.detection.models import Alarm, AlarmStatus
from nexus.evaluation import (
    EvaluationReport,
    FaultDetectionMatch,
    ScenarioReplayEvaluator,
    evaluate_detections,
)
from nexus.fault import FaultType, GroundTruthRecord, build_reference_scenarios
from nexus.telemetry import SyntheticTelemetryGenerator
from nexus.topology import build_simulated_network
from nexus.transport import build_reference_transport_network


def make_test_alarm(
    alarm_id: str,
    node_id: str,
    first_seen: datetime,
    last_seen: Optional[datetime] = None,
    metric_name: str = "latency_ms",
    source: DetectionSource = DetectionSource.THRESHOLD,
) -> Alarm:
    ls = last_seen or first_seen
    return Alarm(
        alarm_id=alarm_id,
        node_id=node_id,
        rule_id="RULE-TEST",
        metric_name=metric_name,
        source=source,
        severity=Severity.MAJOR,
        current_value=120.0,
        threshold=80.0,
        first_seen=first_seen,
        last_seen=ls,
        observation_count=1,
        status=AlarmStatus.ACTIVE,
    )


class TestEvaluatorMetricsAndMatching:
    """Tests for matching logic, precision, recall, F1, and MTTD calculations."""

    @pytest.fixture
    def base_time(self) -> datetime:
        return datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

    def test_perfect_detection_matching(self, base_time: datetime) -> None:
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            start_time=base_time + timedelta(minutes=5),
            end_time=base_time + timedelta(minutes=15),
            severity=1.0,
            affected_node_ids=("CELL-01",),
        )
        alarm = make_test_alarm(
            alarm_id="A-01",
            node_id="CELL-01",
            first_seen=base_time + timedelta(minutes=5, seconds=30),
        )

        report = evaluate_detections([gt], [alarm])
        assert report.total_faults == 1
        assert report.detected_faults == 1
        assert report.undetected_faults == 0
        assert report.true_positive_alarms == 1
        assert report.false_positive_alarms == 0
        assert report.precision == 1.0
        assert report.recall == 1.0
        assert report.f1_score == 1.0
        assert report.mean_time_to_detect_seconds == 30.0
        assert report.fault_matches[0].detected is True
        assert report.fault_matches[0].matching_alarm_ids == ("A-01",)

    def test_undetected_fault_lowers_recall(self, base_time: datetime) -> None:
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            start_time=base_time + timedelta(minutes=5),
            end_time=base_time + timedelta(minutes=15),
            severity=1.0,
            affected_node_ids=("CELL-01",),
        )
        # Zero alarms
        report = evaluate_detections([gt], [])
        assert report.total_faults == 1
        assert report.detected_faults == 0
        assert report.undetected_faults == 1
        assert report.recall == 0.0
        assert report.precision == 0.0
        assert report.f1_score == 0.0
        assert report.mean_time_to_detect_seconds is None

    def test_unmatched_alarm_counts_as_false_positive(self, base_time: datetime) -> None:
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            start_time=base_time + timedelta(minutes=5),
            end_time=base_time + timedelta(minutes=15),
            severity=1.0,
            affected_node_ids=("CELL-01",),
        )
        # Alarm 1 on CELL-01 (TP)
        a1 = make_test_alarm("A-01", "CELL-01", base_time + timedelta(minutes=6))
        # Alarm 2 on unrelated CELL-08 (FP)
        a2 = make_test_alarm("A-02", "CELL-08", base_time + timedelta(minutes=6))

        report = evaluate_detections([gt], [a1, a2])
        assert report.total_alarms == 2
        assert report.true_positive_alarms == 1
        assert report.false_positive_alarms == 1
        assert report.precision == 0.5
        assert report.recall == 1.0
        assert report.unmatched_alarm_ids == ("A-02",)

    def test_multiple_alarms_during_single_fault_not_inflated(self, base_time: datetime) -> None:
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.BACKHAUL_FAILURE,
            target_id="LINK-AGG-01-SITE-01",
            start_time=base_time + timedelta(minutes=5),
            end_time=base_time + timedelta(minutes=15),
            severity=1.0,
            affected_node_ids=("SITE-01", "CELL-01", "CELL-02", "CELL-03"),
        )
        # 3 alarms on different affected cells during the fault
        a1 = make_test_alarm("A-01", "CELL-01", base_time + timedelta(minutes=5, seconds=10))
        a2 = make_test_alarm("A-02", "CELL-02", base_time + timedelta(minutes=5, seconds=20))
        a3 = make_test_alarm("A-03", "CELL-03", base_time + timedelta(minutes=5, seconds=30))

        report = evaluate_detections([gt], [a1, a2, a3])
        # Fault count is 1, detected is 1 (not 3)
        assert report.total_faults == 1
        assert report.detected_faults == 1
        assert report.recall == 1.0
        # All 3 alarms are true positives for the backhaul cut
        assert report.true_positive_alarms == 3
        assert report.false_positive_alarms == 0
        assert report.precision == 1.0
        # MTTD matches earliest alarm (A-01 delay = 10.0s)
        assert report.mean_time_to_detect_seconds == 10.0

    def test_repeated_active_alarm_observations_do_not_inflate_true_positives(self, base_time: datetime) -> None:
        """An ongoing active alarm that was observed 10 times counts as 1 alarm, not 10."""
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            start_time=base_time + timedelta(minutes=5),
            end_time=base_time + timedelta(minutes=15),
            severity=1.0,
            affected_node_ids=("CELL-01",),
        )
        # Single alarm with observation_count = 10
        alarm = Alarm(
            alarm_id="ALARM-CELL-01-00001",
            node_id="CELL-01",
            rule_id="RULE-AVAIL",
            metric_name="availability_pct",
            source=DetectionSource.THRESHOLD,
            severity=Severity.CRITICAL,
            current_value=0.0,
            threshold=95.0,
            first_seen=base_time + timedelta(minutes=5),
            last_seen=base_time + timedelta(minutes=14),
            observation_count=10,
            status=AlarmStatus.ACTIVE,
        )

        report = evaluate_detections([gt], [alarm])
        assert report.total_alarms == 1
        assert report.true_positive_alarms == 1
        assert report.detected_faults == 1

    def test_grace_period_matching(self, base_time: datetime) -> None:
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            start_time=base_time + timedelta(minutes=5),
            end_time=base_time + timedelta(minutes=15),
            severity=1.0,
            affected_node_ids=("CELL-01",),
        )
        # Alarm first seen 20 seconds AFTER fault end_time (12:15:20)
        alarm = make_test_alarm("A-01", "CELL-01", base_time + timedelta(minutes=15, seconds=20))

        # With grace_period = 30 seconds -> matches!
        rep_with_grace = evaluate_detections([gt], [alarm], grace_period_seconds=30.0)
        assert rep_with_grace.detected_faults == 1
        assert rep_with_grace.true_positive_alarms == 1

        # With grace_period = 10 seconds -> does NOT match (alarm arrived at +20s)
        rep_without_grace = evaluate_detections([gt], [alarm], grace_period_seconds=10.0)
        assert rep_without_grace.detected_faults == 0
        assert rep_without_grace.false_positive_alarms == 1

    def test_empty_input_edge_cases(self) -> None:
        # Zero faults, zero alarms
        r_empty = evaluate_detections([], [])
        assert r_empty.precision == 1.0
        assert r_empty.recall == 1.0
        assert r_empty.f1_score == 1.0
        assert r_empty.mean_time_to_detect_seconds is None

        # Zero faults, 2 alarms (spurious)
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        a1 = make_test_alarm("A-01", "CELL-01", t)
        a2 = make_test_alarm("A-02", "CELL-02", t)
        r_spurious = evaluate_detections([], [a1, a2])
        assert r_spurious.total_faults == 0
        assert r_spurious.false_positive_alarms == 2
        assert r_spurious.precision == 0.0
        assert r_spurious.recall == 1.0

    def test_overlapping_ground_truth_faults(self, base_time: datetime) -> None:
        """Two faults with overlapping windows and shared affected nodes.
        
        One alarm on the shared node within the overlap window detects both faults,
        and is counted exactly once in true_positive_alarms (no alarm inflation).
        """
        # Fault 1: Backhaul cut affecting SITE-01 and CELL-01 (12:00 -> 12:15)
        f1 = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.BACKHAUL_FAILURE,
            target_id="LINK-AGG-01-SITE-01",
            start_time=base_time,
            end_time=base_time + timedelta(minutes=15),
            severity=1.0,
            affected_node_ids=("SITE-01", "CELL-01"),
        )
        # Fault 2: Cell outage on CELL-01 (12:05 -> 12:20)
        f2 = GroundTruthRecord(
            scenario_id="SC-02",
            fault_id="F-02",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            start_time=base_time + timedelta(minutes=5),
            end_time=base_time + timedelta(minutes=20),
            severity=1.0,
            affected_node_ids=("CELL-01",),
        )

        # Single alarm on shared CELL-01 raised at 12:08 (inside overlap window 12:05 - 12:15)
        shared_alarm = make_test_alarm("A-SHARED-01", "CELL-01", base_time + timedelta(minutes=8))

        report = evaluate_detections([f1, f2], [shared_alarm])

        # Both faults are successfully detected by the shared alarm
        assert report.total_faults == 2
        assert report.detected_faults == 2
        assert report.undetected_faults == 0
        assert report.fault_matches[0].detected is True
        assert report.fault_matches[1].detected is True

        # Unique alarm is counted once as a true positive
        assert report.total_alarms == 1
        assert report.true_positive_alarms == 1
        assert report.false_positive_alarms == 0

        # Exact metrics verification
        assert report.alarm_precision == 1.0
        assert report.fault_recall == 1.0
        assert report.hybrid_f1_score == 1.0

        # Backwards-compatible aliases
        assert report.precision == 1.0
        assert report.recall == 1.0
        assert report.f1_score == 1.0

    def test_alarm_id_deduplication(self, base_time: datetime) -> None:
        """Duplicate alarm objects or multiple alarms sharing alarm_id are deduplicated."""
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            start_time=base_time,
            end_time=base_time + timedelta(minutes=10),
            severity=1.0,
            affected_node_ids=("CELL-01",),
        )
        a1 = make_test_alarm("A-DUPE-01", "CELL-01", base_time + timedelta(minutes=2))
        a1_copy = make_test_alarm("A-DUPE-01", "CELL-01", base_time + timedelta(minutes=3))

        report = evaluate_detections([gt], [a1, a1_copy, a1])

        # Deduplication must reduce 3 passed objects with identical alarm_id to 1 alarm
        assert report.total_alarms == 1
        assert report.true_positive_alarms == 1
        assert report.false_positive_alarms == 0
        assert report.alarm_precision == 1.0

    def test_distinct_denominators_and_hybrid_f1_score(self, base_time: datetime) -> None:
        """Verifies distinct counting units between alarm_precision and fault_recall."""
        f1 = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            start_time=base_time,
            end_time=base_time + timedelta(minutes=10),
            severity=1.0,
            affected_node_ids=("CELL-01",),
        )
        f2 = GroundTruthRecord(
            scenario_id="SC-02",
            fault_id="F-02",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-02",
            start_time=base_time,
            end_time=base_time + timedelta(minutes=10),
            severity=1.0,
            affected_node_ids=("CELL-02",),
        )

        # 4 unique alarms: 1 true positive matching F-01, 3 spurious false positives
        a_tp = make_test_alarm("A-01", "CELL-01", base_time + timedelta(minutes=2))
        a_fp1 = make_test_alarm("A-02", "CELL-99", base_time + timedelta(minutes=2))
        a_fp2 = make_test_alarm("A-03", "CELL-98", base_time + timedelta(minutes=2))
        a_fp3 = make_test_alarm("A-04", "CELL-97", base_time + timedelta(minutes=2))

        report = evaluate_detections([f1, f2], [a_tp, a_fp1, a_fp2, a_fp3])

        assert report.total_faults == 2
        assert report.detected_faults == 1
        assert report.undetected_faults == 1

        assert report.total_alarms == 4
        assert report.true_positive_alarms == 1
        assert report.false_positive_alarms == 3

        # Alarm precision: 1 TP / 4 alarms = 0.25
        assert report.alarm_precision == 0.25
        assert report.precision == 0.25

        # Fault recall: 1 detected / 2 faults = 0.5
        assert report.fault_recall == 0.5
        assert report.recall == 0.5

        # Hybrid F1: 2 * (0.25 * 0.5) / (0.25 + 0.5) = 0.25 / 0.75 = 0.3333
        assert report.hybrid_f1_score == 0.3333
        assert report.f1_score == 0.3333

    def test_fault_level_mttd_calculation(self, base_time: datetime) -> None:
        """MTTD is calculated as the earliest alarm per fault, averaged across detected faults."""
        f1 = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            start_time=base_time,
            end_time=base_time + timedelta(minutes=10),
            severity=1.0,
            affected_node_ids=("CELL-01",),
        )
        f2 = GroundTruthRecord(
            scenario_id="SC-02",
            fault_id="F-02",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-02",
            start_time=base_time + timedelta(minutes=20),
            end_time=base_time + timedelta(minutes=30),
            severity=1.0,
            affected_node_ids=("CELL-02",),
        )

        # F1 matched by alarms at +60s and +120s -> earliest delay is 60s
        a1_1 = make_test_alarm("A-1", "CELL-01", base_time + timedelta(seconds=60))
        a1_2 = make_test_alarm("A-2", "CELL-01", base_time + timedelta(seconds=120))

        # F2 matched by alarm at +90s -> earliest delay is 90s
        a2_1 = make_test_alarm("A-3", "CELL-02", base_time + timedelta(minutes=20, seconds=90))

        report = evaluate_detections([f1, f2], [a1_1, a1_2, a2_1])
        # Average of 60s and 90s = 75.0s
        assert report.mean_time_to_detect_seconds == 75.0


class TestScenarioReplayIntegration:
    """Integration tests running telemetry generation + fault scenarios + detection + evaluation."""

    @pytest.fixture
    def net(self):
        return build_simulated_network()

    @pytest.fixture
    def transport(self, net):
        return build_reference_transport_network(net)

    @pytest.fixture
    def base_time(self):
        return datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def scenarios(self, net, transport, base_time):
        return build_reference_scenarios(net, transport, base_time=base_time)

    @pytest.mark.parametrize(
        "scenario_key",
        [
            "cell_outage",
            "backhaul_failure",
            "radio_interference",
            "cell_congestion",
            "site_power_failure",
        ],
    )
    def test_replay_evaluator_all_reference_scenarios(
        self, net, transport, base_time, scenarios, scenario_key: str
    ) -> None:
        """Verify that every reference fault scenario is detected and evaluated without detection accessing ground truth."""
        engine = AnomalyDetectionEngine()
        evaluator = ScenarioReplayEvaluator(engine)

        fault_engine = scenarios[scenario_key]
        ground_truth = fault_engine.get_ground_truth()
        assert len(ground_truth) > 0

        # Generate 30 minutes of 1-minute steps (ensuring all scenario fault windows are reached)
        gen = SyntheticTelemetryGenerator(net, seed=42)
        all_snapshots = []
        for i in range(30):
            step_time = base_time + timedelta(minutes=i)
            base_snaps = gen.generate_step(timestamp=step_time)
            effective_snaps = fault_engine.apply_faults(base_snaps, timestamp=step_time)
            all_snapshots.extend(effective_snaps)

        # Node type mapping for rule scoping
        node_types = {n.node_id: n.node_type for n in net.all_nodes()}

        batch_result, report = evaluator.replay_and_evaluate(
            snapshots=all_snapshots,
            ground_truth=ground_truth,
            node_types=node_types,
            grace_period_seconds=60.0,
        )

        assert batch_result.processed_snapshots_count == len(all_snapshots)
        # Every reference fault scenario must be detected by at least one alarm
        assert report.total_faults >= 1
        assert report.detected_faults >= 1
        assert report.recall == 1.0
        assert report.true_positive_alarms >= 1
        assert report.mean_time_to_detect_seconds is not None
        assert report.mean_time_to_detect_seconds >= 0.0
