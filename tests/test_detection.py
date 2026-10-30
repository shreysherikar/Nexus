"""Unit and integration tests for NEXUS Anomaly Detection & Alarm Generation."""

from datetime import datetime, timedelta, timezone
from typing import Optional
import pytest

from nexus.detection import (
    Alarm,
    AlarmManager,
    AlarmStatus,
    AnomalyDetectionEngine,
    AnomalyEvent,
    ComparisonOperator,
    DetectionBatchResult,
    DetectionError,
    DetectionSource,
    DuplicateObservationError,
    InvalidAlarmStateError,
    InvalidDetectorConfigError,
    InvalidRuleError,
    Severity,
    StatisticalDetector,
    StatisticalDetectorConfig,
    TelemetryOrderError,
    ThresholdDetector,
    ThresholdRule,
    get_default_rules,
)
from nexus.telemetry import (
    KPISnapshot,
    PerformanceMetrics,
    RadioMetrics,
    ReliabilityMetrics,
    SyntheticTelemetryGenerator,
)
from nexus.topology import NodeType, Topology, build_simulated_network


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

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
    ts = timestamp or datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
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


def make_site_snapshot(
    node_id: str = "SITE-01",
    timestamp: Optional[datetime] = None,
    throughput_mbps: float = 300.0,
    latency_ms: float = 10.0,
    connection_drop_rate_pct: float = 0.2,
    availability_pct: float = 99.95,
) -> KPISnapshot:
    """Helper creating a valid non-cell (site) snapshot without radio metrics."""
    ts = timestamp or datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
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
        ),
        radio=None,
    )


# ---------------------------------------------------------------------------
# 1. Threshold Rule Model and Detector Tests
# ---------------------------------------------------------------------------

class TestThresholdRuleAndDetector:
    """Tests for threshold rule creation, validation, comparison operators, and recovery."""

    def test_default_rules_validity(self) -> None:
        rules = get_default_rules()
        assert len(rules) >= 6
        rule_ids = {r.rule_id for r in rules}
        assert len(rule_ids) == len(rules)

    def test_rule_validation_rejects_empty_id(self) -> None:
        with pytest.raises(InvalidRuleError, match="rule_id must be a non-empty string"):
            ThresholdRule("", "latency_ms", ComparisonOperator.GT, 80.0, Severity.MAJOR)

    def test_rule_validation_rejects_unknown_metric(self) -> None:
        with pytest.raises(InvalidRuleError, match="Invalid metric_name"):
            ThresholdRule("R1", "cpu_utilization", ComparisonOperator.GT, 80.0, Severity.MAJOR)

    @pytest.mark.parametrize("bad_thresh", [float("nan"), float("inf"), True, False, "80.0", None])
    def test_rule_validation_rejects_non_numeric_threshold(self, bad_thresh: object) -> None:
        with pytest.raises(InvalidRuleError):
            ThresholdRule("R1", "latency_ms", ComparisonOperator.GT, bad_thresh, Severity.MAJOR)  # type: ignore[arg-type]

    def test_hysteresis_validation_for_upper_bounds(self) -> None:
        # Operator GT: threshold = 80.0. clear_threshold must be <= 80.0.
        rule_valid = ThresholdRule("R1", "latency_ms", ComparisonOperator.GT, 80.0, Severity.MAJOR, clear_threshold=60.0)
        assert rule_valid.clear_threshold == 60.0

        # Inverted hysteresis: clear_threshold > threshold is invalid
        with pytest.raises(InvalidRuleError, match="clear_threshold.*must be <="):
            ThresholdRule("R2", "latency_ms", ComparisonOperator.GT, 80.0, Severity.MAJOR, clear_threshold=85.0)

    def test_hysteresis_validation_for_lower_bounds(self) -> None:
        # Operator LT: threshold = 95.0. clear_threshold must be >= 95.0.
        rule_valid = ThresholdRule("R1", "availability_pct", ComparisonOperator.LT, 95.0, Severity.CRITICAL, clear_threshold=98.0)
        assert rule_valid.clear_threshold == 98.0

        # Inverted hysteresis: clear_threshold < threshold is invalid
        with pytest.raises(InvalidRuleError, match="clear_threshold.*must be >="):
            ThresholdRule("R2", "availability_pct", ComparisonOperator.LT, 95.0, Severity.CRITICAL, clear_threshold=90.0)

    @pytest.mark.parametrize(
        "op,thresh,val,expected_breach",
        [
            (ComparisonOperator.GT, 50.0, 50.1, True),
            (ComparisonOperator.GT, 50.0, 50.0, False),
            (ComparisonOperator.GT, 50.0, 49.9, False),
            (ComparisonOperator.GTE, 50.0, 50.0, True),
            (ComparisonOperator.GTE, 50.0, 49.9, False),
            (ComparisonOperator.LT, 10.0, 9.9, True),
            (ComparisonOperator.LT, 10.0, 10.0, False),
            (ComparisonOperator.LT, 10.0, 10.1, False),
            (ComparisonOperator.LTE, 10.0, 10.0, True),
            (ComparisonOperator.LTE, 10.0, 10.1, False),
        ],
    )
    def test_comparison_operators(self, op: ComparisonOperator, thresh: float, val: float, expected_breach: bool) -> None:
        rule = ThresholdRule("TEST-OP", "latency_ms", op, thresh, Severity.WARNING)
        assert rule.evaluate(val) is expected_breach

    def test_node_type_filtering(self) -> None:
        cell_rule = ThresholdRule(
            "CELL-ONLY", "sinr_db", ComparisonOperator.LT, 5.0, Severity.MAJOR, node_types=frozenset({NodeType.CELL})
        )
        detector = ThresholdDetector([cell_rule])

        cell_snap = make_cell_snapshot(sinr_db=2.0)
        events_cell = detector.evaluate_snapshot(cell_snap, node_type=NodeType.CELL)
        assert len(events_cell) == 1
        assert events_cell[0].rule_id == "CELL-ONLY"

        # If evaluated against SITE node type, rule does not apply
        events_site = detector.evaluate_snapshot(cell_snap, node_type=NodeType.SITE)
        assert len(events_site) == 0

    def test_missing_metrics_do_not_cause_errors_or_false_alarms(self) -> None:
        # A site snapshot has no radio metrics
        site_snap = make_site_snapshot()
        detector = ThresholdDetector(get_default_rules())
        events = detector.evaluate_snapshot(site_snap, node_type=NodeType.SITE)
        # Normal site snapshot produces 0 events
        assert len(events) == 0

    def test_check_recovery_with_hysteresis(self) -> None:
        rule = ThresholdRule(
            "R-LAT", "latency_ms", ComparisonOperator.GT, 80.0, Severity.MAJOR, clear_threshold=60.0
        )
        detector = ThresholdDetector([rule])

        # At 85.0 ms: breached
        snap_breach = make_cell_snapshot(latency_ms=85.0)
        assert detector.check_recovery(snap_breach, "R-LAT") is False

        # At 70.0 ms: still in hysteresis band (neither breach nor recovery)
        snap_hysteresis = make_cell_snapshot(latency_ms=70.0)
        assert detector.check_recovery(snap_hysteresis, "R-LAT") is False

        # At 55.0 ms: <= 60.0 ms, recovered!
        snap_recovered = make_cell_snapshot(latency_ms=55.0)
        assert detector.check_recovery(snap_recovered, "R-LAT") is True

    def test_check_recovery_missing_metric_returns_none(self) -> None:
        rule = ThresholdRule("R-SINR", "sinr_db", ComparisonOperator.LT, 5.0, Severity.MAJOR)
        detector = ThresholdDetector([rule])
        site_snap = make_site_snapshot()  # no radio
        assert detector.check_recovery(site_snap, "R-SINR") is None


