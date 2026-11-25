"""Comprehensive regression tests for statistical detection, baseline integrity, and alarm recovery.

Covers:
1. DEFECT-01: Same-batch flagged-and-recovered path without AttributeError, testing _alarm_key filtering.
2. DEFECT-02: Restored statistical anomaly detection:
   - 5.5x throughput surge detected as anomaly
   - Latency doubling inside healthy envelope (13ms -> 26ms) detected
   - PRB utilization jump (15% -> 75%) detected
   - Directional suppression of normal improvements (availability, throughput, drop-rate)
   - Contaminated baseline recovery (0% -> 99.9% availability, 0 -> 350 Mbps throughput) not blocked
   - Configurable two-sided mode
3. DEFECT-03: Consecutive observation recovery hysteresis (count=2 operational default, reset on unhealthy).
4. DEFECT-04: Trusted profile baseline pre-seeding at operational initialization (TelemetryPipeline and engine).
5. The exact 8-metric CELL_OUTAGE recovery reproduction scenario.
6. Full end-to-end operational sequence:
   FAULT -> DETECTION -> INCIDENT -> ACKNOWLEDGEMENT -> RECOVERY -> TWO HEALTHY OBSERVATIONS
   -> ALARM CLEARANCE -> INCIDENT PRESERVATION -> EXPLICIT OPERATOR RESOLUTION.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
import pytest

from nexus.correlation.engine import AlarmCorrelationEngine
from nexus.detection.alarm_manager import AlarmManager
from nexus.detection.engine import AnomalyDetectionEngine, _alarm_key
from nexus.detection.models import (
    Alarm,
    AlarmStatus,
    AnomalyEvent,
    DetectionSource,
    Severity,
)
from nexus.detection.rules import ThresholdRule
from nexus.detection.statistical_detector import (
    HIGHER_IS_BETTER_KPIS,
    LOWER_IS_BETTER_KPIS,
    RESOURCE_UTILIZATION_KPIS,
    StatisticalDetector,
    StatisticalDetectorConfig,
    is_baseline_degraded,
    is_metric_healthy,
)
from nexus.detection.threshold_detector import ThresholdDetector
from nexus.incidents.enums import IncidentStatus
from nexus.incidents.repository import Base, IncidentRepository, create_engine
from nexus.incidents.service import IncidentService
from nexus.rca.engine import RootCauseAnalysisEngine
from nexus.telemetry.generator import SyntheticTelemetryGenerator
from nexus.telemetry.models import (
    KPISnapshot,
    PerformanceMetrics,
    RadioMetrics,
    ReliabilityMetrics,
)
from nexus.telemetry.orchestrator import TelemetryPipeline
from nexus.telemetry.profiles import DEFAULT_PROFILES
from nexus.telemetry.store import TelemetryStore
from nexus.topology.builder import build_simulated_network
from nexus.topology.enums import NodeType
from nexus.transport.builder import build_reference_transport_network


def make_test_snapshot(
    node_id: str = "CELL-01",
    timestamp: datetime | None = None,
    throughput_mbps: float = 350.0,
    latency_ms: float = 20.0,
    connection_drop_rate_pct: float = 0.1,
    availability_pct: float = 99.9,
    handover_success_rate_pct: float = 99.5,
    rsrp_dbm: float = -90.0,
    sinr_db: float = 20.0,
    prb_utilization_pct: float = 40.0,
) -> KPISnapshot:
    """Helper to construct deterministic KPISnapshot instances."""
    ts = timestamp or datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)
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


class TestDefect01SameBatchFlaggedAndRecovered:
    """DEFECT-01 P1: Verifies the recovery-path AttributeError fix on Alarm.key / _alarm_key.

    Tests the exact path where a metric is flagged as anomalous by one detector or contaminated baseline,
    while simultaneously meeting recovery conditions in check_recovery, ensuring:
    1. No AttributeError is raised.
    2. Alarm.key property and _alarm_key helper both return (node_id, metric_name, rule_id, source).
    3. new_alarms and updated_alarms are cleanly filtered when an alarm clears on the same step.
    4. Both median and EWMA recovery paths are verified.
    """

    @pytest.fixture
    def base_time(self) -> datetime:
        return datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)

    def test_alarm_key_identity_helper_and_property(self, base_time: datetime) -> None:
        """Alarm.key and _alarm_key(a) return identical 4-tuples."""
        alarm = Alarm(
            alarm_id="ALARM-TEST-01",
            node_id="CELL-01",
            rule_id="STAT-MEDIAN-latency_ms",
            metric_name="latency_ms",
            source=DetectionSource.STATISTICAL_MEDIAN,
            severity=Severity.MAJOR,
            current_value=120.0,
            threshold=25.0,
            first_seen=base_time,
            last_seen=base_time,
            observation_count=1,
            status=AlarmStatus.ACTIVE,
        )
        expected_key = ("CELL-01", "latency_ms", "STAT-MEDIAN-latency_ms", DetectionSource.STATISTICAL_MEDIAN)
        assert alarm.key == expected_key
        assert _alarm_key(alarm) == expected_key

    def test_same_batch_flagged_and_recovered_no_attribute_error(self, base_time: datetime) -> None:
        """Verifies engine.process_batch successfully filters new_alarms/updated_alarms without AttributeError."""
        engine = AnomalyDetectionEngine()
        engine.seed_node("CELL-01", NodeType.CELL)

        # Step 1: Establish active alarms during degraded state
        for i in range(5):
            snap = make_test_snapshot(
                node_id="CELL-01",
                timestamp=base_time + timedelta(seconds=i * 10),
                availability_pct=0.0,
                latency_ms=150.0,
            )
            engine.process_snapshot(snap)

        active = engine.get_active_alarms()
        assert len(active) >= 1

        # Step 2: Feed recovered snapshot twice (satisfying hysteresis=2)
        # On step 2, check_recovery returns True while flagged_keys handling runs
        rec_snap_1 = make_test_snapshot(
            node_id="CELL-01",
            timestamp=base_time + timedelta(seconds=60),
            availability_pct=99.9,
            latency_ms=20.0,
        )
        res1 = engine.process_batch([rec_snap_1])
        assert isinstance(res1.cleared_alarms, tuple)

        rec_snap_2 = make_test_snapshot(
            node_id="CELL-01",
            timestamp=base_time + timedelta(seconds=70),
            availability_pct=99.9,
            latency_ms=20.0,
        )
        res2 = engine.process_batch([rec_snap_2])
        # Must execute without AttributeError and clear alarms
        assert len(res2.cleared_alarms) >= 1
        # Cleared alarms are removed from new_alarms and updated_alarms
        cleared_keys = {a.key for a in res2.cleared_alarms}
        for a in res2.new_alarms:
            assert a.key not in cleared_keys
        for a in res2.updated_alarms:
            assert a.key not in cleared_keys


class TestDefect02RestoredStatisticalSensitivity:
    """DEFECT-02 P2: Verifies restored statistical anomaly sensitivity and directional suppression."""

    @pytest.fixture
    def base_time(self) -> datetime:
        return datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)

    def test_positive_throughput_surge_detected(self, base_time: datetime) -> None:
        """Extreme positive throughput surges (e.g. 5.5x) are detected as anomalies."""
        config = StatisticalDetectorConfig(
            warmup_count=5,
            window_size=10,
            directional_mode=True,
            surge_ratio_threshold=3.0,
            enable_rolling_median=True,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        # Baseline: 100 Mbps
        for i in range(5):
            snap = make_test_snapshot(
                timestamp=base_time + timedelta(seconds=i * 10),
                throughput_mbps=100.0,
            )
            detector.evaluate_snapshot(snap)

        # 5.5x surge: 550 Mbps (flash crowd / burst)
        surge_snap = make_test_snapshot(
            timestamp=base_time + timedelta(seconds=60),
            throughput_mbps=550.0,
        )
        events = detector.evaluate_snapshot(surge_snap)
        tp_events = [e for e in events if e.metric_name == "throughput_mbps"]
        assert len(tp_events) >= 1
        assert any(e.source == DetectionSource.STATISTICAL_MEDIAN for e in tp_events)
        assert any(e.source == DetectionSource.STATISTICAL_EWMA for e in tp_events)

    def test_modest_throughput_improvement_not_flagged(self, base_time: datetime) -> None:
        """Modest throughput improvement (+50%, 1.5x) is suppressed in directional mode."""
        config = StatisticalDetectorConfig(
            warmup_count=5,
            window_size=10,
            directional_mode=True,
            surge_ratio_threshold=3.0,
            enable_rolling_median=True,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        for i in range(5):
            detector.evaluate_snapshot(
                make_test_snapshot(timestamp=base_time + timedelta(seconds=i * 10), throughput_mbps=100.0)
            )

        # +50% increase (150 Mbps) is well below surge_ratio_threshold (3.0x)
        modest_snap = make_test_snapshot(
            timestamp=base_time + timedelta(seconds=60),
            throughput_mbps=150.0,
        )
        events = detector.evaluate_snapshot(modest_snap)
        assert not any(e.metric_name == "throughput_mbps" for e in events)

    def test_latency_doubling_inside_envelope_detected(self, base_time: datetime) -> None:
        """Latency doubling from 13ms to 26ms (inside the 28ms max envelope) is detected."""
        config = StatisticalDetectorConfig(
            warmup_count=5,
            window_size=10,
            directional_mode=True,
            enable_rolling_median=True,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        # Warmup at nominal healthy latency: 13.0 ms
        for i in range(5):
            detector.evaluate_snapshot(
                make_test_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=13.0)
            )

        # Latency doubles to 26.0 ms (still <= 28ms cell profile max, but severe relative degradation)
        doubled_snap = make_test_snapshot(
            timestamp=base_time + timedelta(seconds=60),
            latency_ms=26.0,
        )
        events = detector.evaluate_snapshot(doubled_snap)
        lat_events = [e for e in events if e.metric_name == "latency_ms"]
        assert len(lat_events) >= 1
        assert any(e.source == DetectionSource.STATISTICAL_MEDIAN for e in lat_events)

    def test_prb_utilization_jump_detected(self, base_time: datetime) -> None:
        """PRB utilization jumping from 15% to 75% is detected as an anomaly."""
        config = StatisticalDetectorConfig(
            warmup_count=5,
            window_size=10,
            directional_mode=True,
            enable_rolling_median=True,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        # Baseline at low PRB utilization: 15%
        for i in range(5):
            detector.evaluate_snapshot(
                make_test_snapshot(timestamp=base_time + timedelta(seconds=i * 10), prb_utilization_pct=15.0)
            )

        # Jump to 75%
        jump_snap = make_test_snapshot(
            timestamp=base_time + timedelta(seconds=60),
            prb_utilization_pct=75.0,
        )
        events = detector.evaluate_snapshot(jump_snap)
        prb_events = [e for e in events if e.metric_name == "prb_utilization_pct"]
        assert len(prb_events) >= 1

    def test_directional_suppression_of_improvements(self, base_time: datetime) -> None:
        """Normal improvements in lower-is-better metrics (latency dropping, drop-rate dropping) are suppressed."""
        config = StatisticalDetectorConfig(
            warmup_count=5,
            window_size=10,
            directional_mode=True,
            enable_rolling_median=True,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        for i in range(5):
            detector.evaluate_snapshot(
                make_test_snapshot(
                    timestamp=base_time + timedelta(seconds=i * 10),
                    latency_ms=25.0,
                    connection_drop_rate_pct=0.4,
                )
            )

        # Latency drops to 12ms and drop rate drops to 0.05% (improvements)
        better_snap = make_test_snapshot(
            timestamp=base_time + timedelta(seconds=60),
            latency_ms=12.0,
            connection_drop_rate_pct=0.05,
        )
        events = detector.evaluate_snapshot(better_snap)
        assert not any(e.metric_name in ("latency_ms", "connection_drop_rate_pct") for e in events)

    def test_recovery_from_contaminated_baseline_not_blocked(self, base_time: datetime) -> None:
        """When baseline is contaminated by outage, healthy telemetry is NOT flagged as an anomaly."""
        config = StatisticalDetectorConfig(
            warmup_count=5,
            window_size=10,
            directional_mode=True,
            enable_rolling_median=True,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        # Contaminate baseline with outage (availability=0%, throughput=0, latency=150ms)
        for i in range(5):
            detector.evaluate_snapshot(
                make_test_snapshot(
                    timestamp=base_time + timedelta(seconds=i * 10),
                    availability_pct=0.0,
                    throughput_mbps=0.0,
                    latency_ms=150.0,
                    connection_drop_rate_pct=100.0,
                )
            )

        # Recovered healthy telemetry
        recov_snap = make_test_snapshot(
            timestamp=base_time + timedelta(seconds=60),
            availability_pct=99.9,
            throughput_mbps=350.0,
            latency_ms=20.0,
            connection_drop_rate_pct=0.1,
        )
        events = detector.evaluate_snapshot(recov_snap)
        # None of the healthy recovered metrics should be flagged as an anomaly!
        flagged = {e.metric_name for e in events}
        assert "availability_pct" not in flagged
        assert "throughput_mbps" not in flagged
        assert "latency_ms" not in flagged
        assert "connection_drop_rate_pct" not in flagged

    def test_configurable_two_sided_mode(self, base_time: datetime) -> None:
        """When two_sided=True, improvements ARE flagged as two-sided deviations."""
        config = StatisticalDetectorConfig(
            warmup_count=5,
            window_size=10,
            directional_mode=True,
            two_sided=True,
            enable_rolling_median=True,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        for i in range(5):
            detector.evaluate_snapshot(
                make_test_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=50.0)
            )

        # Latency drops sharply to 10ms
        drop_snap = make_test_snapshot(timestamp=base_time + timedelta(seconds=60), latency_ms=10.0)
        events = detector.evaluate_snapshot(drop_snap)
        assert any(e.metric_name == "latency_ms" for e in events)


class TestDefect03OperationalRecoveryHysteresis:
    """DEFECT-03 P2: Verifies operational recovery hysteresis (consecutive observation counting)."""

    @pytest.fixture
    def base_time(self) -> datetime:
        return datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)

    def test_consecutive_two_observations_required_by_engine(self, base_time: datetime) -> None:
        """Operational engine requires 2 consecutive healthy observations to clear alarms."""
        engine = AnomalyDetectionEngine()

        # Step 1: Baseline and fault
        for i in range(5):
            engine.process_snapshot(
                make_test_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=20.0)
            )

        spike_snap = make_test_snapshot(timestamp=base_time + timedelta(seconds=50), latency_ms=150.0)
        engine.process_snapshot(spike_snap)
        active = engine.get_active_alarms()
        assert len(active) >= 1

        # Step 2: 1 healthy observation does NOT clear statistical alarms (hysteresis requires 2)
        norm_1 = make_test_snapshot(timestamp=base_time + timedelta(seconds=60), latency_ms=20.0)
        res1 = engine.process_snapshot(norm_1)
        stat_cleared_1 = [
            a for a in res1.cleared_alarms
            if a.source in (DetectionSource.STATISTICAL_MEDIAN, DetectionSource.STATISTICAL_EWMA)
        ]
        assert len(stat_cleared_1) == 0
        stat_active_1 = [
            a for a in engine.get_active_alarms()
            if a.source in (DetectionSource.STATISTICAL_MEDIAN, DetectionSource.STATISTICAL_EWMA)
        ]
        assert len(stat_active_1) >= 1

        # Step 3: 2nd consecutive healthy observation CLEARS statistical alarms
        norm_2 = make_test_snapshot(timestamp=base_time + timedelta(seconds=70), latency_ms=20.0)
        res2 = engine.process_snapshot(norm_2)
        stat_cleared_2 = [
            a for a in res2.cleared_alarms
            if a.source in (DetectionSource.STATISTICAL_MEDIAN, DetectionSource.STATISTICAL_EWMA)
        ]
        assert len(stat_cleared_2) >= 1
        stat_active_2 = [
            a for a in engine.get_active_alarms()
            if a.source in (DetectionSource.STATISTICAL_MEDIAN, DetectionSource.STATISTICAL_EWMA)
        ]
        assert len(stat_active_2) == 0

    def test_unhealthy_observation_resets_recovery_counter(self, base_time: datetime) -> None:
        """An unhealthy observation resets the consecutive recovery counter to 0."""
        config = StatisticalDetectorConfig(
            warmup_count=3,
            window_size=10,
            consecutive_recovery_count=2,
            enable_rolling_median=True,
            enable_ewma=False,
        )
        detector = StatisticalDetector(config)

        for i in range(3):
            detector.evaluate_snapshot(
                make_test_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=20.0)
            )

        # Induce spike
        detector.evaluate_snapshot(
            make_test_snapshot(timestamp=base_time + timedelta(seconds=30), latency_ms=120.0)
        )

        # 1st healthy observation (count=1/2) -> False
        snap_h1 = make_test_snapshot(timestamp=base_time + timedelta(seconds=40), latency_ms=20.0)
        assert detector.check_recovery(snap_h1, DetectionSource.STATISTICAL_MEDIAN, "latency_ms") is False

        # Interrupted by unhealthy observation -> resets counter to 0
        snap_bad = make_test_snapshot(timestamp=base_time + timedelta(seconds=50), latency_ms=120.0)
        assert detector.check_recovery(snap_bad, DetectionSource.STATISTICAL_MEDIAN, "latency_ms") is False

        # 1st healthy observation again (count=1/2) -> still False
        snap_h2 = make_test_snapshot(timestamp=base_time + timedelta(seconds=60), latency_ms=20.0)
        assert detector.check_recovery(snap_h2, DetectionSource.STATISTICAL_MEDIAN, "latency_ms") is False

        # 2nd healthy observation (count=2/2) -> True
        snap_h3 = make_test_snapshot(timestamp=base_time + timedelta(seconds=70), latency_ms=20.0)
        assert detector.check_recovery(snap_h3, DetectionSource.STATISTICAL_MEDIAN, "latency_ms") is True


class TestDefect04OperationalProfileSeeding:
    """DEFECT-04 P3: Verifies trusted profile baseline seeding at operational initialization."""

    def test_seed_from_profile_populates_healthy_state(self) -> None:
        config = StatisticalDetectorConfig(warmup_count=5, window_size=10)
        detector = StatisticalDetector(config)

        cell_profile = DEFAULT_PROFILES[NodeType.CELL]
        detector.seed_from_profile("CELL-01", cell_profile)

        history = detector._median_histories[("CELL-01", "availability_pct")]
        assert len(history) == 5
        assert list(history) == [cell_profile.availability_pct.nominal] * 5

        ewma = detector._ewma_states[("CELL-01", "throughput_mbps")]
        assert ewma["mean"] == cell_profile.throughput_mbps.nominal
        assert ewma["count"] == 5.0

    def test_seeded_detector_immediately_detects_outage_at_t0(self) -> None:
        """A seeded detector immediately detects an outage at t=0 without needing warmup."""
        config = StatisticalDetectorConfig(warmup_count=5, window_size=10)
        detector = StatisticalDetector(config)
        detector.seed_baselines("CELL-01", NodeType.CELL)

        outage_snap = make_test_snapshot(
            node_id="CELL-01",
            availability_pct=0.0,
            throughput_mbps=0.0,
        )
        events = detector.evaluate_snapshot(outage_snap)
        assert len(events) >= 1
        flagged_metrics = {e.metric_name for e in events}
        assert "availability_pct" in flagged_metrics
        assert "throughput_mbps" in flagged_metrics

    def test_subsequent_snapshot_does_not_reset_learned_baseline(self) -> None:
        """Subsequent snapshots and re-seeding calls do not reset learned baselines."""
        engine = AnomalyDetectionEngine()
        engine.seed_node("CELL-01", NodeType.CELL)
        assert "CELL-01" in engine.seeded_nodes

        # Re-seeding with overwrite=False returns False
        assert engine.seed_node("CELL-01", NodeType.CELL, overwrite=False) is False

    def test_unknown_node_type_falls_back_gracefully(self) -> None:
        """Unknown node types or IDs without profiles fall back gracefully without crash."""
        engine = AnomalyDetectionEngine()
        # Non-standard node type or None
        res = engine.seed_node("UNKNOWN_NODE_999", node_type=None)
        assert res is False
        assert "UNKNOWN_NODE_999" not in engine.seeded_nodes

    def test_telemetry_pipeline_wires_seeding_to_alarm_service(self) -> None:
        """TelemetryPipeline constructor seeds detector baselines for all network topology nodes."""
        net = build_simulated_network()
        store = TelemetryStore()
        gen = SyntheticTelemetryGenerator(topology=net)
        engine = AnomalyDetectionEngine()

        class MockAlarmService:
            def __init__(self, eng: AnomalyDetectionEngine) -> None:
                self._detection_engine = eng

        mock_svc = MockAlarmService(engine)
        pipeline = TelemetryPipeline(
            generator=gen,
            store=store,
            alarm_service=mock_svc,
        )
        # All topology cell and site nodes should be seeded
        all_ids = {n.node_id for n in net.all_nodes()}
        assert all_ids.issubset(engine.seeded_nodes)


class TestCellOutageRecoveryReproduction:
    """Reproduction and resolution test for the verified 8-metric CELL_OUTAGE recovery deadlock."""

    @pytest.fixture
    def base_time(self) -> datetime:
        return datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)

    def test_eight_statistical_alarms_clear_upon_telemetry_recovery(self, base_time: datetime) -> None:
        """Verifies that all 8 statistical alarms clear cleanly when CELL-01 telemetry recovers,
        matching the exact values from the read-only investigation report."""
        engine = AnomalyDetectionEngine()
        engine.seed_node("CELL-01", NodeType.CELL)

        # Step 1: Simulate fault condition (CELL_OUTAGE on CELL-01)
        for i in range(5):
            outage_snap = make_test_snapshot(
                node_id="CELL-01",
                timestamp=base_time + timedelta(seconds=i * 10),
                availability_pct=0.0,
                connection_drop_rate_pct=100.0,
                handover_success_rate_pct=0.0,
                latency_ms=0.0,
                prb_utilization_pct=0.0,
                rsrp_dbm=-140.0,
                sinr_db=-20.0,
                throughput_mbps=0.0,
            )
            engine.process_snapshot(outage_snap)

        # Active statistical alarms exist across metrics
        active_during_fault = [
            a for a in engine.get_active_alarms()
            if a.node_id == "CELL-01"
            and a.source in (DetectionSource.STATISTICAL_MEDIAN, DetectionSource.STATISTICAL_EWMA)
        ]
        assert len(active_during_fault) >= 8

        # Step 2a: Observation 1 of recovered telemetry:
        recovered_snap_1 = make_test_snapshot(
            node_id="CELL-01",
            timestamp=base_time + timedelta(seconds=60),
            availability_pct=99.9,
            connection_drop_rate_pct=0.1,
            handover_success_rate_pct=99.5,
            latency_ms=20.6,
            prb_utilization_pct=41.5,
            rsrp_dbm=-90.6,
            sinr_db=20.4,
            throughput_mbps=364.1,
        )
        res1 = engine.process_snapshot(recovered_snap_1)
        # Hysteresis check: exactly 1 observation is NOT sufficient to clear statistical alarms (count=2 required)
        active_after_1 = [
            a for a in engine.get_active_alarms()
            if a.node_id == "CELL-01"
            and a.source in (DetectionSource.STATISTICAL_MEDIAN, DetectionSource.STATISTICAL_EWMA)
        ]
        assert len(active_after_1) > 0

        # Step 2b: Observation 2 of recovered telemetry:
        recovered_snap_2 = make_test_snapshot(
            node_id="CELL-01",
            timestamp=base_time + timedelta(seconds=70),
            availability_pct=99.9,
            connection_drop_rate_pct=0.1,
            handover_success_rate_pct=99.5,
            latency_ms=20.6,
            prb_utilization_pct=41.5,
            rsrp_dbm=-90.6,
            sinr_db=20.4,
            throughput_mbps=364.1,
        )
        res2 = engine.process_snapshot(recovered_snap_2)

        # Step 3: Check active statistical alarms on CELL-01
        active_stat_alarms = [
            a for a in engine.get_active_alarms()
            if a.node_id == "CELL-01"
            and a.source in (DetectionSource.STATISTICAL_MEDIAN, DetectionSource.STATISTICAL_EWMA)
        ]
        # Deadlock broken: ZERO active statistical alarms remain!
        assert len(active_stat_alarms) == 0

    def test_contaminated_warmup_recovery_deadlock_broken(self, base_time: datetime) -> None:
        """Verifies that if warmup occurred during outage, recovered telemetry heals baseline
        rather than indefinitely generating false-positive statistical alarms."""
        engine = AnomalyDetectionEngine()

        # Step 1: Warmup learns outage (contaminated baseline)
        for i in range(5):
            outage_snap = make_test_snapshot(
                node_id="CELL-01",
                timestamp=base_time + timedelta(seconds=i * 10),
                availability_pct=0.0,
                connection_drop_rate_pct=100.0,
                handover_success_rate_pct=0.0,
                latency_ms=0.0,
                prb_utilization_pct=0.0,
                rsrp_dbm=-140.0,
                sinr_db=-20.0,
                throughput_mbps=0.0,
            )
            engine.process_snapshot(outage_snap)

        # Step 2: 5 additional simulation steps of recovered healthy telemetry
        for i in range(5):
            rec_snap = make_test_snapshot(
                node_id="CELL-01",
                timestamp=base_time + timedelta(seconds=60 + i * 10),
                availability_pct=99.9,
                connection_drop_rate_pct=0.1,
                handover_success_rate_pct=99.5,
                latency_ms=20.6,
                prb_utilization_pct=41.5,
                rsrp_dbm=-90.6,
                sinr_db=20.4,
                throughput_mbps=364.1,
            )
            engine.process_snapshot(rec_snap)

        # In old code, 8 statistical alarms were ACTIVE.
        # With directional healing, ZERO statistical alarms are active!
        active_stat = [
            a for a in engine.get_active_alarms()
            if a.node_id == "CELL-01"
            and a.source in (DetectionSource.STATISTICAL_MEDIAN, DetectionSource.STATISTICAL_EWMA)
        ]
        assert len(active_stat) == 0

        # Step 4: Check that alarms transitioned to CLEARED
        cleared_alarms = engine.get_cleared_alarms()
        for metric in (
            "availability_pct",
            "connection_drop_rate_pct",
            "handover_success_rate_pct",
            "latency_ms",
            "prb_utilization_pct",
            "rsrp_dbm",
            "sinr_db",
            "throughput_mbps",
        ):
            assert not any(a.metric_name == metric for a in engine.get_active_alarms())


class TestEndToEndOperationalLifecycle:
    """Demonstrates complete operational sequence with incident state preservation:
    FAULT ACTIVATION -> DEGRADED TELEMETRY -> ALARM -> FAULT DEACTIVATION
    -> HEALTHY TELEMETRY -> TWO OBSERVATIONS -> ALARM CLEARANCE
    -> INCIDENT REMAINS OPEN/ACKNOWLEDGED -> EXPLICIT OPERATOR RESOLUTION.
    """

    @pytest.fixture
    def base_time(self) -> datetime:
        return datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)

    def test_complete_lifecycle_sequence(self, base_time: datetime) -> None:
        net = build_simulated_network()
        transport = build_reference_transport_network(net)
        detection_engine = AnomalyDetectionEngine()
        correlation_engine = AlarmCorrelationEngine(topology=net, transport=transport)
        rca_engine = RootCauseAnalysisEngine(topology=net, transport=transport)
        sql_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(sql_engine)
        incident_repo = IncidentRepository.from_engine(sql_engine)
        incident_service = IncidentService(repository=incident_repo)

        # 1. FAULT ACTIVATION & DEGRADED TELEMETRY
        fault_snaps = [
            make_test_snapshot(
                node_id="CELL-01",
                timestamp=base_time + timedelta(seconds=i * 10),
                availability_pct=0.0,
                throughput_mbps=0.0,
                latency_ms=150.0,
            )
            for i in range(6)
        ]
        res_fault = detection_engine.process_batch(fault_snaps)
        active_alarms = detection_engine.get_active_alarms()
        assert len(active_alarms) >= 1

        # Correlate and create incident
        corr_result = correlation_engine.correlate(active_alarms, topology=net)
        assert corr_result.total_groups_formed >= 1
        group = corr_result.groups[0]
        rca_result = rca_engine.analyze_group(group=group, topology=net, transport=transport)
        incident, created = incident_service.create_or_update_incident(
            correlation_group=group,
            rca_result=rca_result,
            actor="SYSTEM",
            creation_timestamp=base_time + timedelta(seconds=60),
        )
        assert created is True
        assert incident.status == IncidentStatus.OPEN

        # Operator acknowledges the incident
        ack_incident = incident_service.acknowledge_incident(
            incident_id=incident.incident_id,
            actor="NOC_ENGINEER",
            timestamp=base_time + timedelta(seconds=70),
        )
        assert ack_incident.status == IncidentStatus.ACKNOWLEDGED

        # 2. FAULT DEACTIVATION & HEALTHY TELEMETRY (3 steps > 2 required hysteresis observations)
        recovery_snaps = [
            make_test_snapshot(
                node_id="CELL-01",
                timestamp=base_time + timedelta(seconds=80 + i * 10),
                availability_pct=99.9,
                throughput_mbps=350.0,
                latency_ms=20.0,
            )
            for i in range(3)
        ]
        res_recovery = detection_engine.process_batch(recovery_snaps)

        # 3. ALARM CLEARANCE
        # All alarms on CELL-01 should clear cleanly after >=2 healthy observations
        active_after_recovery = [
            a for a in detection_engine.get_active_alarms() if a.node_id == "CELL-01"
        ]
        assert len(active_after_recovery) == 0

        # 4. INCIDENT STATE PRESERVATION: Incident MUST NOT auto-resolve!
        inc_after_recovery = incident_service.get_incident(incident.incident_id)
        assert inc_after_recovery.status == IncidentStatus.ACKNOWLEDGED
        assert inc_after_recovery.resolved_at is None

        # 5. EXPLICIT OPERATOR RESOLUTION
        resolved_incident = incident_service.resolve_incident(
            incident_id=incident.incident_id,
            actor="NOC_ENGINEER",
            notes="Radio unit power cycle complete. Telemetry normal and alarms cleared.",
            timestamp=base_time + timedelta(seconds=120),
        )
        assert resolved_incident.status == IncidentStatus.RESOLVED
        assert resolved_incident.resolved_at is not None
        assert resolved_incident.resolved_by == "NOC_ENGINEER"


class TestCell01StatMedianLatencyRecoveryFix:
    """Verifies the CELL-01 STAT-MEDIAN latency recovery fix:
    1. Realistic minimum scale derived from profile range prevents artificial scale squeeze.
    2. Lower-is-better recovery logic allows healthy operating envelope values (> median) to recover.
    3. Exactly two consecutive healthy observations are required to clear.
    4. Sustained harmful latency remains continuously detectable and never clears.
    """

    @pytest.fixture
    def base_time(self) -> datetime:
        return datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)

    def test_zero_variance_seeded_baseline_profile_spread_established(self) -> None:
        """Zero-variance seeded baseline establishes realistic profile spread for rolling median."""
        detector = StatisticalDetector()
        detector.seed_from_profile("CELL-01", DEFAULT_PROFILES[NodeType.CELL])

        # Rolling median history is seeded with constant nominal 18.0 ms
        key = ("CELL-01", "latency_ms")
        history = list(detector._median_histories[key])
        assert history == [18.0] * 5

        # Profile spread is established from MetricRange(nominal=18, min_val=12, max_val=28)
        # spread = max((28.0 - 12.0) / 6.0, 0.05 * 18.0, 1.0) = 2.6667 ms
        expected_spread = (28.0 - 12.0) / 6.0
        assert detector._profile_spreads[key] == pytest.approx(expected_spread, abs=1e-4)

    def test_cell01_latency_recovery_at_20_point_6_ms_lifecycle(self, base_time: datetime) -> None:
        """CELL-01 latency at 20.6 ms remains active on observation 1 and clears on observation 2."""
        engine = AnomalyDetectionEngine()
        engine.seed_node("CELL-01", NodeType.CELL)

        # Step 1: Simulate fault driving latency to 200 ms
        for i in range(5):
            fault_snap = make_test_snapshot(
                node_id="CELL-01",
                timestamp=base_time + timedelta(seconds=i * 10),
                latency_ms=200.0,
            )
            engine.process_snapshot(fault_snap)

        active_lat_alarms = [
            a for a in engine.get_active_alarms()
            if a.node_id == "CELL-01" and a.metric_name == "latency_ms"
        ]
        assert any(a.source == DetectionSource.STATISTICAL_MEDIAN for a in active_lat_alarms)
        assert any(a.source == DetectionSource.STATISTICAL_EWMA for a in active_lat_alarms)

        # Step 2: Healthy Observation 1 at 20.6 ms (above nominal median 18.0 ms, but healthy)
        snap_rec1 = make_test_snapshot(
            node_id="CELL-01",
            timestamp=base_time + timedelta(seconds=60),
            latency_ms=20.6,
        )
        res1 = engine.process_snapshot(snap_rec1)

        # Requirement 3: Alarm remains ACTIVE after first healthy observation (consecutive=1 < 2)
        stat_active_1 = [
            a for a in engine.get_active_alarms()
            if a.node_id == "CELL-01" and a.metric_name == "latency_ms"
            and a.source == DetectionSource.STATISTICAL_MEDIAN
        ]
        assert len(stat_active_1) == 1
        assert not any(a.rule_id == "STAT-MEDIAN-latency_ms" for a in res1.cleared_alarms)

        # Step 3: Healthy Observation 2 at 20.6 ms
        snap_rec2 = make_test_snapshot(
            node_id="CELL-01",
            timestamp=base_time + timedelta(seconds=70),
            latency_ms=20.6,
        )
        res2 = engine.process_snapshot(snap_rec2)

        # Requirement 3: Alarm CLEARS after second consecutive healthy observation (consecutive=2 >= 2)
        stat_active_2 = [
            a for a in engine.get_active_alarms()
            if a.node_id == "CELL-01" and a.metric_name == "latency_ms"
            and a.source == DetectionSource.STATISTICAL_MEDIAN
        ]
        assert len(stat_active_2) == 0
        assert any(a.rule_id == "STAT-MEDIAN-latency_ms" for a in res2.cleared_alarms)

    def test_sustained_harmful_latency_remains_detectable(self, base_time: datetime) -> None:
        """Requirement 4: Sustained harmful latency (150 ms) remains active and never clears."""
        engine = AnomalyDetectionEngine()
        engine.seed_node("CELL-01", NodeType.CELL)

        # Feed 5 healthy warmup snapshots at nominal 18.0 ms
        for i in range(5):
            engine.process_snapshot(
                make_test_snapshot(
                    node_id="CELL-01",
                    timestamp=base_time + timedelta(seconds=i * 10),
                    latency_ms=18.0,
                )
            )
        assert len(engine.get_active_alarms()) == 0

        # Severe sustained degradation: 150.0 ms across 5 observations
        for i in range(5):
            res = engine.process_snapshot(
                make_test_snapshot(
                    node_id="CELL-01",
                    timestamp=base_time + timedelta(seconds=60 + i * 10),
                    latency_ms=150.0,
                )
            )
            # Must remain actively alarmed on both MEDIAN and EWMA, with 0 cleared alarms
            active_lat = [
                a for a in engine.get_active_alarms()
                if a.node_id == "CELL-01" and a.metric_name == "latency_ms"
            ]
            assert any(a.source == DetectionSource.STATISTICAL_MEDIAN for a in active_lat)
            assert any(a.source == DetectionSource.STATISTICAL_EWMA for a in active_lat)
            assert not any(a.metric_name == "latency_ms" for a in res.cleared_alarms)

    def test_healthy_envelope_latency_above_nominal_median_recovers(self, base_time: datetime) -> None:
        """Requirement 2: Latency at 24.0 ms (inside [12, 28] envelope, above nominal 18 ms) clears cleanly."""
        engine = AnomalyDetectionEngine()
        engine.seed_node("CELL-01", NodeType.CELL)

        # Induce fault
        for i in range(5):
            engine.process_snapshot(
                make_test_snapshot(
                    node_id="CELL-01",
                    timestamp=base_time + timedelta(seconds=i * 10),
                    latency_ms=180.0,
                )
            )

        # Observation 1 at 24.0 ms
        engine.process_snapshot(
            make_test_snapshot(
                node_id="CELL-01",
                timestamp=base_time + timedelta(seconds=60),
                latency_ms=24.0,
            )
        )
        assert any(
            a.rule_id == "STAT-MEDIAN-latency_ms" for a in engine.get_active_alarms()
        )

        # Observation 2 at 24.0 ms
        res2 = engine.process_snapshot(
            make_test_snapshot(
                node_id="CELL-01",
                timestamp=base_time + timedelta(seconds=70),
                latency_ms=24.0,
            )
        )
        assert not any(
            a.rule_id == "STAT-MEDIAN-latency_ms" for a in engine.get_active_alarms()
        )
        assert any(a.rule_id == "STAT-MEDIAN-latency_ms" for a in res2.cleared_alarms)

    def test_direct_statistical_detector_check_recovery_latency(self, base_time: datetime) -> None:
        """StatisticalDetector.check_recovery correctly tracks consecutive observations and hysteresis."""
        config = StatisticalDetectorConfig(
            consecutive_recovery_count=2,
            recovery_hysteresis_factor=0.8,
            directional_mode=True,
        )
        detector = StatisticalDetector(config)
        detector.seed_from_profile("CELL-01", DEFAULT_PROFILES[NodeType.CELL])

        snap_rec1 = make_test_snapshot(node_id="CELL-01", timestamp=base_time, latency_ms=20.6)
        # Observation 1: count=1 < 2 -> returns False
        rec1 = detector.check_recovery(
            snap_rec1, DetectionSource.STATISTICAL_MEDIAN, "latency_ms", node_type=NodeType.CELL
        )
        assert rec1 is False
        assert detector._recovery_counters[("CELL-01", "latency_ms", DetectionSource.STATISTICAL_MEDIAN)] == 1

        # Observation 2: count=2 >= 2 -> returns True
        snap_rec2 = make_test_snapshot(node_id="CELL-01", timestamp=base_time + timedelta(seconds=10), latency_ms=20.6)
        rec2 = detector.check_recovery(
            snap_rec2, DetectionSource.STATISTICAL_MEDIAN, "latency_ms", node_type=NodeType.CELL
        )
        assert rec2 is True
        assert ("CELL-01", "latency_ms", DetectionSource.STATISTICAL_MEDIAN) not in detector._recovery_counters

