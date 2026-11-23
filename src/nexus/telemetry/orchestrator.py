"""Telemetry pipeline orchestration connecting telemetry generation to storage and detection."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

from nexus.telemetry.generator import SyntheticTelemetryGenerator
from nexus.telemetry.models import KPISnapshot
from nexus.telemetry.store import TelemetryStore, get_telemetry_store
from nexus.topology.api import get_topology_registry


class TelemetryPipeline:
    """Explicit application-level orchestration interface connecting generator to store.

    Guarantees:
    - Feeds genuine KPISnapshot instances produced by SyntheticTelemetryGenerator directly into TelemetryStore.
    - Applies active fault scenario transformations BEFORE detection and storage (ground-truth isolation).
    - Feeds effective snapshots downstream into AnomalyDetectionEngine and AlarmService.
    - Zero background loops or infinite telemetry threads created at import time.
    - Idempotent: invoking generate_step with the same timestamp does not create duplicate snapshots in store.
    - Can ingest externally generated snapshots (e.g. from scenario replay or fault evaluation).
    """

    def __init__(
        self,
        generator: SyntheticTelemetryGenerator,
        store: TelemetryStore,
        fault_service: Optional[Any] = None,
        alarm_service: Optional[Any] = None,
        correlation_engine: Optional[Any] = None,
        rca_engine: Optional[Any] = None,
        incident_service: Optional[Any] = None,
    ) -> None:
        self._generator = generator
        self._store = store
        self._fault_service = fault_service
        self._alarm_service = alarm_service
        self._correlation_engine = correlation_engine
        self._rca_engine = rca_engine
        self._incident_service = incident_service

    @property
    def generator(self) -> SyntheticTelemetryGenerator:
        return self._generator

    @property
    def store(self) -> TelemetryStore:
        return self._store

    @property
    def fault_service(self) -> Optional[Any]:
        return self._fault_service

    def set_fault_service(self, fault_service: Optional[Any]) -> None:
        self._fault_service = fault_service

    @property
    def alarm_service(self) -> Optional[Any]:
        return self._alarm_service

    def set_alarm_service(self, alarm_service: Optional[Any]) -> None:
        self._alarm_service = alarm_service

    @property
    def correlation_engine(self) -> Optional[Any]:
        return self._correlation_engine

    def set_correlation_engine(self, correlation_engine: Optional[Any]) -> None:
        self._correlation_engine = correlation_engine

    @property
    def rca_engine(self) -> Optional[Any]:
        return self._rca_engine

    def set_rca_engine(self, rca_engine: Optional[Any]) -> None:
        self._rca_engine = rca_engine

    @property
    def incident_service(self) -> Optional[Any]:
        if self._incident_service is None:
            try:
                from nexus.incidents.api import get_incident_service
                return get_incident_service()
            except Exception:
                return None
        return self._incident_service

    def set_incident_service(self, incident_service: Optional[Any]) -> None:
        self._incident_service = incident_service

    def generate_step(self, timestamp: Optional[datetime] = None) -> list[KPISnapshot]:
        """Generate a complete step for all topology nodes, apply active faults, record to store,
        and process downstream detection.

        Args:
            timestamp: Optional explicit UTC timestamp for deterministic snapshot generation.

        Returns:
            List of generated effective KPISnapshot instances.
        """
        base_snapshots = self._generator.generate_step(timestamp=timestamp)
        effective_ts = (
            base_snapshots[0].timestamp
            if base_snapshots
            else (timestamp or datetime.now(timezone.utc))
        )

        # 1. Transform base snapshots with active fault scenario (ground truth isolated in fault service)
        if self._fault_service is not None:
            effective_snapshots = self._fault_service.apply_faults(base_snapshots, timestamp=effective_ts)
        else:
            effective_snapshots = base_snapshots

        # 2. Record effective snapshots into store (publishes TELEMETRY_SNAPSHOT events)
        self._store.record_batch(effective_snapshots)

        # 3. Downstream detection processing
        if self._alarm_service is not None:
            topo = getattr(self._generator, "_topology", None)
            node_types = {n.node_id: n.node_type for n in topo.all_nodes()} if topo else None
            self._alarm_service.process_snapshots(effective_snapshots, node_types=node_types)

            # 4. Correlation, RCA, and Incident lifecycle
            if self._correlation_engine is not None and topo is not None:
                active_alarms = self._alarm_service.manager.get_active_alarms()
                if active_alarms:
                    corr_result = self._correlation_engine.correlate(active_alarms, topology=topo)
                    for group in corr_result.groups:
                        rca_result = None
                        if self._rca_engine is not None:
                            try:
                                rca_result = self._rca_engine.analyze_group(
                                    group=group,
                                    topology=topo,
                                    transport=getattr(self, "_transport", None) or getattr(self._rca_engine, "_transport", None),
                                    telemetry_snapshots=effective_snapshots,
                                    analysis_timestamp=effective_ts,
                                )
                            except Exception:
                                pass
                        inc_svc = self.incident_service
                        if inc_svc is not None:
                            try:
                                inc_svc.create_or_update_incident(
                                    correlation_group=group,
                                    rca_result=rca_result,
                                    actor="SYSTEM",
                                    creation_timestamp=effective_ts,
                                )
                            except Exception as exc:
                                logger.exception("Failed to create or update incident: %s", exc)

        return effective_snapshots

    def generate_node_snapshot(
        self, node_id: str, timestamp: Optional[datetime] = None
    ) -> KPISnapshot:
        """Generate a single node snapshot, apply active faults, and record into store.

        Args:
            node_id: Target topology node ID.
            timestamp: Optional explicit UTC timestamp.

        Returns:
            The generated effective KPISnapshot.
        """
        base_snapshot = self._generator.generate_node_snapshot(node_id, timestamp=timestamp)
        effective_ts = base_snapshot.timestamp

        if self._fault_service is not None:
            transformed = self._fault_service.apply_faults([base_snapshot], timestamp=effective_ts)
            effective_snapshot = transformed[0] if transformed else base_snapshot
        else:
            effective_snapshot = base_snapshot

        self._store.record(effective_snapshot)

        if self._alarm_service is not None:
            topo = getattr(self._generator, "_topology", None)
            node = topo.get_node(node_id) if topo and topo.has_node(node_id) else None
            node_type = node.node_type if node else None
            self._alarm_service.process_snapshots(
                [effective_snapshot],
                node_types={node_id: node_type} if node_type else None,
            )

            # Correlation, RCA, and Incident lifecycle
            if self._correlation_engine is not None and topo is not None:
                active_alarms = self._alarm_service.manager.get_active_alarms()
                if active_alarms:
                    corr_result = self._correlation_engine.correlate(active_alarms, topology=topo)
                    for group in corr_result.groups:
                        rca_result = None
                        if self._rca_engine is not None:
                            try:
                                rca_result = self._rca_engine.analyze_group(
                                    group=group,
                                    topology=topo,
                                    transport=getattr(self, "_transport", None) or getattr(self._rca_engine, "_transport", None),
                                    telemetry_snapshots=[effective_snapshot],
                                    analysis_timestamp=effective_ts,
                                )
                            except Exception:
                                pass
                        inc_svc = self.incident_service
                        if inc_svc is not None:
                            try:
                                inc_svc.create_or_update_incident(
                                    correlation_group=group,
                                    rca_result=rca_result,
                                    actor="SYSTEM",
                                    creation_timestamp=effective_ts,
                                )
                            except Exception as exc:
                                logger.exception("Failed to create or update incident: %s", exc)

        return effective_snapshot

    def ingest_snapshots(self, snapshots: Sequence[KPISnapshot]) -> int:
        """Ingest pre-produced snapshots (e.g. from fault injection or scenario replay).

        Returns:
            Count of newly recorded snapshots.
        """
        return self._store.record_batch(snapshots)


_default_pipeline: Optional[TelemetryPipeline] = None
_pipeline_lock = threading.Lock()


def get_telemetry_pipeline() -> TelemetryPipeline:
    """Retrieve or initialize global TelemetryPipeline singleton."""
    global _default_pipeline
    with _pipeline_lock:
        if _default_pipeline is None:
            from nexus.correlation.engine import AlarmCorrelationEngine
            from nexus.detection.service import get_alarm_service
            from nexus.fault.service import get_fault_service
            from nexus.incidents.api import get_incident_service
            from nexus.rca.engine import RootCauseAnalysisEngine
            from nexus.transport.builder import build_reference_transport_network

            topo = get_topology_registry()
            store = get_telemetry_store()
            gen = SyntheticTelemetryGenerator(topology=topo)
            fault_svc = get_fault_service()
            alarm_svc = get_alarm_service()
            corr_engine = AlarmCorrelationEngine(topology=topo)
            trans = build_reference_transport_network(topo)
            rca_engine = RootCauseAnalysisEngine(topology=topo, transport=trans)
            _default_pipeline = TelemetryPipeline(
                generator=gen,
                store=store,
                fault_service=fault_svc,
                alarm_service=alarm_svc,
                correlation_engine=corr_engine,
                rca_engine=rca_engine,
                incident_service=None,
            )
            _default_pipeline._transport = trans
        return _default_pipeline


def set_telemetry_pipeline(pipeline: TelemetryPipeline) -> None:
    """Override global TelemetryPipeline instance (useful for tests)."""
    global _default_pipeline
    with _pipeline_lock:
        _default_pipeline = pipeline
