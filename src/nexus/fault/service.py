"""Service layer for network fault injection scenario lifecycle and telemetry transformation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
from typing import Any, Callable, Iterable, Optional

from nexus.fault.engine import FaultScenarioEngine
from nexus.fault.exceptions import ScenarioError
from nexus.fault.models import Fault, FaultType
from nexus.fault.schemas import (
    ActiveScenarioResponse,
    FaultInfo,
    FaultScenarioInfo,
    FaultScenarioListResponse,
)
from nexus.telemetry.models import KPISnapshot
from nexus.topology.api import get_topology_registry
from nexus.topology.topology import Topology
from nexus.transport.builder import build_reference_transport_network
from nexus.transport.network import TransportNetwork

EventPublisher = Callable[[str, dict[str, Any]], None]

SCENARIO_METADATA: dict[str, dict[str, Any]] = {
    "cell_outage": {
        "scenario_id": "SCENARIO-CELL-OUTAGE-01",
        "name": "Single Cell Outage",
        "description": "Single radio sector hardware failure on CELL-01 causing complete loss of cell service.",
        "target_id": "CELL-01",
        "fault_type": FaultType.CELL_OUTAGE,
        "severity": 1.0,
        "default_offset_minutes": 5,
        "default_duration_minutes": 10,
    },
    "backhaul_failure": {
        "scenario_id": "SCENARIO-BACKHAUL-FAIL-01",
        "name": "Backhaul Transport Cut",
        "description": "Fiber severance on backhaul transport link LINK-AGG-01-SITE-01 isolating SITE-01 and CELL-01..03.",
        "target_id": "LINK-AGG-01-SITE-01",
        "fault_type": FaultType.BACKHAUL_FAILURE,
        "severity": 1.0,
        "default_offset_minutes": 10,
        "default_duration_minutes": 15,
    },
    "radio_interference": {
        "scenario_id": "SCENARIO-INTERFERENCE-01",
        "name": "Radio RF Interference",
        "description": "Severe external RF interference on CELL-05 degrading Signal-to-Interference-plus-Noise ratio and throughput.",
        "target_id": "CELL-05",
        "fault_type": FaultType.RADIO_INTERFERENCE,
        "severity": 0.8,
        "default_offset_minutes": 2,
        "default_duration_minutes": 10,
    },
    "cell_congestion": {
        "scenario_id": "SCENARIO-CONGESTION-01",
        "name": "Cell PRB Congestion",
        "description": "Traffic surge saturating PRB utilization on CELL-10, restricting throughput and elevating scheduling latency.",
        "target_id": "CELL-10",
        "fault_type": FaultType.CELL_CONGESTION,
        "severity": 0.9,
        "default_offset_minutes": 15,
        "default_duration_minutes": 15,
    },
    "site_power_failure": {
        "scenario_id": "SCENARIO-POWER-FAIL-01",
        "name": "Site Facility Blackout",
        "description": "Mains grid outage with failed generator backup at SITE-04 taking down SITE-04 and subordinate cells (CELL-10..12).",
        "target_id": "SITE-04",
        "fault_type": FaultType.SITE_POWER_FAILURE,
        "severity": 1.0,
        "default_offset_minutes": 20,
        "default_duration_minutes": 25,
    },
}


class FaultService:
    """Manages active fault scenarios, reference definitions, and telemetry transformation.

    Guarantees:
    - Maintains strict ground-truth isolation: active scenario state is used purely to transform
      telemetry snapshots BEFORE downstream detection ingestion.
    - Deterministic, conflict-checked execution using FaultScenarioEngine.
    - Zero background simulation loops; fault effects apply exclusively when operator triggers steps.
    """

    def __init__(
        self,
        topology: Optional[Topology] = None,
        transport: Optional[TransportNetwork] = None,
        event_publisher: Optional[EventPublisher] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._topology = topology if topology is not None else get_topology_registry()
        self._transport = (
            transport
            if transport is not None
            else build_reference_transport_network(self._topology)
        )
        self._event_publisher = event_publisher

        self._active_key: Optional[str] = None
        self._active_engine: Optional[FaultScenarioEngine] = None
        self._activated_at: Optional[datetime] = None

    def set_event_publisher(self, publisher: Optional[EventPublisher]) -> None:
        with self._lock:
            self._event_publisher = publisher

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        pub = self._event_publisher
        if pub:
            try:
                pub(event_type, payload)
            except Exception:
                pass

    def get_reference_scenarios(self) -> FaultScenarioListResponse:
        """Return the catalog of available reference fault scenarios with active state."""
        with self._lock:
            items: list[FaultScenarioInfo] = []
            for key, meta in SCENARIO_METADATA.items():
                dummy_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
                fault = Fault(
                    fault_id=f"FAULT-REF-{key.upper()}",
                    fault_type=meta["fault_type"],
                    target_id=meta["target_id"],
                    start_time=dummy_time,
                    end_time=dummy_time + timedelta(hours=1),
                    severity=meta["severity"],
                    description=meta["description"],
                )
                engine = FaultScenarioEngine(
                    topology=self._topology,
                    transport=self._transport,
                    faults=[fault],
                    scenario_id=meta["scenario_id"],
                    description=meta["description"],
                )
                gt = engine.get_ground_truth()[0]
                is_active = self._active_key == key

                items.append(
                    FaultScenarioInfo(
                        id=key,
                        scenario_id=meta["scenario_id"],
                        name=meta["name"],
                        description=meta["description"],
                        fault_type=meta["fault_type"].value,
                        target_id=meta["target_id"],
                        severity=meta["severity"],
                        affected_nodes=list(gt.affected_node_ids),
                        is_active=is_active,
                    )
                )

            return FaultScenarioListResponse(
                items=items,
                total=len(items),
                active_scenario_id=self._active_key,
            )

    def activate_scenario(
        self,
        scenario_key: str,
        immediate: bool = True,
        base_time: Optional[datetime] = None,
    ) -> ActiveScenarioResponse:
        """Activate a predefined reference fault scenario.

        Args:
            scenario_key: Key of the scenario (e.g. 'radio_interference').
            immediate: If True, sets time window to cover now immediately for live simulation.
            base_time: Optional reference base timestamp.

        Returns:
            ActiveScenarioResponse with current status.
        """
        with self._lock:
            if scenario_key not in SCENARIO_METADATA:
                raise ScenarioError(
                    f"Unknown scenario_key '{scenario_key}'. Valid scenarios: {list(SCENARIO_METADATA.keys())}"
                )

            meta = SCENARIO_METADATA[scenario_key]
            now = datetime.now(timezone.utc)
            effective_base = base_time or now

            if immediate:
                # Active indefinitely across all simulation steps until explicitly deactivated
                start_t = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
                end_t = datetime(2099, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            else:
                start_t = effective_base + timedelta(minutes=meta["default_offset_minutes"])
                end_t = start_t + timedelta(minutes=meta["default_duration_minutes"])

            fault = Fault(
                fault_id=f"FAULT-ACTIVE-{scenario_key.upper()}",
                fault_type=meta["fault_type"],
                target_id=meta["target_id"],
                start_time=start_t,
                end_time=end_t,
                severity=meta["severity"],
                description=meta["description"],
            )

            engine = FaultScenarioEngine(
                topology=self._topology,
                transport=self._transport,
                faults=[fault],
                scenario_id=meta["scenario_id"],
                description=meta["description"],
            )

            self._active_key = scenario_key
            self._active_engine = engine
            self._activated_at = now

            resp = self.get_active_scenario()

            self._publish(
                "FAULT_STATUS_CHANGED",
                {
                    "active": True,
                    "scenario_key": scenario_key,
                    "scenario_id": meta["scenario_id"],
                    "name": meta["name"],
                    "target_id": meta["target_id"],
                    "fault_type": meta["fault_type"].value,
                    "severity": meta["severity"],
                    "timestamp": now.isoformat(),
                },
            )

            return resp

    def deactivate_scenario(self) -> ActiveScenarioResponse:
        """Deactivate any active fault scenario, returning network to nominal state."""
        with self._lock:
            prev_key = self._active_key
            self._active_key = None
            self._active_engine = None
            self._activated_at = None

            resp = self.get_active_scenario()

            if prev_key is not None:
                now = datetime.now(timezone.utc)
                self._publish(
                    "FAULT_STATUS_CHANGED",
                    {
                        "active": False,
                        "scenario_key": None,
                        "scenario_id": None,
                        "name": None,
                        "target_id": None,
                        "fault_type": None,
                        "severity": None,
                        "timestamp": now.isoformat(),
                    },
                )

            return resp

    def get_active_scenario(self) -> ActiveScenarioResponse:
        """Retrieve current active scenario status."""
        with self._lock:
            if self._active_key is None or self._active_engine is None:
                return ActiveScenarioResponse(active=False)

            meta = SCENARIO_METADATA[self._active_key]
            fault_infos: list[FaultInfo] = []
            for f in self._active_engine.faults:
                affected = self._active_engine.get_active_affected_nodes(f.start_time).get(f.target_id, [f.target_id])
                # or use engine ground truth
                gt = self._active_engine.get_ground_truth()
                affected_ids = list(gt[0].affected_node_ids) if gt else [f.target_id]

                fault_infos.append(
                    FaultInfo(
                        fault_id=f.fault_id,
                        fault_type=f.fault_type.value,
                        target_id=f.target_id,
                        severity=f.severity,
                        start_time=f.start_time,
                        end_time=f.end_time,
                        affected_nodes=affected_ids,
                        description=f.description,
                    )
                )

            return ActiveScenarioResponse(
                active=True,
                scenario_id=meta["scenario_id"],
                scenario_key=self._active_key,
                name=meta["name"],
                description=meta["description"],
                faults=fault_infos,
                activated_at=self._activated_at,
            )

    def apply_faults(
        self,
        base_snapshots: Iterable[KPISnapshot],
        timestamp: datetime,
    ) -> list[KPISnapshot]:
        """Apply active fault scenario transformation to generated base telemetry snapshots."""
        with self._lock:
            if self._active_engine is None:
                return list(base_snapshots)
            return self._active_engine.apply_faults(base_snapshots, timestamp=timestamp)


_default_fault_service: Optional[FaultService] = None
_fault_lock = threading.Lock()


def get_fault_service() -> FaultService:
    """Retrieve or initialize global FaultService singleton."""
    global _default_fault_service
    with _fault_lock:
        if _default_fault_service is None:
            _default_fault_service = FaultService()
        return _default_fault_service


def set_fault_service(service: FaultService) -> None:
    """Override global FaultService instance (useful for tests)."""
    global _default_fault_service
    with _fault_lock:
        _default_fault_service = service
