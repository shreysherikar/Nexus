"""Predefined reference fault scenarios covering standard failure profiles."""

from datetime import datetime, timedelta, timezone

from nexus.fault.engine import FaultScenarioEngine
from nexus.fault.models import Fault, FaultType
from nexus.topology.topology import Topology
from nexus.transport.network import TransportNetwork


def build_reference_scenarios(
    topology: Topology,
    transport: TransportNetwork,
    base_time: datetime = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc),
) -> dict[str, FaultScenarioEngine]:
    """Create a standard suite of 5 reference fault scenarios for benchmarking.

    Scenarios:
    1. 'cell_outage': Single CELL outage (CELL-01 becomes unavailable).
    2. 'backhaul_failure': Transport link cut (LINK-AGG-01-SITE-01 fails, affecting SITE-01 and CELL-01..03).
    3. 'radio_interference': RF interference on CELL-05 (lowers SINR & throughput).
    4. 'cell_congestion': Heavy PRB utilization spike on CELL-10 (causes scheduling latency).
    5. 'site_power_failure': Complete facility power failure at SITE-04 (takes SITE-04 and CELL-10..12 offline).

    Args:
        topology: The 27-node reference network topology.
        transport: The 26-link reference transport network.
        base_time: Base UTC timestamp for scenario time windows (default 12:00:00 UTC).

    Returns:
        Dict mapping scenario key to initialized FaultScenarioEngine.
    """
    scenarios: dict[str, FaultScenarioEngine] = {}

    # 1. Single Cell Outage
    scenarios["cell_outage"] = FaultScenarioEngine(
        topology=topology,
        transport=transport,
        scenario_id="SCENARIO-CELL-OUTAGE-01",
        description="Single radio sector failure on CELL-01",
        faults=[
            Fault(
                fault_id="FAULT-OUTAGE-CELL-01",
                fault_type=FaultType.CELL_OUTAGE,
                target_id="CELL-01",
                start_time=base_time + timedelta(minutes=5),
                end_time=base_time + timedelta(minutes=15),
                severity=1.0,
                description="Cell hardware failure causing radio unavailability",
            )
        ],
    )

    # 2. Backhaul Transport Failure
    # LINK-AGG-01-SITE-01 is upstream AGG-01 -> downstream SITE-01
    scenarios["backhaul_failure"] = FaultScenarioEngine(
        topology=topology,
        transport=transport,
        scenario_id="SCENARIO-BACKHAUL-FAIL-01",
        description="Fiber cut on backhaul transport link from AGG-01 to SITE-01",
        faults=[
            Fault(
                fault_id="FAULT-BACKHAUL-AGG1-SITE1",
                fault_type=FaultType.BACKHAUL_FAILURE,
                target_id="LINK-AGG-01-SITE-01",
                start_time=base_time + timedelta(minutes=10),
                end_time=base_time + timedelta(minutes=25),
                severity=1.0,
                description="Fiber severance isolating SITE-01 and its 3 subordinate cells",
            )
        ],
    )

    # 3. Radio Interference
    scenarios["radio_interference"] = FaultScenarioEngine(
        topology=topology,
        transport=transport,
        scenario_id="SCENARIO-INTERFERENCE-01",
        description="Severe external RF interference on CELL-05",
        faults=[
            Fault(
                fault_id="FAULT-RF-INTERFERENCE-CELL-05",
                fault_type=FaultType.RADIO_INTERFERENCE,
                target_id="CELL-05",
                start_time=base_time + timedelta(minutes=2),
                end_time=base_time + timedelta(minutes=12),
                severity=0.8,
                description="Unlicensed spectrum interference degrading signal-to-noise ratio",
            )
        ],
    )

    # 4. Cell Congestion
    scenarios["cell_congestion"] = FaultScenarioEngine(
        topology=topology,
        transport=transport,
        scenario_id="SCENARIO-CONGESTION-01",
        description="Stadium event traffic surge causing cell saturation on CELL-10",
        faults=[
            Fault(
                fault_id="FAULT-CONGESTION-CELL-10",
                fault_type=FaultType.CELL_CONGESTION,
                target_id="CELL-10",
                start_time=base_time + timedelta(minutes=15),
                end_time=base_time + timedelta(minutes=30),
                severity=0.9,
                description="High PRB utilization causing scheduler queuing delays",
            )
        ],
    )

    # 5. Site Power Failure
    scenarios["site_power_failure"] = FaultScenarioEngine(
        topology=topology,
        transport=transport,
        scenario_id="SCENARIO-POWER-FAIL-01",
        description="Mains grid outage with failed generator backup at SITE-04",
        faults=[
            Fault(
                fault_id="FAULT-POWER-SITE-04",
                fault_type=FaultType.SITE_POWER_FAILURE,
                target_id="SITE-04",
                start_time=base_time + timedelta(minutes=20),
                end_time=base_time + timedelta(minutes=45),
                severity=1.0,
                description="Complete facility blackout taking down SITE-04 and CELL-10..12",
            )
        ],
    )

    return scenarios
