"""Unit and integration tests for the Fault & Scenario Engine domain."""

from datetime import datetime, timedelta, timezone
from typing import Optional
import pytest

from nexus.fault import (
    ConflictingFaultError,
    Fault,
    FaultScenarioEngine,
    FaultType,
    GroundTruthRecord,
    IncompatibleTargetError,
    InvalidFaultStateError,
    ScenarioError,
    build_reference_scenarios,
)
from nexus.telemetry import (
    KPISnapshot,
    PerformanceMetrics,
    RadioMetrics,
    ReliabilityMetrics,
    SyntheticTelemetryGenerator,
)
from nexus.topology import NodeType, Topology, build_simulated_network
from nexus.transport import (
    TransportNetwork,
    build_reference_transport_network,
)


class TestFaultModelValidation:
    """Tests for Fault model validation, timestamp normalization, and intervals."""

    def test_valid_fault_creation(self) -> None:
        t_start = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t_end = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        f = Fault(
            fault_id="F1",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            start_time=t_start,
            end_time=t_end,
            severity=0.8,
            description="Test fault",
        )
        assert f.fault_id == "F1"
        assert f.fault_type == FaultType.CELL_OUTAGE
        assert f.target_id == "CELL-01"
        assert f.start_time == t_start
        assert f.end_time == t_end
        assert f.severity == 0.8
        assert f.description == "Test fault"

    def test_timestamp_naive_normalized_to_utc(self) -> None:
        t_start = datetime(2026, 10, 30, 12, 0, 0)
        t_end = datetime(2026, 10, 30, 12, 10, 0)
        f = Fault("F1", FaultType.CELL_OUTAGE, "CELL-01", t_start, t_end)
        assert f.start_time.tzinfo == timezone.utc
        assert f.end_time.tzinfo == timezone.utc

    def test_timestamp_non_utc_normalized_preserving_instant(self) -> None:
        tz_plus_5 = timezone(timedelta(hours=5))
        t_start = datetime(2026, 10, 30, 17, 0, 0, tzinfo=tz_plus_5)  # 12:00 UTC
        t_end = datetime(2026, 10, 30, 17, 10, 0, tzinfo=tz_plus_5)  # 12:10 UTC
        f = Fault("F1", FaultType.CELL_OUTAGE, "CELL-01", t_start, t_end)
        assert f.start_time.tzinfo == timezone.utc
        assert f.start_time.hour == 12
        assert f.end_time.hour == 12
        assert f.end_time.minute == 10

    def test_invalid_interval_start_not_earlier_than_end(self) -> None:
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        # start == end
        with pytest.raises(InvalidFaultStateError, match="must be strictly earlier"):
            Fault("F1", FaultType.CELL_OUTAGE, "CELL-01", t, t)

        # start > end
        with pytest.raises(InvalidFaultStateError, match="must be strictly earlier"):
            Fault("F1", FaultType.CELL_OUTAGE, "CELL-01", t + timedelta(minutes=5), t)

    @pytest.mark.parametrize("invalid_id", ["", "   ", None])
    def test_invalid_identifiers_rejected(self, invalid_id: object) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        with pytest.raises(InvalidFaultStateError):
            Fault(invalid_id, FaultType.CELL_OUTAGE, "CELL-01", t1, t2)  # type: ignore[arg-type]
        with pytest.raises(InvalidFaultStateError):
            Fault("F1", FaultType.CELL_OUTAGE, invalid_id, t1, t2)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_sev", [-0.1, 1.01, float("nan"), float("inf"), True, False, "1.0"])
    def test_invalid_severity_rejected(self, bad_sev: object) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        with pytest.raises(InvalidFaultStateError):
            Fault("F1", FaultType.CELL_OUTAGE, "CELL-01", t1, t2, severity=bad_sev)  # type: ignore[arg-type]

    def test_half_open_active_interval_semantics(self) -> None:
        """Verify start_time <= timestamp < end_time half-open interval."""
        t_start = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t_end = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        f = Fault("F1", FaultType.CELL_OUTAGE, "CELL-01", t_start, t_end)

        # Before start
        assert not f.is_active_at(t_start - timedelta(seconds=1))
        # Exactly at start
        assert f.is_active_at(t_start)
        # Inside interval
        assert f.is_active_at(t_start + timedelta(minutes=5))
        # 1 microsecond before end
        assert f.is_active_at(t_end - timedelta(microseconds=1))
        # Exactly at end (recovered!)
        assert not f.is_active_at(t_end)
        # After end
        assert not f.is_active_at(t_end + timedelta(seconds=1))


