"""Unit and integration tests for the Telemetry and Synthetic KPI Generator domain."""

from datetime import datetime, timedelta, timezone
import math
import pytest

from nexus.telemetry import (
    DEFAULT_CELL_PROFILE,
    DEFAULT_CORE_PROFILE,
    DEFAULT_PROFILES,
    IncompatibleNodeError,
    InvalidKPIValueError,
    InvalidProfileError,
    KPISnapshot,
    MetricRange,
    NodeOperatingProfile,
    PerformanceMetrics,
    RadioMetrics,
    ReliabilityMetrics,
    SyntheticTelemetryGenerator,
)
from nexus.topology import (
    NodeNotFoundError,
    NodeType,
    Topology,
    build_simulated_network,
)


class TestKPIModelValidation:
    """Tests for typed KPI models, bounds enforcement, and snapshot integrity."""

    def test_valid_radio_metrics(self) -> None:
        rm = RadioMetrics(rsrp_dbm=-85.5, sinr_db=18.2, prb_utilization_pct=45.0)
        assert rm.rsrp_dbm == -85.5
        assert rm.sinr_db == 18.2
        assert rm.prb_utilization_pct == 45.0

    def test_invalid_radio_metrics_bounds(self) -> None:
        # Invalid PRB (> 100%)
        with pytest.raises(InvalidKPIValueError, match="prb_utilization_pct"):
            RadioMetrics(rsrp_dbm=-85.0, sinr_db=15.0, prb_utilization_pct=105.0)

        # Invalid PRB (< 0%)
        with pytest.raises(InvalidKPIValueError, match="prb_utilization_pct"):
            RadioMetrics(rsrp_dbm=-85.0, sinr_db=15.0, prb_utilization_pct=-1.0)

        # Invalid RSRP
        with pytest.raises(InvalidKPIValueError, match="rsrp_dbm"):
            RadioMetrics(rsrp_dbm=-160.0, sinr_db=15.0, prb_utilization_pct=50.0)

        # Non-numeric value
        with pytest.raises(InvalidKPIValueError, match="must be a numeric value"):
            RadioMetrics(rsrp_dbm="bad", sinr_db=15.0, prb_utilization_pct=50.0)  # type: ignore[arg-type]

    @pytest.mark.parametrize("invalid_num", [float("nan"), float("inf"), float("-inf"), True, False])
    def test_radio_metrics_rejects_non_finite_and_bools(self, invalid_num: object) -> None:
        with pytest.raises(InvalidKPIValueError):
            RadioMetrics(rsrp_dbm=invalid_num, sinr_db=15.0, prb_utilization_pct=50.0)  # type: ignore[arg-type]
        with pytest.raises(InvalidKPIValueError):
            RadioMetrics(rsrp_dbm=-85.0, sinr_db=invalid_num, prb_utilization_pct=50.0)  # type: ignore[arg-type]
        with pytest.raises(InvalidKPIValueError):
            RadioMetrics(rsrp_dbm=-85.0, sinr_db=15.0, prb_utilization_pct=invalid_num)  # type: ignore[arg-type]

    def test_valid_performance_metrics(self) -> None:
        pm = PerformanceMetrics(throughput_mbps=450.0, latency_ms=12.5)
        assert pm.throughput_mbps == 450.0
        assert pm.latency_ms == 12.5

    def test_invalid_performance_metrics(self) -> None:
        # Negative throughput
        with pytest.raises(InvalidKPIValueError, match="throughput_mbps"):
            PerformanceMetrics(throughput_mbps=-10.0, latency_ms=5.0)

        # Negative latency
        with pytest.raises(InvalidKPIValueError, match="latency_ms"):
            PerformanceMetrics(throughput_mbps=100.0, latency_ms=-0.1)

    @pytest.mark.parametrize("invalid_num", [float("nan"), float("inf"), float("-inf"), True, False])
    def test_performance_metrics_rejects_non_finite_and_bools(self, invalid_num: object) -> None:
        with pytest.raises(InvalidKPIValueError):
            PerformanceMetrics(throughput_mbps=invalid_num, latency_ms=10.0)  # type: ignore[arg-type]
        with pytest.raises(InvalidKPIValueError):
            PerformanceMetrics(throughput_mbps=100.0, latency_ms=invalid_num)  # type: ignore[arg-type]

    def test_valid_reliability_metrics(self) -> None:
        # Transport node (no handover rate)
        rel1 = ReliabilityMetrics(connection_drop_rate_pct=0.01, availability_pct=99.99)
        assert rel1.handover_success_rate_pct is None

        # Cell node (with handover rate)
        rel2 = ReliabilityMetrics(
            connection_drop_rate_pct=0.1,
            availability_pct=99.9,
            handover_success_rate_pct=99.5,
        )
        assert rel2.handover_success_rate_pct == 99.5

    def test_invalid_reliability_metrics(self) -> None:
        # Percentage > 100%
        with pytest.raises(InvalidKPIValueError, match="availability_pct"):
            ReliabilityMetrics(connection_drop_rate_pct=0.0, availability_pct=101.0)

        with pytest.raises(InvalidKPIValueError, match="connection_drop_rate_pct"):
            ReliabilityMetrics(connection_drop_rate_pct=-0.5, availability_pct=99.0)

        with pytest.raises(InvalidKPIValueError, match="handover_success_rate_pct"):
            ReliabilityMetrics(
                connection_drop_rate_pct=0.0,
                availability_pct=99.0,
                handover_success_rate_pct=110.0,
            )

    @pytest.mark.parametrize("invalid_num", [float("nan"), float("inf"), float("-inf"), True, False])
    def test_reliability_metrics_rejects_non_finite_and_bools(self, invalid_num: object) -> None:
        with pytest.raises(InvalidKPIValueError):
            ReliabilityMetrics(connection_drop_rate_pct=invalid_num, availability_pct=99.9)  # type: ignore[arg-type]
        with pytest.raises(InvalidKPIValueError):
            ReliabilityMetrics(connection_drop_rate_pct=0.1, availability_pct=invalid_num)  # type: ignore[arg-type]
        with pytest.raises(InvalidKPIValueError):
            ReliabilityMetrics(
                connection_drop_rate_pct=0.1,
                availability_pct=99.9,
                handover_success_rate_pct=invalid_num,  # type: ignore[arg-type]
            )

    def test_valid_kpi_snapshot(self) -> None:
        now = datetime.now(timezone.utc)
        snap = KPISnapshot(
            node_id="CELL-01",
            timestamp=now,
            performance=PerformanceMetrics(throughput_mbps=300.0, latency_ms=15.0),
            reliability=ReliabilityMetrics(
                connection_drop_rate_pct=0.05,
                availability_pct=99.9,
                handover_success_rate_pct=99.2,
            ),
            radio=RadioMetrics(rsrp_dbm=-85.0, sinr_db=20.0, prb_utilization_pct=40.0),
        )
        assert snap.node_id == "CELL-01"
        assert snap.timestamp == now
        assert snap.radio is not None
        assert snap.radio.rsrp_dbm == -85.0

        flat = snap.to_metric_dict()
        assert flat["node_id"] == "CELL-01"
        assert flat["throughput_mbps"] == 300.0
        assert flat["rsrp_dbm"] == -85.0

    def test_timestamp_normalization_naive_datetime(self) -> None:
        """Naive datetime is interpreted as UTC."""
        naive = datetime(2026, 10, 30, 12, 0, 0)
        snap = KPISnapshot(
            node_id="CORE-01",
            timestamp=naive,
            performance=PerformanceMetrics(throughput_mbps=9000.0, latency_ms=1.2),
            reliability=ReliabilityMetrics(connection_drop_rate_pct=0.001, availability_pct=100.0),
        )
        assert snap.timestamp.tzinfo is not None
        assert snap.timestamp.tzinfo == timezone.utc
        assert snap.timestamp.hour == 12
        assert snap.timestamp.minute == 0

    def test_timestamp_normalization_utc_aware(self) -> None:
        """UTC-aware datetime is preserved as UTC."""
        utc_ts = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        snap = KPISnapshot(
            node_id="CORE-01",
            timestamp=utc_ts,
            performance=PerformanceMetrics(throughput_mbps=9000.0, latency_ms=1.2),
            reliability=ReliabilityMetrics(connection_drop_rate_pct=0.001, availability_pct=100.0),
        )
        assert snap.timestamp == utc_ts
        assert snap.timestamp.tzinfo == timezone.utc

    def test_timestamp_normalization_non_utc_aware(self) -> None:
        """Non-UTC aware datetime (e.g., UTC+05:30) is converted to UTC preserving the instant."""
        tz_plus_530 = timezone(timedelta(hours=5, minutes=30))
        local_ts = datetime(2026, 10, 30, 15, 30, 0, tzinfo=tz_plus_530)
        snap = KPISnapshot(
            node_id="CORE-01",
            timestamp=local_ts,
            performance=PerformanceMetrics(throughput_mbps=9000.0, latency_ms=1.2),
            reliability=ReliabilityMetrics(connection_drop_rate_pct=0.001, availability_pct=100.0),
        )
        assert snap.timestamp.tzinfo == timezone.utc
        # 15:30 UTC+5:30 is 10:00 UTC
        assert snap.timestamp.hour == 10
        assert snap.timestamp.minute == 0
        assert snap.timestamp == local_ts

    def test_timestamp_invalid_types(self) -> None:
        """Invalid timestamp types must raise InvalidKPIValueError."""
        with pytest.raises(InvalidKPIValueError, match="timestamp must be a datetime"):
            KPISnapshot(
                node_id="CORE-01",
                timestamp="2026-10-30T12:00:00Z",  # type: ignore[arg-type]
                performance=PerformanceMetrics(10.0, 1.0),
                reliability=ReliabilityMetrics(0.01, 99.9),
            )
        with pytest.raises(InvalidKPIValueError, match="timestamp must be a datetime"):
            KPISnapshot(
                node_id="CORE-01",
                timestamp=1730289600,  # type: ignore[arg-type]
                performance=PerformanceMetrics(10.0, 1.0),
                reliability=ReliabilityMetrics(0.01, 99.9),
            )

    def test_invalid_snapshot_attributes(self) -> None:
        now = datetime.now(timezone.utc)
        with pytest.raises(InvalidKPIValueError, match="node_id must be a non-empty string"):
            KPISnapshot(
                node_id="  ",
                timestamp=now,
                performance=PerformanceMetrics(10.0, 1.0),
                reliability=ReliabilityMetrics(0.01, 99.9),
            )

        with pytest.raises(InvalidKPIValueError, match="performance must be an instance"):
            KPISnapshot(
                node_id="CORE-01",
                timestamp=now,
                performance={"throughput_mbps": 10.0},  # type: ignore[arg-type]
                reliability=ReliabilityMetrics(0.01, 99.9),
            )