# ---------------------------------------------------------------------------
# 2. Statistical Detector Tests
# ---------------------------------------------------------------------------

class TestStatisticalDetector:
    """Tests for Rolling Median and EWMA baseline calculations, contamination prevention, and isolation."""

    def test_config_validation(self) -> None:
        with pytest.raises(InvalidDetectorConfigError, match="window_size"):
            StatisticalDetectorConfig(window_size=2)  # min 3

        with pytest.raises(InvalidDetectorConfigError, match="warmup_count"):
            StatisticalDetectorConfig(window_size=10, warmup_count=15)  # warm > win

        with pytest.raises(InvalidDetectorConfigError, match="ewma_alpha"):
            StatisticalDetectorConfig(ewma_alpha=1.5)  # alpha < 1.0

        with pytest.raises(InvalidDetectorConfigError, match="ewma_alpha"):
            StatisticalDetectorConfig(ewma_alpha=0.0)  # alpha > 0.0

        with pytest.raises(InvalidDetectorConfigError, match="median_deviation_threshold"):
            StatisticalDetectorConfig(median_deviation_threshold=float("nan"))

    def test_warmup_period_suppresses_alarms(self) -> None:
        config = StatisticalDetectorConfig(window_size=10, warmup_count=5)
        detector = StatisticalDetector(config)

        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(4):  # count 0, 1, 2, 3 < 5
            snap = make_cell_snapshot(timestamp=t + timedelta(seconds=i * 10), throughput_mbps=100.0)
            events = detector.evaluate_snapshot(snap)
            assert len(events) == 0

    def test_rolling_median_detects_sudden_spike(self) -> None:
        config = StatisticalDetectorConfig(
            window_size=10,
            warmup_count=5,
            median_deviation_threshold=3.0,
            enable_rolling_median=True,
            enable_ewma=False,
        )
        detector = StatisticalDetector(config)

        base_t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        # Establish stable latency baseline around 20 ms
        for i in range(8):
            val = 20.0 + (1.0 if i % 2 == 0 else -1.0)
            snap = make_cell_snapshot(timestamp=base_t + timedelta(seconds=i * 10), latency_ms=val)
            events = detector.evaluate_snapshot(snap)
            assert len(events) == 0

        # Sudden spike to 120 ms
        spike_snap = make_cell_snapshot(timestamp=base_t + timedelta(seconds=90), latency_ms=120.0)
        events = detector.evaluate_snapshot(spike_snap)
        assert len(events) >= 1
        lat_event = next(e for e in events if e.metric_name == "latency_ms")
        assert lat_event.source == DetectionSource.STATISTICAL_MEDIAN
        assert lat_event.current_value == 120.0
        assert lat_event.evidence["method"] == "rolling_median"

    def test_ewma_detects_sustained_shift(self) -> None:
        config = StatisticalDetectorConfig(
            window_size=10,
            warmup_count=5,
            ewma_alpha=0.25,
            ewma_sensitivity=3.0,
            enable_rolling_median=False,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        base_t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(8):
            val = 100.0 + (0.5 if i % 2 == 0 else -0.5)
            snap = make_cell_snapshot(timestamp=base_t + timedelta(seconds=i * 10), throughput_mbps=val)
            events = detector.evaluate_snapshot(snap)
            assert len(events) == 0

        # Throughput collapses to 10 Mbps
        drop_snap = make_cell_snapshot(timestamp=base_t + timedelta(seconds=90), throughput_mbps=10.0)
        events = detector.evaluate_snapshot(drop_snap)
        assert len(events) >= 1
        tp_event = next(e for e in events if e.metric_name == "throughput_mbps")
        assert tp_event.source == DetectionSource.STATISTICAL_EWMA
        assert tp_event.current_value == 10.0

    def test_gradual_degradation_detection(self) -> None:
        """EWMA detects gradual multi-step degradation away from baseline."""
        config = StatisticalDetectorConfig(
            window_size=15,
            warmup_count=5,
            ewma_alpha=0.1,  # slower alpha retains baseline memory
            ewma_sensitivity=3.0,
            enable_rolling_median=False,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)
        base_t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

        # Baseline: 5 samples at 100 Mbps
        for i in range(5):
            detector.evaluate_snapshot(make_cell_snapshot(timestamp=base_t + timedelta(seconds=i * 10), throughput_mbps=100.0))

        # Gradual degradation: 90, 80, 70, 60, 50, 40...
        flagged = False
        for i in range(1, 10):
            val = max(10.0, 100.0 - (i * 10.0))
            snap = make_cell_snapshot(timestamp=base_t + timedelta(seconds=(5 + i) * 10), throughput_mbps=val)
            events = detector.evaluate_snapshot(snap)
            if any(e.metric_name == "throughput_mbps" for e in events):
                flagged = True
                break

        assert flagged is True

    def test_contamination_prevention_excludes_anomalies_from_baseline(self) -> None:
        config = StatisticalDetectorConfig(
            window_size=5,
            warmup_count=3,
            median_deviation_threshold=2.5,
            enable_rolling_median=True,
            enable_ewma=False,
        )
        detector = StatisticalDetector(config)
        base_t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

        # Baseline: 3 samples of 50.0 ms
        for i in range(3):
            snap = make_cell_snapshot(timestamp=base_t + timedelta(seconds=i * 10), latency_ms=50.0)
            detector.evaluate_snapshot(snap)

        # Verify history holds [50.0, 50.0, 50.0]
        history = detector._median_histories[("CELL-01", "latency_ms")]
        assert list(history) == [50.0, 50.0, 50.0]

        # Anomaly sample of 250.0 ms
        anomaly_snap = make_cell_snapshot(timestamp=base_t + timedelta(seconds=40), latency_ms=250.0)
        events = detector.evaluate_snapshot(anomaly_snap)
        assert len(events) == 1

        # Contamination check: history MUST NOT contain 250.0
        assert 250.0 not in history
        assert list(history) == [50.0, 50.0, 50.0]

    def test_independent_baselines_per_node_and_metric(self) -> None:
        detector = StatisticalDetector(StatisticalDetectorConfig(warmup_count=3))
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

        # Feed CELL-01 latency 20ms
        for i in range(3):
            detector.evaluate_snapshot(make_cell_snapshot("CELL-01", t + timedelta(seconds=i), latency_ms=20.0))

        # Feed CELL-02 latency 150ms
        for i in range(3):
            detector.evaluate_snapshot(make_cell_snapshot("CELL-02", t + timedelta(seconds=i), latency_ms=150.0))

        # CELL-01 history has 20.0; CELL-02 history has 150.0
        hist_c1 = detector._median_histories[("CELL-01", "latency_ms")]
        hist_c2 = detector._median_histories[("CELL-02", "latency_ms")]
        assert list(hist_c1) == [20.0, 20.0, 20.0]
        assert list(hist_c2) == [150.0, 150.0, 150.0]

    def test_reset_behavior(self) -> None:
        detector = StatisticalDetector(StatisticalDetectorConfig(warmup_count=3))
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(3):
            detector.evaluate_snapshot(make_cell_snapshot("CELL-01", t + timedelta(seconds=i)))
            detector.evaluate_snapshot(make_cell_snapshot("CELL-02", t + timedelta(seconds=i)))

        assert len(detector._median_histories) > 0
        detector.reset_node("CELL-01")
        assert not any(k[0] == "CELL-01" for k in detector._median_histories)
        assert any(k[0] == "CELL-02" for k in detector._median_histories)

        detector.reset()
        assert len(detector._median_histories) == 0
        assert len(detector._ewma_states) == 0


# ---------------------------------------------------------------------------
# 3. Alarm Manager & Lifecycle Tests
# ---------------------------------------------------------------------------

class TestAlarmManager:
    """Tests for alarm deduplication, updates, clearing, and hysteresis."""

    def test_initial_alarm_creation(self) -> None:
        mgr = AlarmManager()
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        event = AnomalyEvent(
            node_id="CELL-01",
            metric_name="latency_ms",
            timestamp=t,
            source=DetectionSource.THRESHOLD,
            rule_id="RULE-LAT",
            severity=Severity.MAJOR,
            current_value=95.0,
            threshold=80.0,
            description="High latency",
        )
        alarm, is_new = mgr.process_anomaly(event)
        assert is_new is True
        assert alarm.node_id == "CELL-01"
        assert alarm.observation_count == 1
        assert alarm.first_seen == t
        assert alarm.last_seen == t
        assert alarm.status == AlarmStatus.ACTIVE
        assert alarm.cleared_at is None
        assert mgr.active_alarms_count == 1

    def test_alarm_deduplication_and_observation_updates(self) -> None:
        mgr = AlarmManager()
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 0, 10, tzinfo=timezone.utc)

        ev1 = AnomalyEvent("CELL-01", "latency_ms", t1, DetectionSource.THRESHOLD, "RULE-LAT", Severity.MAJOR, 95.0, 80.0)
        alarm1, is_new1 = mgr.process_anomaly(ev1)
        assert is_new1 is True

        ev2 = AnomalyEvent("CELL-01", "latency_ms", t2, DetectionSource.THRESHOLD, "RULE-LAT", Severity.CRITICAL, 110.0, 80.0)
        alarm2, is_new2 = mgr.process_anomaly(ev2)
        assert is_new2 is False
        assert alarm2.alarm_id == alarm1.alarm_id
        assert alarm2.first_seen == t1  # Preserved
        assert alarm2.last_seen == t2   # Updated
        assert alarm2.observation_count == 2
        assert alarm2.current_value == 110.0
        assert alarm2.severity == Severity.CRITICAL

    def test_clearing_alarm_moves_to_history(self) -> None:
        mgr = AlarmManager()
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 5, 0, tzinfo=timezone.utc)

        ev = AnomalyEvent("CELL-01", "latency_ms", t1, DetectionSource.THRESHOLD, "RULE-LAT", Severity.MAJOR, 95.0, 80.0)
        alarm, _ = mgr.process_anomaly(ev)
        key = ("CELL-01", "latency_ms", "RULE-LAT", DetectionSource.THRESHOLD)

        cleared = mgr.clear_alarm(key, t2)
        assert cleared is not None
        assert cleared.alarm_id == alarm.alarm_id
        assert cleared.status == AlarmStatus.CLEARED
        assert cleared.cleared_at == t2
        assert mgr.active_alarms_count == 0
        assert mgr.cleared_alarms_count == 1
        assert mgr.get_cleared_alarms()[0] == cleared

    def test_reappearance_after_clearing_creates_new_alarm(self) -> None:
        mgr = AlarmManager()
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 5, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)

        ev1 = AnomalyEvent("CELL-01", "latency_ms", t1, DetectionSource.THRESHOLD, "RULE-LAT", Severity.MAJOR, 95.0, 80.0)
        a1, is_new1 = mgr.process_anomaly(ev1)
        assert is_new1 is True

        key = ("CELL-01", "latency_ms", "RULE-LAT", DetectionSource.THRESHOLD)
        mgr.clear_alarm(key, t2)

        # Condition reappears at t3
        ev2 = AnomalyEvent("CELL-01", "latency_ms", t3, DetectionSource.THRESHOLD, "RULE-LAT", Severity.MAJOR, 105.0, 80.0)
        a2, is_new2 = mgr.process_anomaly(ev2)
        assert is_new2 is True
        assert a2.alarm_id != a1.alarm_id
        assert a2.first_seen == t3
        assert mgr.active_alarms_count == 1
        assert mgr.cleared_alarms_count == 1

    def test_independent_rules_on_same_metric_do_not_merge(self) -> None:
        mgr = AlarmManager()
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

        # Rule 1: Threshold Warning
        ev1 = AnomalyEvent("CELL-01", "latency_ms", t, DetectionSource.THRESHOLD, "RULE-LAT-WARN", Severity.WARNING, 65.0, 60.0)
        # Rule 2: Statistical EWMA
        ev2 = AnomalyEvent("CELL-01", "latency_ms", t, DetectionSource.STATISTICAL_EWMA, "STAT-EWMA-latency", Severity.MAJOR, 65.0, 20.0)

        a1, _ = mgr.process_anomaly(ev1)
        a2, _ = mgr.process_anomaly(ev2)
        assert a1.alarm_id != a2.alarm_id
        assert mgr.active_alarms_count == 2