class TestGroundTruthRecordValidation:
    """Tests for GroundTruthRecord construction, field validation, and immutability."""

    def test_valid_ground_truth_record_creation(self) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        gt = GroundTruthRecord(
            scenario_id="SC-01",
            fault_id="F-01",
            fault_type=FaultType.CELL_OUTAGE,
            target_id="CELL-01",
            start_time=t1,
            end_time=t2,
            severity=1.0,
            affected_node_ids=("CELL-01",),
            description="Cell outage test",
        )
        assert gt.scenario_id == "SC-01"
        assert gt.fault_id == "F-01"
        assert gt.fault_type == FaultType.CELL_OUTAGE
        assert gt.target_id == "CELL-01"
        assert gt.start_time == t1
        assert gt.end_time == t2
        assert gt.severity == 1.0
        assert gt.affected_node_ids == ("CELL-01",)
        assert gt.description == "Cell outage test"

    def test_timestamp_normalization(self) -> None:
        t1_naive = datetime(2026, 10, 30, 12, 0, 0)
        t2_naive = datetime(2026, 10, 30, 12, 10, 0)
        gt = GroundTruthRecord(
            "SC-01", "F-01", FaultType.CELL_OUTAGE, "CELL-01", t1_naive, t2_naive, 1.0, ("CELL-01",)
        )
        assert gt.start_time.tzinfo == timezone.utc
        assert gt.end_time.tzinfo == timezone.utc

    def test_invalid_interval_rejected(self) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(InvalidFaultStateError, match="must be strictly earlier"):
            GroundTruthRecord("SC-01", "F-01", FaultType.CELL_OUTAGE, "CELL-01", t1, t1, 1.0, ("CELL-01",))

    @pytest.mark.parametrize("invalid_id", ["", "   ", None])
    def test_invalid_identifiers_rejected(self, invalid_id: object) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        with pytest.raises(InvalidFaultStateError):
            GroundTruthRecord(invalid_id, "F-01", FaultType.CELL_OUTAGE, "CELL-01", t1, t2, 1.0, ("CELL-01",))  # type: ignore[arg-type]
        with pytest.raises(InvalidFaultStateError):
            GroundTruthRecord("SC-01", invalid_id, FaultType.CELL_OUTAGE, "CELL-01", t1, t2, 1.0, ("CELL-01",))  # type: ignore[arg-type]
        with pytest.raises(InvalidFaultStateError):
            GroundTruthRecord("SC-01", "F-01", FaultType.CELL_OUTAGE, invalid_id, t1, t2, 1.0, ("CELL-01",))  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_sev", [-0.1, 1.5, float("nan"), float("inf"), True, False, "1.0"])
    def test_invalid_severity_rejected(self, bad_sev: object) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        with pytest.raises(InvalidFaultStateError):
            GroundTruthRecord("SC-01", "F-01", FaultType.CELL_OUTAGE, "CELL-01", t1, t2, bad_sev, ("CELL-01",))  # type: ignore[arg-type]

    def test_fault_type_string_coercion(self) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        gt = GroundTruthRecord("SC-01", "F-01", "BACKHAUL_FAILURE", "LINK-01", t1, t2, 1.0, ("SITE-01",))  # type: ignore[arg-type]
        assert gt.fault_type == FaultType.BACKHAUL_FAILURE

    def test_invalid_fault_type_rejected(self) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        with pytest.raises(InvalidFaultStateError, match="Invalid fault_type"):
            GroundTruthRecord("SC-01", "F-01", "BAD_TYPE", "CELL-01", t1, t2, 1.0, ("CELL-01",))  # type: ignore[arg-type]

    def test_affected_node_ids_validation_and_uniqueness(self) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)

        # Rejects non-sequence
        with pytest.raises(InvalidFaultStateError, match="must be a sequence"):
            GroundTruthRecord("SC-01", "F-01", FaultType.CELL_OUTAGE, "CELL-01", t1, t2, 1.0, 123)  # type: ignore[arg-type]

        # Rejects empty or whitespace node IDs
        with pytest.raises(InvalidFaultStateError, match="empty or non-string"):
            GroundTruthRecord("SC-01", "F-01", FaultType.CELL_OUTAGE, "CELL-01", t1, t2, 1.0, ("CELL-01", ""))

        with pytest.raises(InvalidFaultStateError, match="empty or non-string"):
            GroundTruthRecord("SC-01", "F-01", FaultType.CELL_OUTAGE, "CELL-01", t1, t2, 1.0, ("CELL-01", None))  # type: ignore[arg-type]

        # Rejects duplicates
        with pytest.raises(InvalidFaultStateError, match="Duplicate node ID"):
            GroundTruthRecord("SC-01", "F-01", FaultType.CELL_OUTAGE, "CELL-01", t1, t2, 1.0, ("CELL-01", "CELL-01"))

        # Successfully coerces list to tuple
        gt = GroundTruthRecord("SC-01", "F-01", FaultType.CELL_OUTAGE, "CELL-01", t1, t2, 1.0, ["CELL-01", "CELL-02"])
        assert isinstance(gt.affected_node_ids, tuple)
        assert gt.affected_node_ids == ("CELL-01", "CELL-02")

    @pytest.mark.parametrize("valid_desc", [None, "Valid description", ""])
    def test_description_valid_types_accepted(self, valid_desc: Optional[str]) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        gt = GroundTruthRecord(
            "SC-01", "F-01", FaultType.CELL_OUTAGE, "CELL-01", t1, t2, 1.0, ("CELL-01",), description=valid_desc
        )
        assert gt.description == valid_desc

    @pytest.mark.parametrize("invalid_desc", [123, True, False, ["notes"], {"text": "desc"}])
    def test_description_invalid_types_rejected(self, invalid_desc: object) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        with pytest.raises(InvalidFaultStateError, match="description must be a string or None"):
            GroundTruthRecord(
                "SC-01", "F-01", FaultType.CELL_OUTAGE, "CELL-01", t1, t2, 1.0, ("CELL-01",), description=invalid_desc  # type: ignore[arg-type]
            )