class TestOperatingProfiles:
    """Tests for profile validation and boundary constraints."""

    def test_metric_range_validation(self) -> None:
        # Valid range
        r = MetricRange(min_val=10.0, max_val=20.0, nominal=15.0)
        assert r.nominal == 15.0

        # Min > Max
        with pytest.raises(InvalidProfileError, match="cannot be greater than max_val"):
            MetricRange(min_val=30.0, max_val=20.0, nominal=25.0)

        # Nominal outside bounds
        with pytest.raises(InvalidProfileError, match="must be within"):
            MetricRange(min_val=10.0, max_val=20.0, nominal=25.0)

    @pytest.mark.parametrize("invalid_num", [float("nan"), float("inf"), float("-inf"), True, False, "10"])
    def test_metric_range_rejects_non_finite_and_bools(self, invalid_num: object) -> None:
        with pytest.raises(InvalidProfileError):
            MetricRange(min_val=invalid_num, max_val=20.0, nominal=15.0)  # type: ignore[arg-type]
        with pytest.raises(InvalidProfileError):
            MetricRange(min_val=10.0, max_val=invalid_num, nominal=15.0)  # type: ignore[arg-type]
        with pytest.raises(InvalidProfileError):
            MetricRange(min_val=10.0, max_val=20.0, nominal=invalid_num)  # type: ignore[arg-type]

    def test_semantic_metric_boundaries_rejected_at_construction(self) -> None:
        """Metric-specific semantic constraints must be enforced during NodeOperatingProfile construction."""
        # 1. Negative throughput
        with pytest.raises(InvalidProfileError, match="throughput_mbps minimum.*cannot be less than 0.0"):
            NodeOperatingProfile(
                node_type=NodeType.CORE,
                throughput_mbps=MetricRange(-5.0, 100.0, 50.0),
                latency_ms=MetricRange(1.0, 5.0, 2.0),
                connection_drop_rate_pct=MetricRange(0.0, 0.1, 0.05),
                availability_pct=MetricRange(99.0, 100.0, 99.9),
            )

        # 2. Negative latency
        with pytest.raises(InvalidProfileError, match="latency_ms minimum.*cannot be less than 0.0"):
            NodeOperatingProfile(
                node_type=NodeType.CORE,
                throughput_mbps=MetricRange(100.0, 500.0, 300.0),
                latency_ms=MetricRange(-1.0, 5.0, 2.0),
                connection_drop_rate_pct=MetricRange(0.0, 0.1, 0.05),
                availability_pct=MetricRange(99.0, 100.0, 99.9),
            )

        # 3. Drop rate < 0% or > 100%
        with pytest.raises(InvalidProfileError, match="connection_drop_rate_pct maximum.*cannot exceed 100.0"):
            NodeOperatingProfile(
                node_type=NodeType.CORE,
                throughput_mbps=MetricRange(100.0, 500.0, 300.0),
                latency_ms=MetricRange(1.0, 5.0, 2.0),
                connection_drop_rate_pct=MetricRange(0.0, 105.0, 50.0),
                availability_pct=MetricRange(99.0, 100.0, 99.9),
            )

        # 4. Availability < 0% or > 100%
        with pytest.raises(InvalidProfileError, match="availability_pct minimum.*cannot be less than 0.0"):
            NodeOperatingProfile(
                node_type=NodeType.CORE,
                throughput_mbps=MetricRange(100.0, 500.0, 300.0),
                latency_ms=MetricRange(1.0, 5.0, 2.0),
                connection_drop_rate_pct=MetricRange(0.0, 0.1, 0.05),
                availability_pct=MetricRange(-1.0, 100.0, 99.0),
            )

        # 5. Handover success rate > 100% on CELL
        with pytest.raises(InvalidProfileError, match="handover_success_rate_pct maximum.*cannot exceed 100.0"):
            NodeOperatingProfile(
                node_type=NodeType.CELL,
                throughput_mbps=MetricRange(100.0, 500.0, 300.0),
                latency_ms=MetricRange(10.0, 30.0, 20.0),
                connection_drop_rate_pct=MetricRange(0.05, 0.50, 0.15),
                availability_pct=MetricRange(99.0, 100.0, 99.5),
                handover_success_rate_pct=MetricRange(95.0, 105.0, 98.0),
                rsrp_dbm=MetricRange(-105.0, -75.0, -88.0),
                sinr_db=MetricRange(10.0, 30.0, 20.0),
                prb_utilization_pct=MetricRange(20.0, 60.0, 40.0),
            )

        # 6. PRB utilization > 100% on CELL
        with pytest.raises(InvalidProfileError, match="prb_utilization_pct maximum.*cannot exceed 100.0"):
            NodeOperatingProfile(
                node_type=NodeType.CELL,
                throughput_mbps=MetricRange(100.0, 500.0, 300.0),
                latency_ms=MetricRange(10.0, 30.0, 20.0),
                connection_drop_rate_pct=MetricRange(0.05, 0.50, 0.15),
                availability_pct=MetricRange(99.0, 100.0, 99.5),
                handover_success_rate_pct=MetricRange(95.0, 100.0, 98.0),
                rsrp_dbm=MetricRange(-105.0, -75.0, -88.0),
                sinr_db=MetricRange(10.0, 30.0, 20.0),
                prb_utilization_pct=MetricRange(20.0, 110.0, 40.0),
            )

        # 7. RSRP out of broad physical limits [-150, -30]
        with pytest.raises(InvalidProfileError, match="rsrp_dbm minimum.*cannot be less than -150.0"):
            NodeOperatingProfile(
                node_type=NodeType.CELL,
                throughput_mbps=MetricRange(100.0, 500.0, 300.0),
                latency_ms=MetricRange(10.0, 30.0, 20.0),
                connection_drop_rate_pct=MetricRange(0.05, 0.50, 0.15),
                availability_pct=MetricRange(99.0, 100.0, 99.5),
                handover_success_rate_pct=MetricRange(95.0, 100.0, 98.0),
                rsrp_dbm=MetricRange(-160.0, -75.0, -88.0),
                sinr_db=MetricRange(10.0, 30.0, 20.0),
                prb_utilization_pct=MetricRange(20.0, 60.0, 40.0),
            )

        # 8. SINR out of broad physical limits [-30, 50]
        with pytest.raises(InvalidProfileError, match="sinr_db maximum.*cannot exceed 50.0"):
            NodeOperatingProfile(
                node_type=NodeType.CELL,
                throughput_mbps=MetricRange(100.0, 500.0, 300.0),
                latency_ms=MetricRange(10.0, 30.0, 20.0),
                connection_drop_rate_pct=MetricRange(0.05, 0.50, 0.15),
                availability_pct=MetricRange(99.0, 100.0, 99.5),
                handover_success_rate_pct=MetricRange(95.0, 100.0, 98.0),
                rsrp_dbm=MetricRange(-105.0, -75.0, -88.0),
                sinr_db=MetricRange(10.0, 60.0, 20.0),
                prb_utilization_pct=MetricRange(20.0, 60.0, 40.0),
            )

    def test_profile_tier_consistency(self) -> None:
        # Non-cell profile with radio metric configured
        with pytest.raises(InvalidProfileError, match="must not specify radio-only or handover ranges"):
            NodeOperatingProfile(
                node_type=NodeType.CORE,
                throughput_mbps=MetricRange(100.0, 200.0, 150.0),
                latency_ms=MetricRange(1.0, 5.0, 2.0),
                connection_drop_rate_pct=MetricRange(0.0, 0.1, 0.05),
                availability_pct=MetricRange(99.0, 100.0, 99.9),
                rsrp_dbm=MetricRange(-100.0, -80.0, -90.0),  # Disallowed for CORE
            )

        # Non-cell profile with handover configured
        with pytest.raises(InvalidProfileError, match="must not specify radio-only or handover ranges"):
            NodeOperatingProfile(
                node_type=NodeType.AGGREGATION,
                throughput_mbps=MetricRange(100.0, 200.0, 150.0),
                latency_ms=MetricRange(1.0, 5.0, 2.0),
                connection_drop_rate_pct=MetricRange(0.0, 0.1, 0.05),
                availability_pct=MetricRange(99.0, 100.0, 99.9),
                handover_success_rate_pct=MetricRange(98.0, 100.0, 99.0),  # Disallowed for AGG
            )

        # Cell profile missing handover metric configured
        with pytest.raises(InvalidProfileError, match="CELL operating profile requires handover_success_rate_pct"):
            NodeOperatingProfile(
                node_type=NodeType.CELL,
                throughput_mbps=MetricRange(100.0, 200.0, 150.0),
                latency_ms=MetricRange(1.0, 5.0, 2.0),
                connection_drop_rate_pct=MetricRange(0.0, 0.1, 0.05),
                availability_pct=MetricRange(99.0, 100.0, 99.9),
                rsrp_dbm=MetricRange(-100.0, -80.0, -90.0),
                sinr_db=MetricRange(10.0, 30.0, 20.0),
                prb_utilization_pct=MetricRange(20.0, 60.0, 40.0),
                handover_success_rate_pct=None,
            )

        # Cell profile missing radio metric configured
        with pytest.raises(InvalidProfileError, match="CELL operating profile requires"):
            NodeOperatingProfile(
                node_type=NodeType.CELL,
                throughput_mbps=MetricRange(100.0, 200.0, 150.0),
                latency_ms=MetricRange(1.0, 5.0, 2.0),
                connection_drop_rate_pct=MetricRange(0.0, 0.1, 0.05),
                availability_pct=MetricRange(99.0, 100.0, 99.9),
                handover_success_rate_pct=MetricRange(98.0, 100.0, 99.0),
                # Missing rsrp, sinr, prb
            )

    def test_profile_rejects_non_metric_range_instances(self) -> None:
        with pytest.raises(InvalidProfileError, match="must be an instance of MetricRange"):
            NodeOperatingProfile(
                node_type=NodeType.CORE,
                throughput_mbps={"min": 100, "max": 200, "nominal": 150},  # type: ignore[arg-type]
                latency_ms=MetricRange(1.0, 5.0, 2.0),
                connection_drop_rate_pct=MetricRange(0.0, 0.1, 0.05),
                availability_pct=MetricRange(99.0, 100.0, 99.9),
            )

    def test_default_profiles_cover_all_node_types(self) -> None:
        for node_type in NodeType:
            assert node_type in DEFAULT_PROFILES
            prof = DEFAULT_PROFILES[node_type]
            assert prof.node_type == node_type