# ---------------------------------------------------------------------------
# 4. Anomaly Detection Engine Tests
# ---------------------------------------------------------------------------

class TestAnomalyDetectionEngine:
    """Tests for coordinator engine, atomic batch validation, ordering, and deduplication."""

    def test_engine_initialization_defaults(self) -> None:
        engine = AnomalyDetectionEngine()
        assert engine.enable_threshold is True
        assert engine.enable_statistical is True
        assert len(engine.get_active_alarms()) == 0

    def test_threshold_only_configuration(self) -> None:
        engine = AnomalyDetectionEngine(enable_threshold=True, enable_statistical=False)
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        snap = make_cell_snapshot(timestamp=t, latency_ms=120.0)
        result = engine.process_snapshot(snap, node_type=NodeType.CELL)
        assert result.processed_snapshots_count == 1
        assert len(result.new_alarms) >= 1
        assert all(a.source == DetectionSource.THRESHOLD for a in result.new_alarms)

    def test_statistical_only_configuration(self) -> None:
        engine = AnomalyDetectionEngine(enable_threshold=False, enable_statistical=True)
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        # Feed warmup samples
        for i in range(8):
            snap = make_cell_snapshot(timestamp=t + timedelta(seconds=i * 10), throughput_mbps=100.0)
            engine.process_snapshot(snap)

        # Induce drop
        drop_snap = make_cell_snapshot(timestamp=t + timedelta(seconds=90), throughput_mbps=5.0)
        result = engine.process_snapshot(drop_snap)
        assert any(a.source in (DetectionSource.STATISTICAL_MEDIAN, DetectionSource.STATISTICAL_EWMA) for a in result.new_alarms)
        assert not any(a.source == DetectionSource.THRESHOLD for a in result.new_alarms)

    def test_duplicate_observations_in_batch_rejected(self) -> None:
        engine = AnomalyDetectionEngine()
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        snap1 = make_cell_snapshot("CELL-01", timestamp=t)
        snap2 = make_cell_snapshot("CELL-01", timestamp=t)
        with pytest.raises(DuplicateObservationError, match="Duplicate observation"):
            engine.process_batch([snap1, snap2])

    def test_out_of_order_telemetry_rejected(self) -> None:
        engine = AnomalyDetectionEngine()
        t1 = datetime(2026, 10, 30, 12, 5, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)  # earlier than t1
        snap1 = make_cell_snapshot("CELL-01", timestamp=t1)
        snap2 = make_cell_snapshot("CELL-01", timestamp=t2)

        with pytest.raises(TelemetryOrderError, match="Out-of-order telemetry"):
            engine.process_batch([snap1, snap2])

    def test_atomic_batch_validation_no_partial_mutations(self) -> None:
        engine = AnomalyDetectionEngine()
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        snap1 = make_cell_snapshot("CELL-01", timestamp=t1, latency_ms=150.0)  # would trigger alarm
        snap_bad = "NOT_A_SNAPSHOT"

        with pytest.raises(DetectionError):
            engine.process_batch([snap1, snap_bad])  # type: ignore[list-item]

        # Engine state must remain completely pristine
        assert len(engine.get_active_alarms()) == 0

    def test_deterministic_replay_produces_identical_alarms(self) -> None:
        engine1 = AnomalyDetectionEngine()
        engine2 = AnomalyDetectionEngine()

        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        snaps = [
            make_cell_snapshot(timestamp=t + timedelta(seconds=i * 10), latency_ms=100.0 if i == 5 else 20.0)
            for i in range(10)
        ]

        res1 = engine1.process_batch(snaps, node_types={"CELL-01": NodeType.CELL})
        res2 = engine2.process_batch(snaps, node_types={"CELL-01": NodeType.CELL})

        assert len(res1.new_alarms) == len(res2.new_alarms)
        for a1, a2 in zip(res1.new_alarms, res2.new_alarms):
            assert a1.metric_name == a2.metric_name
            assert a1.source == a2.source
            assert a1.severity == a2.severity
            assert a1.current_value == a2.current_value

    def test_missing_metric_does_not_clear_active_alarm(self) -> None:
        """An active alarm on a metric must not clear if that metric is absent in a later snapshot."""
        # Use single rule on SINR (radio metric)
        rule = ThresholdRule("RULE-SINR", "sinr_db", ComparisonOperator.LT, 5.0, Severity.MAJOR)
        engine = AnomalyDetectionEngine(
            threshold_detector=ThresholdDetector([rule]),
            enable_statistical=False,
        )
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 1, 0, tzinfo=timezone.utc)

        # Step 1: Low SINR breaches threshold on CELL-01
        snap1 = make_cell_snapshot("CELL-01", timestamp=t1, sinr_db=2.0)
        res1 = engine.process_snapshot(snap1, node_type=NodeType.CELL)
        assert len(res1.new_alarms) == 1
        assert len(engine.get_active_alarms()) == 1

        # Step 2: Next snapshot for CELL-01 has radio=None (e.g. transient sensor outage or non-radio state)
        snap2 = make_site_snapshot("CELL-01", timestamp=t2)  # has no radio metrics
        res2 = engine.process_snapshot(snap2, node_type=NodeType.CELL)

        # The alarm must NOT be cleared because the metric was absent
        assert len(res2.cleared_alarms) == 0
        active_alarms = engine.get_active_alarms()
        assert len(active_alarms) == 1
        assert active_alarms[0].metric_name == "sinr_db"
        assert active_alarms[0].status == AlarmStatus.ACTIVE