class TestScenarioEngineTargetAndConflictValidation:
    """Tests covering target validation, conflict detection, and scenario constraints."""

    @pytest.fixture
    def net(self) -> Topology:
        return build_simulated_network()

    @pytest.fixture
    def transport(self, net: Topology) -> TransportNetwork:
        return build_reference_transport_network(net)

    def test_incompatible_target_types_rejected(self, net: Topology, transport: TransportNetwork) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)

        # CELL_OUTAGE targeting SITE-01 (must be CELL)
        f_bad_cell = Fault("F1", FaultType.CELL_OUTAGE, "SITE-01", t1, t2)
        with pytest.raises(IncompatibleTargetError, match="requires a CELL node target"):
            FaultScenarioEngine(net, transport, [f_bad_cell])

        # SITE_POWER_FAILURE targeting CELL-01 (must be SITE)
        f_bad_site = Fault("F2", FaultType.SITE_POWER_FAILURE, "CELL-01", t1, t2)
        with pytest.raises(IncompatibleTargetError, match="requires a SITE node target"):
            FaultScenarioEngine(net, transport, [f_bad_site])

        # BACKHAUL_FAILURE targeting a node instead of a transport link
        f_bad_link = Fault("F3", FaultType.BACKHAUL_FAILURE, "SITE-01", t1, t2)
        with pytest.raises(IncompatibleTargetError, match="does not exist in transport network"):
            FaultScenarioEngine(net, transport, [f_bad_link])

    def test_duplicate_fault_id_in_scenario_rejected(self, net: Topology, transport: TransportNetwork) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        f1 = Fault("F1", FaultType.CELL_OUTAGE, "CELL-01", t1, t2)
        f2 = Fault("F1", FaultType.CELL_OUTAGE, "CELL-02", t1, t2)
        with pytest.raises(InvalidFaultStateError, match="Duplicate fault_id 'F1'"):
            FaultScenarioEngine(net, transport, [f1, f2])

    def test_conflicting_overlapping_faults_rejected(self, net: Topology, transport: TransportNetwork) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)

        # 1. Same fault type overlapping on same target
        f1 = Fault("F1", FaultType.CELL_OUTAGE, "CELL-01", t1, t2)
        f2 = Fault("F2", FaultType.CELL_OUTAGE, "CELL-01", t1 + timedelta(minutes=5), t2 + timedelta(minutes=5))
        with pytest.raises(ConflictingFaultError, match="Conflicting overlapping faults"):
            FaultScenarioEngine(net, transport, [f1, f2])

        # 2. Outage overlapping with Interference on same cell
        f3 = Fault("F3", FaultType.RADIO_INTERFERENCE, "CELL-01", t1 + timedelta(minutes=2), t2)
        with pytest.raises(ConflictingFaultError, match="Conflicting overlapping faults"):
            FaultScenarioEngine(net, transport, [f1, f3])

    def test_non_overlapping_faults_on_same_target_allowed(self, net: Topology, transport: TransportNetwork) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 30, 12, 15, 0, tzinfo=timezone.utc)
        t4 = datetime(2026, 10, 30, 12, 25, 0, tzinfo=timezone.utc)

        # f1 ends at 12:10, f2 starts at 12:15 -> no overlap
        f1 = Fault("F1", FaultType.CELL_OUTAGE, "CELL-01", t1, t2)
        f2 = Fault("F2", FaultType.CELL_OUTAGE, "CELL-01", t3, t4)
        engine = FaultScenarioEngine(net, transport, [f1, f2])
        assert len(engine.faults) == 2

    def test_conflict_backhaul_failure_and_interference_on_descendant_cell_rejected(
        self, net: Topology, transport: TransportNetwork
    ) -> None:
        """LINK-AGG-01-SITE-01 failure impacts SITE-01 and CELL-01..03.
        Simultaneous RADIO_INTERFERENCE on CELL-01 must be detected and rejected."""
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        f_bh = Fault("F_BH", FaultType.BACKHAUL_FAILURE, "LINK-AGG-01-SITE-01", t1, t2)
        f_rf = Fault("F_RF", FaultType.RADIO_INTERFERENCE, "CELL-01", t1, t2)
        with pytest.raises(ConflictingFaultError, match="Conflicting overlapping faults"):
            FaultScenarioEngine(net, transport, [f_bh, f_rf])

    def test_conflict_backhaul_failure_and_congestion_on_descendant_cell_rejected(
        self, net: Topology, transport: TransportNetwork
    ) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        f_bh = Fault("F_BH", FaultType.BACKHAUL_FAILURE, "LINK-AGG-01-SITE-01", t1, t2)
        f_cong = Fault("F_CONG", FaultType.CELL_CONGESTION, "CELL-02", t1, t2)
        with pytest.raises(ConflictingFaultError, match="Conflicting overlapping faults"):
            FaultScenarioEngine(net, transport, [f_bh, f_cong])

    def test_conflict_site_power_failure_and_interference_on_descendant_cell_rejected(
        self, net: Topology, transport: TransportNetwork
    ) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        f_pwr = Fault("F_PWR", FaultType.SITE_POWER_FAILURE, "SITE-01", t1, t2)
        f_rf = Fault("F_RF", FaultType.RADIO_INTERFERENCE, "CELL-03", t1, t2)
        with pytest.raises(ConflictingFaultError, match="Conflicting overlapping faults"):
            FaultScenarioEngine(net, transport, [f_pwr, f_rf])

    def test_conflict_site_power_failure_and_congestion_on_descendant_cell_rejected(
        self, net: Topology, transport: TransportNetwork
    ) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        f_pwr = Fault("F_PWR", FaultType.SITE_POWER_FAILURE, "SITE-01", t1, t2)
        f_cong = Fault("F_CONG", FaultType.CELL_CONGESTION, "CELL-01", t1, t2)
        with pytest.raises(ConflictingFaultError, match="Conflicting overlapping faults"):
            FaultScenarioEngine(net, transport, [f_pwr, f_cong])

    def test_conflict_cell_congestion_and_interference_on_same_cell_rejected(
        self, net: Topology, transport: TransportNetwork
    ) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        f_rf = Fault("F_RF", FaultType.RADIO_INTERFERENCE, "CELL-01", t1, t2)
        f_cong = Fault("F_CONG", FaultType.CELL_CONGESTION, "CELL-01", t1, t2)
        with pytest.raises(ConflictingFaultError, match="Conflicting overlapping faults"):
            FaultScenarioEngine(net, transport, [f_rf, f_cong])

    def test_conflict_two_congestions_on_same_cell_rejected(
        self, net: Topology, transport: TransportNetwork
    ) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        f1 = Fault("F_CONG1", FaultType.CELL_CONGESTION, "CELL-01", t1, t2)
        f2 = Fault("F_CONG2", FaultType.CELL_CONGESTION, "CELL-01", t1, t2)
        with pytest.raises(ConflictingFaultError, match="Conflicting overlapping faults"):
            FaultScenarioEngine(net, transport, [f1, f2])

    def test_independent_branch_faults_allowed(
        self, net: Topology, transport: TransportNetwork
    ) -> None:
        """Faults on separate branches (e.g. SITE-01 branch vs SITE-02 branch) do not conflict."""
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        f_bh = Fault("F_BH", FaultType.BACKHAUL_FAILURE, "LINK-AGG-01-SITE-01", t1, t2)
        # CELL-04 is under SITE-02, disjoint from SITE-01 branch
        f_rf = Fault("F_RF", FaultType.RADIO_INTERFERENCE, "CELL-04", t1, t2)
        engine = FaultScenarioEngine(net, transport, [f_bh, f_rf])
        assert len(engine.faults) == 2

    def test_non_overlapping_faults_on_same_affected_node_allowed(
        self, net: Topology, transport: TransportNetwork
    ) -> None:
        t1 = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        t4 = datetime(2026, 10, 30, 12, 20, 0, tzinfo=timezone.utc)
        f_bh = Fault("F_BH", FaultType.BACKHAUL_FAILURE, "LINK-AGG-01-SITE-01", t1, t2)
        f_rf = Fault("F_RF", FaultType.RADIO_INTERFERENCE, "CELL-01", t3, t4)
        engine = FaultScenarioEngine(net, transport, [f_bh, f_rf])
        assert len(engine.faults) == 2