class TestSyntheticTelemetryGenerator:
    """Tests for deterministic generation, temporal continuity, and cross-metric relationships."""

    @pytest.fixture
    def net(self) -> Topology:
        return build_simulated_network()

    def test_generator_seed_validation(self, net: Topology) -> None:
        """Seed must be int or None, rejecting booleans, floats, and strings."""
        # Valid seeds
        g1 = SyntheticTelemetryGenerator(net, seed=0)
        assert g1 is not None
        g2 = SyntheticTelemetryGenerator(net, seed=999)
        assert g2 is not None
        g3 = SyntheticTelemetryGenerator(net, seed=None)
        assert g3 is not None

        # Rejected seeds
        with pytest.raises(TypeError, match="seed must be an integer or None"):
            SyntheticTelemetryGenerator(net, seed=True)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="seed must be an integer or None"):
            SyntheticTelemetryGenerator(net, seed=False)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="seed must be an integer or None"):
            SyntheticTelemetryGenerator(net, seed=42.5)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="seed must be an integer or None"):
            SyntheticTelemetryGenerator(net, seed="42")  # type: ignore[arg-type]

    def test_generator_alpha_validation(self, net: Topology) -> None:
        # Valid alpha boundaries
        g0 = SyntheticTelemetryGenerator(net, alpha=0.0)
        assert g0._alpha == 0.0
        g1 = SyntheticTelemetryGenerator(net, alpha=1.0)
        assert g1._alpha == 1.0

        # Invalid alpha: outside [0, 1]
        with pytest.raises(ValueError, match="alpha must be a finite number between 0.0 and 1.0"):
            SyntheticTelemetryGenerator(net, alpha=-0.1)
        with pytest.raises(ValueError, match="alpha must be a finite number between 0.0 and 1.0"):
            SyntheticTelemetryGenerator(net, alpha=1.01)

        # Invalid alpha: boolean, nan, inf
        with pytest.raises(ValueError, match="alpha must be a numeric value"):
            SyntheticTelemetryGenerator(net, alpha=True)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="alpha must be a finite number"):
            SyntheticTelemetryGenerator(net, alpha=float("nan"))
        with pytest.raises(ValueError, match="alpha must be a finite number"):
            SyntheticTelemetryGenerator(net, alpha=float("inf"))

    def test_custom_profile_validation_mismatched_key(self, net: Topology) -> None:
        # Mapping key AGGREGATION maps to CORE profile
        bad_mapping = {
            NodeType.AGGREGATION: DEFAULT_CORE_PROFILE,
        }
        with pytest.raises(InvalidProfileError, match="Profile key AGGREGATION does not match profile.node_type CORE"):
            SyntheticTelemetryGenerator(net, profiles=bad_mapping)

    def test_custom_profile_validation_invalid_type(self, net: Topology) -> None:
        bad_mapping = {
            NodeType.CORE: "not-a-profile",
        }
        with pytest.raises(InvalidProfileError, match="Expected NodeOperatingProfile"):
            SyntheticTelemetryGenerator(net, profiles=bad_mapping)  # type: ignore[dict-item]

    def test_partial_profile_mapping_supported_and_raises_incompatible_node_error(self, net: Topology) -> None:
        """Partial profile mapping is explicitly supported at init; unconfigured nodes raise IncompatibleNodeError during generation."""
        # Only configure CORE and AGGREGATION
        partial_mapping = {
            NodeType.CORE: DEFAULT_CORE_PROFILE,
            NodeType.AGGREGATION: DEFAULT_CORE_PROFILE.__class__(
                node_type=NodeType.AGGREGATION,
                throughput_mbps=MetricRange(1000.0, 2000.0, 1500.0),
                latency_ms=MetricRange(2.0, 5.0, 3.0),
                connection_drop_rate_pct=MetricRange(0.01, 0.05, 0.02),
                availability_pct=MetricRange(99.0, 100.0, 99.5),
            ),
        }
        gen = SyntheticTelemetryGenerator(net, seed=42, profiles=partial_mapping)

        # CORE and AGGREGATION nodes succeed
        assert gen.generate_node_snapshot("CORE-01").node_id == "CORE-01"
        assert gen.generate_node_snapshot("AGG-01").node_id == "AGG-01"

        # SITE and CELL nodes lack profiles in partial mapping, raising IncompatibleNodeError
        with pytest.raises(IncompatibleNodeError, match="No operating profile configured for node type: SITE"):
            gen.generate_node_snapshot("SITE-01")
        with pytest.raises(IncompatibleNodeError, match="No operating profile configured for node type: CELL"):
            gen.generate_node_snapshot("CELL-01")

    def test_deterministic_generation_with_same_seed_and_timestamps(self, net: Topology) -> None:
        """Two generators with same seed and same explicit timestamps produce identical complete snapshots."""
        gen1 = SyntheticTelemetryGenerator(net, seed=12345)
        gen2 = SyntheticTelemetryGenerator(net, seed=12345)

        base_time = datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc)

        # Run 3 consecutive steps
        for step_i in range(3):
            ts = base_time + timedelta(seconds=step_i * 5)
            step1 = gen1.generate_step(timestamp=ts)
            step2 = gen2.generate_step(timestamp=ts)

            assert len(step1) == len(step2) == 27
            for s1, s2 in zip(step1, step2):
                assert s1.node_id == s2.node_id
                assert s1.timestamp == s2.timestamp == ts
                assert s1.performance == s2.performance
                assert s1.reliability == s2.reliability
                assert s1.radio == s2.radio

    def test_divergent_generation_with_different_seeds(self, net: Topology) -> None:
        """Generators with different seeds produce distinct metric values."""
        gen1 = SyntheticTelemetryGenerator(net, seed=100)
        gen2 = SyntheticTelemetryGenerator(net, seed=200)

        snap1 = gen1.generate_node_snapshot("CELL-01")
        snap2 = gen2.generate_node_snapshot("CELL-01")

        assert snap1.node_id == snap2.node_id == "CELL-01"
        assert snap1.performance != snap2.performance

    def test_node_type_metric_structure(self, net: Topology) -> None:
        """Verify radio metrics are generated for CELL nodes and omitted for non-CELL nodes."""
        gen = SyntheticTelemetryGenerator(net, seed=42)
        step = gen.generate_step()

        for snap in step:
            node = net.get_node(snap.node_id)
            if node.node_type == NodeType.CELL:
                assert snap.radio is not None
                assert -105.0 <= snap.radio.rsrp_dbm <= -75.0
                assert 10.0 <= snap.radio.sinr_db <= 30.0
                assert 20.0 <= snap.radio.prb_utilization_pct <= 65.0
                assert snap.reliability.handover_success_rate_pct is not None
            else:
                assert snap.radio is None
                assert snap.reliability.handover_success_rate_pct is None

    def test_kpi_values_respect_profile_bounds_over_steps(self, net: Topology) -> None:
        """Verify that across multiple simulation steps, all KPIs stay within profile bounds."""
        gen = SyntheticTelemetryGenerator(net, seed=999)
        core_prof = DEFAULT_CORE_PROFILE
        cell_prof = DEFAULT_CELL_PROFILE

        for _ in range(10):
            step = gen.generate_step()
            for snap in step:
                node = net.get_node(snap.node_id)
                if node.node_type == NodeType.CORE:
                    assert (
                        core_prof.throughput_mbps.min_val
                        <= snap.performance.throughput_mbps
                        <= core_prof.throughput_mbps.max_val
                    )
                    assert (
                        core_prof.latency_ms.min_val
                        <= snap.performance.latency_ms
                        <= core_prof.latency_ms.max_val
                    )
                elif node.node_type == NodeType.CELL:
                    assert (
                        cell_prof.throughput_mbps.min_val
                        <= snap.performance.throughput_mbps
                        <= cell_prof.throughput_mbps.max_val
                    )
                    assert (
                        cell_prof.latency_ms.min_val
                        <= snap.performance.latency_ms
                        <= cell_prof.latency_ms.max_val
                    )
                    assert snap.radio is not None
                    assert (
                        cell_prof.prb_utilization_pct.min_val  # type: ignore[union-attr]
                        <= snap.radio.prb_utilization_pct
                        <= cell_prof.prb_utilization_pct.max_val  # type: ignore[union-attr]
                    )

    def test_temporal_continuity(self, net: Topology) -> None:
        """Successive steps should exhibit smooth transitions rather than wild jumps."""
        gen = SyntheticTelemetryGenerator(net, seed=42, alpha=0.8)
        prev_tp = None

        # Sample 5 consecutive steps for CORE-01
        for _ in range(5):
            snap = gen.generate_node_snapshot("CORE-01")
            curr_tp = snap.performance.throughput_mbps
            if prev_tp is not None:
                # With alpha=0.8, deviation from prev is damped
                diff = abs(curr_tp - prev_tp)
                assert diff < 800.0  # Much less than the total 2000 Mbps range
            prev_tp = curr_tp

    def test_sinr_response_under_controlled_profiles(self, net: Topology) -> None:
        """Higher SINR profile yields higher average throughput for CELL nodes."""
        low_sinr_profile = NodeOperatingProfile(
            node_type=NodeType.CELL,
            throughput_mbps=MetricRange(100.0, 500.0, 300.0),
            latency_ms=MetricRange(10.0, 30.0, 20.0),
            connection_drop_rate_pct=MetricRange(0.05, 0.50, 0.15),
            availability_pct=MetricRange(99.0, 100.0, 99.5),
            handover_success_rate_pct=MetricRange(95.0, 100.0, 98.0),
            rsrp_dbm=MetricRange(-105.0, -75.0, -88.0),
            sinr_db=MetricRange(0.0, 10.0, 5.0),  # Low SINR
            prb_utilization_pct=MetricRange(40.0, 40.0, 40.0),  # Fixed PRB
        )
        high_sinr_profile = NodeOperatingProfile(
            node_type=NodeType.CELL,
            throughput_mbps=MetricRange(100.0, 500.0, 300.0),
            latency_ms=MetricRange(10.0, 30.0, 20.0),
            connection_drop_rate_pct=MetricRange(0.05, 0.50, 0.15),
            availability_pct=MetricRange(99.0, 100.0, 99.5),
            handover_success_rate_pct=MetricRange(95.0, 100.0, 98.0),
            rsrp_dbm=MetricRange(-105.0, -75.0, -88.0),
            sinr_db=MetricRange(30.0, 40.0, 35.0),  # High SINR
            prb_utilization_pct=MetricRange(40.0, 40.0, 40.0),  # Fixed PRB
        )

        gen_low = SyntheticTelemetryGenerator(net, seed=77, profiles={NodeType.CELL: low_sinr_profile}, alpha=0.0)
        gen_high = SyntheticTelemetryGenerator(net, seed=77, profiles={NodeType.CELL: high_sinr_profile}, alpha=0.0)

        tp_low = [gen_low.generate_node_snapshot("CELL-01").performance.throughput_mbps for _ in range(5)]
        tp_high = [gen_high.generate_node_snapshot("CELL-01").performance.throughput_mbps for _ in range(5)]

        assert sum(tp_high) / len(tp_high) > sum(tp_low) / len(tp_low)

    def test_prb_congestion_response_under_controlled_profiles(self, net: Topology) -> None:
        """High PRB congestion decreases available throughput and increases latency."""
        low_prb_profile = NodeOperatingProfile(
            node_type=NodeType.CELL,
            throughput_mbps=MetricRange(100.0, 500.0, 300.0),
            latency_ms=MetricRange(10.0, 40.0, 25.0),
            connection_drop_rate_pct=MetricRange(0.05, 0.50, 0.15),
            availability_pct=MetricRange(99.0, 100.0, 99.5),
            handover_success_rate_pct=MetricRange(95.0, 100.0, 98.0),
            rsrp_dbm=MetricRange(-105.0, -75.0, -88.0),
            sinr_db=MetricRange(20.0, 20.0, 20.0),  # Fixed SINR
            prb_utilization_pct=MetricRange(10.0, 20.0, 15.0),  # Low PRB
        )
        high_prb_profile = NodeOperatingProfile(
            node_type=NodeType.CELL,
            throughput_mbps=MetricRange(100.0, 500.0, 300.0),
            latency_ms=MetricRange(10.0, 40.0, 25.0),
            connection_drop_rate_pct=MetricRange(0.05, 0.50, 0.15),
            availability_pct=MetricRange(99.0, 100.0, 99.5),
            handover_success_rate_pct=MetricRange(95.0, 100.0, 98.0),
            rsrp_dbm=MetricRange(-105.0, -75.0, -88.0),
            sinr_db=MetricRange(20.0, 20.0, 20.0),  # Fixed SINR
            prb_utilization_pct=MetricRange(85.0, 95.0, 90.0),  # High PRB
        )

        gen_low = SyntheticTelemetryGenerator(net, seed=88, profiles={NodeType.CELL: low_prb_profile}, alpha=0.0)
        gen_high = SyntheticTelemetryGenerator(net, seed=88, profiles={NodeType.CELL: high_prb_profile}, alpha=0.0)

        samples_low = [gen_low.generate_node_snapshot("CELL-01") for _ in range(5)]
        samples_high = [gen_high.generate_node_snapshot("CELL-01") for _ in range(5)]

        avg_tp_low = sum(s.performance.throughput_mbps for s in samples_low) / len(samples_low)
        avg_tp_high = sum(s.performance.throughput_mbps for s in samples_high) / len(samples_high)
        avg_lat_low = sum(s.performance.latency_ms for s in samples_low) / len(samples_low)
        avg_lat_high = sum(s.performance.latency_ms for s in samples_high) / len(samples_high)

        # High congestion dampens throughput and increases latency
        assert avg_tp_low > avg_tp_high
        assert avg_lat_high > avg_lat_low

    def test_cell_reliability_relationships_under_controlled_conditions(self, net: Topology) -> None:
        """Poor channel conditions and high latency slightly degrade handover rate and increase drop rate."""
        good_profile = NodeOperatingProfile(
            node_type=NodeType.CELL,
            throughput_mbps=MetricRange(100.0, 500.0, 300.0),
            latency_ms=MetricRange(10.0, 20.0, 12.0),
            connection_drop_rate_pct=MetricRange(0.01, 1.0, 0.2),
            availability_pct=MetricRange(99.0, 100.0, 99.5),
            handover_success_rate_pct=MetricRange(90.0, 100.0, 98.0),
            rsrp_dbm=MetricRange(-85.0, -75.0, -80.0),
            sinr_db=MetricRange(25.0, 35.0, 30.0),  # High SINR
            prb_utilization_pct=MetricRange(20.0, 30.0, 25.0),  # Low PRB
        )
        stressed_profile = NodeOperatingProfile(
            node_type=NodeType.CELL,
            throughput_mbps=MetricRange(100.0, 500.0, 300.0),
            latency_ms=MetricRange(30.0, 40.0, 35.0),
            connection_drop_rate_pct=MetricRange(0.01, 1.0, 0.2),
            availability_pct=MetricRange(99.0, 100.0, 99.5),
            handover_success_rate_pct=MetricRange(90.0, 100.0, 98.0),
            rsrp_dbm=MetricRange(-115.0, -105.0, -110.0),
            sinr_db=MetricRange(0.0, 10.0, 5.0),  # Low SINR
            prb_utilization_pct=MetricRange(80.0, 90.0, 85.0),  # High PRB
        )

        gen_good = SyntheticTelemetryGenerator(net, seed=99, profiles={NodeType.CELL: good_profile}, alpha=0.0)
        gen_stressed = SyntheticTelemetryGenerator(net, seed=99, profiles={NodeType.CELL: stressed_profile}, alpha=0.0)

        snaps_good = [gen_good.generate_node_snapshot("CELL-01") for _ in range(5)]
        snaps_stressed = [gen_stressed.generate_node_snapshot("CELL-01") for _ in range(5)]

        avg_hosr_good = sum(s.reliability.handover_success_rate_pct for s in snaps_good if s.reliability.handover_success_rate_pct) / 5
        avg_hosr_stressed = sum(s.reliability.handover_success_rate_pct for s in snaps_stressed if s.reliability.handover_success_rate_pct) / 5

        avg_drop_good = sum(s.reliability.connection_drop_rate_pct for s in snaps_good) / 5
        avg_drop_stressed = sum(s.reliability.connection_drop_rate_pct for s in snaps_stressed) / 5

        assert avg_hosr_good > avg_hosr_stressed
        assert avg_drop_stressed > avg_drop_good

    def test_generator_error_on_unknown_node(self, net: Topology) -> None:
        gen = SyntheticTelemetryGenerator(net, seed=42)
        with pytest.raises(NodeNotFoundError):
            gen.generate_node_snapshot("NON-EXISTENT")

    def test_empty_topology_generation(self) -> None:
        empty_net = Topology()
        gen = SyntheticTelemetryGenerator(empty_net, seed=42)
        snapshots = gen.generate_step()
        assert snapshots == []