class TestCrossDetectorContaminationPolicy:
    """Rigorous tests verifying shared contamination policy between rolling median and EWMA."""

    @pytest.fixture
    def base_time(self) -> datetime:
        return datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

    def test_median_flags_ewma_does_not_neither_updates(self, base_time: datetime) -> None:
        """When rolling median flags but EWMA does not, NEITHER baseline is updated."""
        config = StatisticalDetectorConfig(
            window_size=10,
            warmup_count=3,
            median_deviation_threshold=2.0,  # sensitive median
            ewma_sensitivity=100.0,          # insensitive EWMA
            enable_rolling_median=True,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        # Baseline: 3 warm-up samples of 20.0 ms
        for i in range(3):
            detector.evaluate_snapshot(make_cell_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=20.0))

        # Check pre-observation state
        med_hist = detector._median_histories[("CELL-01", "latency_ms")]
        ewma_st = detector._ewma_states[("CELL-01", "latency_ms")]
        assert len(med_hist) == 3
        assert ewma_st["count"] == 3.0
        assert ewma_st["mean"] == 20.0

        # Sample with latency = 50.0 ms (flags median, does not flag EWMA)
        snap = make_cell_snapshot(timestamp=base_time + timedelta(seconds=30), latency_ms=50.0)
        events = detector.evaluate_snapshot(snap)

        assert len(events) == 1
        assert events[0].source == DetectionSource.STATISTICAL_MEDIAN

        # Verify BOTH baselines were protected from contamination
        assert len(med_hist) == 3
        assert 50.0 not in med_hist
        assert ewma_st["count"] == 3.0
        assert ewma_st["mean"] == 20.0

    def test_ewma_flags_median_does_not_neither_updates(self, base_time: datetime) -> None:
        """When EWMA flags but rolling median does not, NEITHER baseline is updated."""
        config = StatisticalDetectorConfig(
            window_size=10,
            warmup_count=3,
            median_deviation_threshold=100.0,  # insensitive median
            ewma_sensitivity=2.0,             # sensitive EWMA
            enable_rolling_median=True,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        # Baseline: 3 warm-up samples of 20.0 ms
        for i in range(3):
            detector.evaluate_snapshot(make_cell_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=20.0))

        med_hist = detector._median_histories[("CELL-01", "latency_ms")]
        ewma_st = detector._ewma_states[("CELL-01", "latency_ms")]
        assert len(med_hist) == 3
        assert ewma_st["count"] == 3.0

        # Sample with latency = 50.0 ms (flags EWMA, does not flag median)
        snap = make_cell_snapshot(timestamp=base_time + timedelta(seconds=30), latency_ms=50.0)
        events = detector.evaluate_snapshot(snap)

        assert len(events) == 1
        assert events[0].source == DetectionSource.STATISTICAL_EWMA

        # Verify NEITHER baseline was updated
        assert len(med_hist) == 3
        assert 50.0 not in med_hist
        assert ewma_st["count"] == 3.0
        assert ewma_st["mean"] == 20.0

    def test_both_flag_neither_updates_and_both_emit_events(self, base_time: datetime) -> None:
        """When both detectors flag, both emit independent events and neither baseline updates."""
        config = StatisticalDetectorConfig(
            window_size=10,
            warmup_count=3,
            median_deviation_threshold=2.0,
            ewma_sensitivity=2.0,
            enable_rolling_median=True,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        for i in range(3):
            detector.evaluate_snapshot(make_cell_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=20.0))

        snap = make_cell_snapshot(timestamp=base_time + timedelta(seconds=30), latency_ms=80.0)
        events = detector.evaluate_snapshot(snap)

        # Independent events emitted
        assert len(events) == 2
        sources = {e.source for e in events}
        assert sources == {DetectionSource.STATISTICAL_MEDIAN, DetectionSource.STATISTICAL_EWMA}

        # Neither baseline updated
        med_hist = detector._median_histories[("CELL-01", "latency_ms")]
        ewma_st = detector._ewma_states[("CELL-01", "latency_ms")]
        assert len(med_hist) == 3
        assert 80.0 not in med_hist
        assert ewma_st["count"] == 3.0
        assert ewma_st["mean"] == 20.0

    def test_neither_flags_both_baselines_update(self, base_time: datetime) -> None:
        """When neither detector flags, both baselines incorporate the clean sample."""
        config = StatisticalDetectorConfig(
            window_size=10,
            warmup_count=3,
            median_deviation_threshold=3.0,
            ewma_sensitivity=3.0,
            enable_rolling_median=True,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        for i in range(3):
            detector.evaluate_snapshot(make_cell_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=20.0))

        # Sample closely aligned with baseline
        snap = make_cell_snapshot(timestamp=base_time + timedelta(seconds=30), latency_ms=20.5)
        events = detector.evaluate_snapshot(snap)

        assert len(events) == 0

        # Both baselines updated
        med_hist = detector._median_histories[("CELL-01", "latency_ms")]
        ewma_st = detector._ewma_states[("CELL-01", "latency_ms")]
        assert len(med_hist) == 4
        assert med_hist[-1] == 20.5
        assert ewma_st["count"] == 4.0
        assert ewma_st["mean"] != 20.0  # shifted towards 20.5

    def test_median_only_and_ewma_only_configurations(self, base_time: datetime) -> None:
        """Disabled detectors do not evaluate or update state."""
        # Median only
        med_only = StatisticalDetector(StatisticalDetectorConfig(
            warmup_count=3, enable_rolling_median=True, enable_ewma=False
        ))
        for i in range(3):
            med_only.evaluate_snapshot(make_cell_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=20.0))
        assert len(med_only._median_histories) > 0
        assert len(med_only._ewma_states) == 0

        # EWMA only
        ewma_only = StatisticalDetector(StatisticalDetectorConfig(
            warmup_count=3, enable_rolling_median=False, enable_ewma=True
        ))
        for i in range(3):
            ewma_only.evaluate_snapshot(make_cell_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=20.0))
        assert len(ewma_only._median_histories) == 0
        assert len(ewma_only._ewma_states) > 0

    def test_warmup_and_recovery_preserved(self, base_time: datetime) -> None:
        """Warm-up period does not trigger anomalies; recovery logic correctly reports recovery."""
        config = StatisticalDetectorConfig(warmup_count=4, window_size=10)
        detector = StatisticalDetector(config)

        # During warmup: no events even with variable values
        for i in range(4):
            snap = make_cell_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=20.0)
            assert len(detector.evaluate_snapshot(snap)) == 0

        # Severe spike
        spike_snap = make_cell_snapshot(timestamp=base_time + timedelta(seconds=40), latency_ms=200.0)
        events = detector.evaluate_snapshot(spike_snap)
        assert len(events) >= 1

        # Check recovery on returning to normal
        normal_snap = make_cell_snapshot(timestamp=base_time + timedelta(seconds=50), latency_ms=20.1)
        rec_med = detector.check_recovery(normal_snap, DetectionSource.STATISTICAL_MEDIAN, "latency_ms")
        rec_ewma = detector.check_recovery(normal_snap, DetectionSource.STATISTICAL_EWMA, "latency_ms")
        assert rec_med is True
        assert rec_ewma is True