class TestFaultScenarioEngineTelemetryEffectsAndImpact:
    """Tests verifying telemetry transformations, downstream blast radius, and ground truth."""

    @pytest.fixture
    def net(self) -> Topology:
        return build_simulated_network()

    @pytest.fixture
    def transport(self, net: Topology) -> TransportNetwork:
        return build_reference_transport_network(net)

    @pytest.fixture
    def gen(self, net: Topology) -> SyntheticTelemetryGenerator:
        return SyntheticTelemetryGenerator(net, seed=42)

    def test_no_faults_active_preserves_base_telemetry_identically(
        self, net: Topology, transport: TransportNetwork, gen: SyntheticTelemetryGenerator
    ) -> None:
        t_fault = datetime(2026, 10, 30, 12, 10, 0, tzinfo=timezone.utc)
        t_eval = datetime(2026, 10, 30, 11, 0, 0, tzinfo=timezone.utc)  # Evaluation is before fault

        fault = Fault("F1", FaultType.CELL_OUTAGE, "CELL-01", t_fault, t_fault + timedelta(minutes=10))
        engine = FaultScenarioEngine(net, transport, [fault])

        base_step = gen.generate_step(timestamp=t_eval)
        effective_step = engine.apply_faults(base_step, timestamp=t_eval)

        assert effective_step == base_step

    def test_cell_outage_telemetry_transformation(
        self, net: Topology, transport: TransportNetwork, gen: SyntheticTelemetryGenerator
    ) -> None:
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        fault = Fault("F1", FaultType.CELL_OUTAGE, "CELL-01", t, t + timedelta(minutes=10))
        engine = FaultScenarioEngine(net, transport, [fault])

        base_step = gen.generate_step(timestamp=t)
        effective_step = engine.apply_faults(base_step, timestamp=t)

        cell_base = next(s for s in base_step if s.node_id == "CELL-01")
        cell_eff = next(s for s in effective_step if s.node_id == "CELL-01")

        # Base snapshot was NOT mutated
        assert cell_base.performance.throughput_mbps > 0.0
        assert cell_base.reliability.availability_pct > 90.0

        # Effective snapshot reflects total outage
        assert cell_eff.performance.throughput_mbps == 0.0
        assert cell_eff.reliability.availability_pct == 0.0
        assert cell_eff.reliability.connection_drop_rate_pct == 100.0
        assert cell_eff.reliability.handover_success_rate_pct == 0.0
        assert cell_eff.radio is not None
        assert cell_eff.radio.prb_utilization_pct == 0.0
        assert cell_eff.radio.rsrp_dbm == -145.0

        # Unrelated cell CELL-02 remains unaffected
        cell2_base = next(s for s in base_step if s.node_id == "CELL-02")
        cell2_eff = next(s for s in effective_step if s.node_id == "CELL-02")
        assert cell2_eff == cell2_base

    def test_backhaul_failure_downstream_subtree_propagation(
        self, net: Topology, transport: TransportNetwork, gen: SyntheticTelemetryGenerator
    ) -> None:
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        # Target LINK-AGG-01-SITE-01: upstream is AGG-01, downstream is SITE-01
        fault = Fault("F_BH", FaultType.BACKHAUL_FAILURE, "LINK-AGG-01-SITE-01", t, t + timedelta(minutes=15))
        engine = FaultScenarioEngine(net, transport, [fault])

        # Ground truth check
        gt = engine.get_ground_truth()[0]
        assert gt.affected_node_ids == ("SITE-01", "CELL-01", "CELL-02", "CELL-03")

        base_step = gen.generate_step(timestamp=t)
        effective_step = engine.apply_faults(base_step, timestamp=t)

        affected_ids = {"SITE-01", "CELL-01", "CELL-02", "CELL-03"}
        for snap in effective_step:
            if snap.node_id in affected_ids:
                # Affected nodes reflect complete outage
                assert snap.performance.throughput_mbps == 0.0
                assert snap.reliability.availability_pct == 0.0
            else:
                # Unrelated nodes (AGG-01, SITE-02, CELL-04..18) remain completely unaffected
                base_snap = next(s for s in base_step if s.node_id == snap.node_id)
                assert snap == base_snap

    def test_site_power_failure_propagation(
        self, net: Topology, transport: TransportNetwork, gen: SyntheticTelemetryGenerator
    ) -> None:
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        fault = Fault("F_PWR", FaultType.SITE_POWER_FAILURE, "SITE-04", t, t + timedelta(minutes=20))
        engine = FaultScenarioEngine(net, transport, [fault])

        # SITE-04 owns CELL-10, CELL-11, CELL-12
        gt = engine.get_ground_truth()[0]
        assert gt.affected_node_ids == ("SITE-04", "CELL-10", "CELL-11", "CELL-12")

        base_step = gen.generate_step(timestamp=t)
        effective_step = engine.apply_faults(base_step, timestamp=t)

        site4_eff = next(s for s in effective_step if s.node_id == "SITE-04")
        assert site4_eff.performance.throughput_mbps == 0.0
        assert site4_eff.reliability.availability_pct == 0.0

        for c_id in ["CELL-10", "CELL-11", "CELL-12"]:
            cell_eff = next(s for s in effective_step if s.node_id == c_id)
            assert cell_eff.performance.throughput_mbps == 0.0
            assert cell_eff.reliability.availability_pct == 0.0

        # Unrelated SITE-05 and CELL-13..15 are unaffected
        site5_base = next(s for s in base_step if s.node_id == "SITE-05")
        site5_eff = next(s for s in effective_step if s.node_id == "SITE-05")
        assert site5_eff == site5_base

    def test_radio_interference_telemetry_transformation(
        self, net: Topology, transport: TransportNetwork, gen: SyntheticTelemetryGenerator
    ) -> None:
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        fault = Fault("F_RF", FaultType.RADIO_INTERFERENCE, "CELL-05", t, t + timedelta(minutes=10), severity=0.8)
        engine = FaultScenarioEngine(net, transport, [fault])

        base_step = gen.generate_step(timestamp=t)
        effective_step = engine.apply_faults(base_step, timestamp=t)

        cell5_base = next(s for s in base_step if s.node_id == "CELL-05")
        cell5_eff = next(s for s in effective_step if s.node_id == "CELL-05")

        assert cell5_base.radio is not None and cell5_eff.radio is not None
        # Severe SINR drop
        assert cell5_eff.radio.sinr_db < cell5_base.radio.sinr_db
        # Throughput drop
        assert cell5_eff.performance.throughput_mbps < cell5_base.performance.throughput_mbps
        # Increased drop rate
        assert cell5_eff.reliability.connection_drop_rate_pct > cell5_base.reliability.connection_drop_rate_pct

        # PRB was not affected by interference
        assert cell5_eff.radio.prb_utilization_pct == cell5_base.radio.prb_utilization_pct

        # Unrelated cells unaffected
        cell6_base = next(s for s in base_step if s.node_id == "CELL-06")
        cell6_eff = next(s for s in effective_step if s.node_id == "CELL-06")
        assert cell6_eff == cell6_base

    def test_radio_interference_severity_boundaries(
        self, net: Topology, transport: TransportNetwork, gen: SyntheticTelemetryGenerator
    ) -> None:
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        base_step = gen.generate_step(timestamp=t)
        base_c5 = next(s for s in base_step if s.node_id == "CELL-05")
        assert base_c5.radio is not None
        base_sinr = base_c5.radio.sinr_db

        # Severity 0.0 -> penalty is 0.0 dB (delta = 0.0 dB)
        f0 = Fault("F0", FaultType.RADIO_INTERFERENCE, "CELL-05", t, t + timedelta(minutes=10), severity=0.0)
        e0 = FaultScenarioEngine(net, transport, [f0])
        eff0 = e0.apply_faults(base_step, timestamp=t)
        eff0_c5 = next(s for s in eff0 if s.node_id == "CELL-05")
        assert eff0_c5.radio is not None
        assert eff0_c5.radio.sinr_db == base_sinr

        # Severity 0.5 -> penalty is 10.0 dB
        f05 = Fault("F05", FaultType.RADIO_INTERFERENCE, "CELL-05", t, t + timedelta(minutes=10), severity=0.5)
        e05 = FaultScenarioEngine(net, transport, [f05])
        eff05 = e05.apply_faults(base_step, timestamp=t)
        eff05_c5 = next(s for s in eff05 if s.node_id == "CELL-05")
        assert eff05_c5.radio is not None
        assert eff05_c5.radio.sinr_db == round(base_sinr - 10.0, 2)

        # Severity 1.0 -> maximum penalty is 20.0 dB
        f1 = Fault("F1", FaultType.RADIO_INTERFERENCE, "CELL-05", t, t + timedelta(minutes=10), severity=1.0)
        e1 = FaultScenarioEngine(net, transport, [f1])
        eff1 = e1.apply_faults(base_step, timestamp=t)
        eff1_c5 = next(s for s in eff1 if s.node_id == "CELL-05")
        assert eff1_c5.radio is not None
        expected_sinr = max(-25.0, round(base_sinr - 20.0, 2))
        assert eff1_c5.radio.sinr_db == expected_sinr

    def test_radio_interference_clamping_at_minimum_sinr(
        self, net: Topology, transport: TransportNetwork
    ) -> None:
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        # Create a snapshot with low initial SINR (-15 dB)
        low_snap = KPISnapshot(
            node_id="CELL-05",
            timestamp=t,
            performance=PerformanceMetrics(50.0, 10.0),
            reliability=ReliabilityMetrics(0.1, 99.9, 99.5),
            radio=RadioMetrics(rsrp_dbm=-100.0, sinr_db=-15.0, prb_utilization_pct=40.0),
        )
        f_max = Fault("F_MAX", FaultType.RADIO_INTERFERENCE, "CELL-05", t, t + timedelta(minutes=10), severity=1.0)
        engine = FaultScenarioEngine(net, transport, [f_max])
        eff = engine.apply_faults([low_snap], timestamp=t)
        assert eff[0].radio is not None
        # -15.0 - 20.0 = -35.0 dB, which must clamp to physical floor -25.0 dB
        assert eff[0].radio.sinr_db == -25.0

    def test_cell_congestion_telemetry_transformation(
        self, net: Topology, transport: TransportNetwork, gen: SyntheticTelemetryGenerator
    ) -> None:
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        fault = Fault("F_CONG", FaultType.CELL_CONGESTION, "CELL-10", t, t + timedelta(minutes=10), severity=0.9)
        engine = FaultScenarioEngine(net, transport, [fault])

        base_step = gen.generate_step(timestamp=t)
        effective_step = engine.apply_faults(base_step, timestamp=t)

        cell10_base = next(s for s in base_step if s.node_id == "CELL-10")
        cell10_eff = next(s for s in effective_step if s.node_id == "CELL-10")

        assert cell10_base.radio is not None and cell10_eff.radio is not None
        # PRB utilization spiked
        assert cell10_eff.radio.prb_utilization_pct > cell10_base.radio.prb_utilization_pct
        assert cell10_eff.radio.prb_utilization_pct >= 90.0
        # Latency increased
        assert cell10_eff.performance.latency_ms > cell10_base.performance.latency_ms
        # Throughput reduced
        assert cell10_eff.performance.throughput_mbps < cell10_base.performance.throughput_mbps

        # SINR was not affected by congestion
        assert cell10_eff.radio.sinr_db == cell10_base.radio.sinr_db

    def test_frozen_fault_impact_sets_isolated_from_subsequent_topology_reparenting(
        self, net: Topology, transport: TransportNetwork, gen: SyntheticTelemetryGenerator
    ) -> None:
        """Regression test: Engine freezes fault impact sets at construction.
        Subsequent topology mutations/reparenting do not alter active affected nodes or transformations.
        """
        # 1. Topology and transport are provided by fixtures (net, transport)
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

        # 2. Construct an engine with a backhaul fault on LINK-AGG-01-SITE-01
        fault = Fault("F_BH", FaultType.BACKHAUL_FAILURE, "LINK-AGG-01-SITE-01", t, t + timedelta(minutes=15))
        engine = FaultScenarioEngine(net, transport, [fault])

        # 3. Record its ground-truth affected nodes (deterministic BFS: SITE-01, CELL-01, CELL-02, CELL-03)
        gt_affected = engine.get_ground_truth()[0].affected_node_ids
        assert gt_affected == ("SITE-01", "CELL-01", "CELL-02", "CELL-03")

        # 4. Reparent a descendant node after engine construction (CELL-01 reparented from SITE-01 to SITE-02)
        net.set_parent("CELL-01", "SITE-02")
        # Verify in topology itself that CELL-01 is no longer a descendant of SITE-01
        current_site1_descendants = {d.node_id for d in net.get_descendants("SITE-01")}
        assert "CELL-01" not in current_site1_descendants

        # 5. Evaluate the active fault
        active_map = engine.get_active_affected_nodes(t)
        base_step = gen.generate_step(timestamp=t)
        effective_step = engine.apply_faults(base_step, timestamp=t)

        # 6. Verify that the engine's affected-node mapping and telemetry transformation still use the original recorded impact set
        assert set(active_map.keys()) == set(gt_affected)
        assert "CELL-01" in active_map

        cell1_eff = next(s for s in effective_step if s.node_id == "CELL-01")
        # Under outage, throughput and availability are 0.0
        assert cell1_eff.performance.throughput_mbps == 0.0
        assert cell1_eff.reliability.availability_pct == 0.0

        for nid in gt_affected:
            eff_snap = next(s for s in effective_step if s.node_id == nid)
            assert eff_snap.performance.throughput_mbps == 0.0
            assert eff_snap.reliability.availability_pct == 0.0

    def test_stored_affected_nodes_encapsulation(
        self, net: Topology, transport: TransportNetwork
    ) -> None:
        """Callers cannot mutate the stored affected-node collections."""
        t = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        fault = Fault("F_BH", FaultType.BACKHAUL_FAILURE, "LINK-AGG-01-SITE-01", t, t + timedelta(minutes=15))
        engine = FaultScenarioEngine(net, transport, [fault])

        # Ground truth affected nodes is an immutable tuple
        gt = engine.get_ground_truth()[0]
        assert isinstance(gt.affected_node_ids, tuple)

        # Modifying the mapping returned by get_active_affected_nodes does not mutate internal engine state
        active_map = engine.get_active_affected_nodes(t)
        active_map.clear()
        assert len(engine.get_active_affected_nodes(t)) > 0