class TestEvidenceImmutability:
    """Verifies that diagnostic evidence is safely and recursively immutable."""

    def test_anomaly_event_evidence_immutability(self) -> None:
        raw_evidence = {
            "scalar": 42,
            "nested_dict": {"alpha": "beta", "count": 10},
            "nested_list": [1, 2, 3],
            "nested_set": {"tag1", "tag2"},
        }
        event = AnomalyEvent(
            node_id="CELL-01",
            metric_name="latency_ms",
            timestamp=datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc),
            source=DetectionSource.THRESHOLD,
            rule_id="R-01",
            severity=Severity.MAJOR,
            current_value=120.0,
            threshold=80.0,
            evidence=raw_evidence,
        )

        # 1. Modifying the original dict does not affect the event
        raw_evidence["scalar"] = 999
        raw_evidence["nested_dict"]["alpha"] = "MUTATED"
        raw_evidence["nested_list"].append(999)
        assert event.evidence["scalar"] == 42
        assert event.evidence["nested_dict"]["alpha"] == "beta"
        assert event.evidence["nested_list"] == (1, 2, 3)

        # 2. Modifying the event evidence directly raises TypeError
        with pytest.raises(TypeError):
            event.evidence["scalar"] = 100

        with pytest.raises(TypeError):
            event.evidence["new_key"] = "test"

        # 3. Modifying nested structures raises TypeError or AttributeError
        with pytest.raises(TypeError):
            event.evidence["nested_dict"]["alpha"] = "direct_mutation"

        with pytest.raises(AttributeError):
            event.evidence["nested_list"].append(4)  # type: ignore[attr-defined]

        # 4. Reject non-mapping inputs
        with pytest.raises(InvalidAlarmStateError):
            AnomalyEvent(
                node_id="CELL-01",
                metric_name="latency_ms",
                timestamp=datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc),
                source=DetectionSource.THRESHOLD,
                rule_id="R-01",
                severity=Severity.MAJOR,
                current_value=120.0,
                evidence="not_a_mapping",  # type: ignore[arg-type]
            )

    def test_alarm_evidence_immutability_and_manager_leak_protection(self) -> None:
        manager = AlarmManager()
        raw_evidence = {"baseline": 50.0, "details": {"source_ip": "10.0.0.1"}}
        event = AnomalyEvent(
            node_id="CELL-01",
            metric_name="latency_ms",
            timestamp=datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc),
            source=DetectionSource.THRESHOLD,
            rule_id="R-01",
            severity=Severity.MAJOR,
            current_value=120.0,
            threshold=80.0,
            evidence=raw_evidence,
        )

        alarm, is_new = manager.process_anomaly(event)
        assert is_new is True

        # Returned alarm evidence cannot be mutated
        with pytest.raises(TypeError):
            alarm.evidence["baseline"] = 999.0

        with pytest.raises(TypeError):
            alarm.evidence["details"]["source_ip"] = "mutated"

        # Alarms returned by manager queries are safely protected
        active_alarms = manager.get_active_alarms()
        with pytest.raises(TypeError):
            active_alarms[0].evidence["baseline"] = 0.0

        all_alarms = manager.get_all_alarms()
        with pytest.raises(TypeError):
            all_alarms[0].evidence["baseline"] = 0.0

        # Internal state remains completely unmutated
        assert manager.get_active_alarms()[0].evidence["baseline"] == 50.0


class TestBatchAtomicityAndTransactionalRollback:
    """Tests guaranteeing that process_batch() either succeeds completely or rolls back all state."""

    def test_node_types_validation_and_normalization(self) -> None:
        engine = AnomalyDetectionEngine()
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        snap = make_cell_snapshot("CELL-01", timestamp=t)

        # 1. String value normalization works ("cell" -> NodeType.CELL)
        res = engine.process_batch([snap], node_types={"CELL-01": "cell"})
        assert res.processed_snapshots_count == 1

        # 2. Invalid string value rejected
        t2 = datetime(2026, 10, 30, 12, 1, 0, tzinfo=timezone.utc)
        snap2 = make_cell_snapshot("CELL-01", timestamp=t2)
        with pytest.raises(DetectionError, match="Invalid NodeType string"):
            engine.process_batch([snap2], node_types={"CELL-01": "NON_EXISTENT_TYPE"})

        # 3. Invalid value type rejected
        t3 = datetime(2026, 10, 30, 12, 2, 0, tzinfo=timezone.utc)
        snap3 = make_cell_snapshot("CELL-01", timestamp=t3)
        with pytest.raises(DetectionError, match="Invalid NodeType value"):
            engine.process_batch([snap3], node_types={"CELL-01": 12345})  # type: ignore[dict-item]

        # 4. Invalid key rejected (empty string or non-string)
        with pytest.raises(DetectionError, match="node_types key must be a non-empty string"):
            engine.process_batch([snap3], node_types={"": NodeType.CELL})

        with pytest.raises(DetectionError, match="node_types key must be a non-empty string"):
            engine.process_batch([snap3], node_types={123: NodeType.CELL})  # type: ignore[dict-item]

    def test_transactional_rollback_on_mid_batch_failure(self) -> None:
        """If an error occurs halfway through a batch, all baselines, alarms, and timestamps roll back."""
        engine = AnomalyDetectionEngine()
        base_t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

        # Step 1: Establish baseline with 3 valid snapshots
        initial_snaps = [
            make_cell_snapshot("CELL-01", timestamp=base_t + timedelta(seconds=i * 10), latency_ms=20.0)
            for i in range(3)
        ]
        res_init = engine.process_batch(initial_snaps)
        assert res_init.processed_snapshots_count == 3
        assert len(engine.get_active_alarms()) == 0
        last_ts_before = dict(engine._last_node_timestamps)
        stats_state_before = engine.statistical_detector.snapshot_state()

        # Step 2: Attempt a batch that succeeds on snapshot 1 but fails on snapshot 2
        snap_ok = make_cell_snapshot("CELL-01", timestamp=base_t + timedelta(seconds=40), latency_ms=20.0)
        snap_bad = make_cell_snapshot("CELL-01", timestamp=base_t + timedelta(seconds=50), latency_ms=20.0)

        # Monkeypatch evaluate_snapshot on detector to raise an error during snap_bad
        original_eval = engine.statistical_detector.evaluate_snapshot
        calls = 0

        def flaky_eval(snap):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Simulated processing crash halfway through batch!")
            return original_eval(snap)

        engine.statistical_detector.evaluate_snapshot = flaky_eval

        try:
            with pytest.raises(RuntimeError, match="Simulated processing crash"):
                engine.process_batch([snap_ok, snap_bad])
        finally:
            engine.statistical_detector.evaluate_snapshot = original_eval

        # Step 3: Verify complete transactional rollback
        # Timestamps must match initial state
        assert engine._last_node_timestamps == last_ts_before
        # Statistical detector state must match initial state
        assert engine.statistical_detector.snapshot_state() == stats_state_before
        # Alarms must match initial state
        assert len(engine.get_active_alarms()) == 0

        # Step 4: Verify subsequent valid batch processes smoothly
        snap_next = make_cell_snapshot("CELL-01", timestamp=base_t + timedelta(seconds=40), latency_ms=20.0)
        res_next = engine.process_batch([snap_next])
        assert res_next.processed_snapshots_count == 1