class TestReferenceScenariosSuite:
    """Tests for the reference scenarios suite covering all 5 fault types."""

    @pytest.fixture
    def net(self) -> Topology:
        return build_simulated_network()

    @pytest.fixture
    def transport(self, net: Topology) -> TransportNetwork:
        return build_reference_transport_network(net)

    def test_reference_scenarios_builder_completeness(
        self, net: Topology, transport: TransportNetwork
    ) -> None:
        base_time = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        scenarios = build_reference_scenarios(net, transport, base_time=base_time)

        expected_keys = {
            "cell_outage",
            "backhaul_failure",
            "radio_interference",
            "cell_congestion",
            "site_power_failure",
        }
        assert set(scenarios.keys()) == expected_keys

        for key, engine in scenarios.items():
            assert isinstance(engine, FaultScenarioEngine)
            gt_records = engine.get_ground_truth()
            assert len(gt_records) >= 1
            for gt in gt_records:
                assert gt.scenario_id.startswith("SCENARIO-")
                assert len(gt.affected_node_ids) > 0
                assert gt.start_time >= base_time
                assert gt.end_time > gt.start_time

    def test_reproducible_scenario_replay(
        self, net: Topology, transport: TransportNetwork
    ) -> None:
        """Running the same scenario at identical timestamps produces identical outputs."""
        base_time = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        suite1 = build_reference_scenarios(net, transport, base_time=base_time)
        suite2 = build_reference_scenarios(net, transport, base_time=base_time)

        gen1 = SyntheticTelemetryGenerator(net, seed=55)
        gen2 = SyntheticTelemetryGenerator(net, seed=55)

        t_active = base_time + timedelta(minutes=10)
        base1 = gen1.generate_step(timestamp=t_active)
        base2 = gen2.generate_step(timestamp=t_active)

        eff1 = suite1["backhaul_failure"].apply_faults(base1, timestamp=t_active)
        eff2 = suite2["backhaul_failure"].apply_faults(base2, timestamp=t_active)

        assert eff1 == eff2