class TestAlarmManagerTransactionalClearing:
    """Verifies that clear_alarm validates state and constructs cleared alarm before mutating."""

    def test_clear_alarm_transactional_failure_and_success(self) -> None:
        manager = AlarmManager()
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 5, 0, tzinfo=timezone.utc)

        event = AnomalyEvent(
            node_id="CELL-01",
            metric_name="latency_ms",
            timestamp=t2,
            source=DetectionSource.THRESHOLD,
            rule_id="RULE-01",
            severity=Severity.MAJOR,
            current_value=150.0,
        )
        alarm, _ = manager.process_anomaly(event)
        key = (alarm.node_id, alarm.metric_name, alarm.rule_id, alarm.source)

        assert manager.active_alarms_count == 1
        assert manager.cleared_alarms_count == 0

        # 1. Invalid timestamp (earlier than last_seen t2)
        earlier_t = datetime(2026, 10, 30, 12, 4, 0, tzinfo=timezone.utc)
        with pytest.raises(InvalidAlarmStateError, match="cannot be earlier than last_seen"):
            manager.clear_alarm(key, earlier_t)

        # Alarm remains ACTIVE and unmutated in active collection
        assert manager.active_alarms_count == 1
        assert manager.cleared_alarms_count == 0
        assert manager.get_active_alarm_by_key(key) is not None

        # 2. Invalid non-datetime type
        with pytest.raises(InvalidAlarmStateError, match="must be a datetime"):
            manager.clear_alarm(key, "invalid_timestamp")  # type: ignore[arg-type]

        assert manager.active_alarms_count == 1
        assert manager.cleared_alarms_count == 0

        # 3. Successful clearing
        later_t = datetime(2026, 10, 30, 12, 6, 0, tzinfo=timezone.utc)
        cleared = manager.clear_alarm(key, later_t)
        assert cleared is not None
        assert cleared.status == AlarmStatus.CLEARED
        assert cleared.cleared_at == later_t

        assert manager.active_alarms_count == 0
        assert manager.cleared_alarms_count == 1
        assert manager.get_cleared_alarms()[0].alarm_id == alarm.alarm_id


class TestStatisticalEvidenceAccuracy:
    """Verifies evidence accuracy, raw vs effective scale/spread tracking, and reproduction."""

    @pytest.fixture
    def base_time(self) -> datetime:
        return datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

    def test_rolling_median_evidence_minimum_scale_floor_active(self, base_time: datetime) -> None:
        """When history is constant (MAD=0), raw_scale is 0 and effective_scale uses floor."""
        config = StatisticalDetectorConfig(
            window_size=10,
            warmup_count=5,
            median_deviation_threshold=3.0,
            enable_rolling_median=True,
            enable_ewma=False,
        )
        detector = StatisticalDetector(config)

        # Baseline: 5 constant observations at 20.0 ms
        for i in range(5):
            detector.evaluate_snapshot(make_cell_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=20.0))

        # Sudden spike to 120.0 ms
        spike_snap = make_cell_snapshot(timestamp=base_time + timedelta(seconds=60), latency_ms=120.0)
        events = detector.evaluate_snapshot(spike_snap)
        assert len(events) == 1
        ev = events[0]

        ev_dict = ev.evidence
        # raw_scale is 0 because MAD of constant history is 0
        assert ev_dict["raw_scale"] == 0.0
        # min_scale_floor is 0.05 * 20.0 = 1.0
        assert ev_dict["min_scale_floor"] == 1.0
        # effective_scale uses the floor
        assert ev_dict["effective_scale"] == 1.0
        assert ev_dict["raw_scale"] < ev_dict["effective_scale"]

        # Verify deviation and reproduction formula: score = absolute_deviation / effective_scale
        deviation = ev_dict["deviation"]
        assert deviation == 100.0
        expected_score = deviation / ev_dict["effective_scale"]
        assert ev_dict["score"] == pytest.approx(expected_score, abs=1e-4)

    def test_rolling_median_evidence_raw_scale_exceeds_floor(self, base_time: datetime) -> None:
        """When history has natural variance, raw_scale exceeds floor and is used as effective_scale."""
        config = StatisticalDetectorConfig(
            window_size=10,
            warmup_count=5,
            median_deviation_threshold=3.0,
            enable_rolling_median=True,
            enable_ewma=False,
        )
        detector = StatisticalDetector(config)

        # Baseline with dispersion: 10, 20, 30, 40, 50 -> med=30, residuals=[20, 10, 0, 10, 20], mad=10
        # raw_scale = 1.4826 * 10 = 14.826, floor = 0.05 * 30 = 1.5
        for i, val in enumerate([10.0, 20.0, 30.0, 40.0, 50.0]):
            detector.evaluate_snapshot(make_cell_snapshot(timestamp=base_time + timedelta(seconds=i * 10), latency_ms=val))

        # Extreme spike to 200.0 ms -> deviation = 170.0
        spike_snap = make_cell_snapshot(timestamp=base_time + timedelta(seconds=60), latency_ms=200.0)
        events = detector.evaluate_snapshot(spike_snap)
        assert len(events) == 1
        ev = events[0]

        ev_dict = ev.evidence
        assert ev_dict["raw_scale"] == 14.826
        assert ev_dict["min_scale_floor"] == 1.5
        # Raw scale strictly exceeds the floor
        assert ev_dict["raw_scale"] > ev_dict["min_scale_floor"]
        assert ev_dict["effective_scale"] == ev_dict["raw_scale"]

        # Verify score reproduction: score = absolute_deviation / effective_scale
        deviation = ev_dict["deviation"]
        assert deviation == 170.0
        expected_score = round(deviation / ev_dict["effective_scale"], 4)
        assert ev_dict["score"] == pytest.approx(expected_score, abs=1e-4)

    def test_ewma_evidence_minimum_spread_floor_active(self, base_time: datetime) -> None:
        """When EWMA history is constant (var=0), raw_spread is 0 and effective_spread uses floor."""
        config = StatisticalDetectorConfig(
            window_size=10,
            warmup_count=5,
            ewma_alpha=0.2,
            ewma_sensitivity=3.0,
            enable_rolling_median=False,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        # Baseline: 5 constant throughput samples of 50.0 Mbps
        for i in range(5):
            detector.evaluate_snapshot(make_cell_snapshot(timestamp=base_time + timedelta(seconds=i * 10), throughput_mbps=50.0))

        # Collapse to 5.0 Mbps
        drop_snap = make_cell_snapshot(timestamp=base_time + timedelta(seconds=60), throughput_mbps=5.0)
        events = detector.evaluate_snapshot(drop_snap)
        assert len(events) == 1
        ev = events[0]

        ev_dict = ev.evidence
        assert ev_dict["raw_spread"] == 0.0
        # min_spread_floor is 0.05 * 50.0 = 2.5
        assert ev_dict["min_spread_floor"] == 2.5
        assert ev_dict["effective_spread"] == 2.5
        assert ev_dict["raw_spread"] < ev_dict["effective_spread"]

        # Verify ewma_score reproduction: ewma_score = absolute_difference / effective_spread
        diff = abs(ev_dict["diff"])
        assert diff == 45.0
        expected_score = diff / ev_dict["effective_spread"]
        assert ev_dict["score"] == pytest.approx(expected_score, abs=1e-4)

    def test_ewma_evidence_raw_spread_exceeds_floor(self, base_time: datetime) -> None:
        """When EWMA baseline has accumulated variance, raw_spread exceeds floor."""
        config = StatisticalDetectorConfig(
            window_size=15,
            warmup_count=6,
            ewma_alpha=0.3,
            ewma_sensitivity=2.5,
            enable_rolling_median=False,
            enable_ewma=True,
        )
        detector = StatisticalDetector(config)

        # Feed alternating values with variance: 20.0, 80.0, 20.0, 80.0, 20.0, 80.0
        for i in range(6):
            val = 80.0 if i % 2 == 1 else 20.0
            detector.evaluate_snapshot(make_cell_snapshot(timestamp=base_time + timedelta(seconds=i * 10), throughput_mbps=val))

        # Extreme spike to 250.0 Mbps
        spike_snap = make_cell_snapshot(timestamp=base_time + timedelta(seconds=70), throughput_mbps=250.0)
        events = detector.evaluate_snapshot(spike_snap)
        assert len(events) == 1
        ev = events[0]

        ev_dict = ev.evidence
        # Raw spread has accumulated variance > floor
        assert ev_dict["raw_spread"] > ev_dict["min_spread_floor"]
        assert ev_dict["effective_spread"] == ev_dict["raw_spread"]

        # Verify score reproduction: ewma_score = absolute_difference / effective_spread
        diff = abs(ev_dict["diff"])
        expected_score = round(diff / ev_dict["effective_spread"], 4)
        assert ev_dict["score"] == pytest.approx(expected_score, abs=1e-4)
