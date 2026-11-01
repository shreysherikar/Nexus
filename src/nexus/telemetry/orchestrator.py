"""Telemetry pipeline orchestration connecting telemetry generation to storage."""

from __future__ import annotations

from datetime import datetime
import threading
from typing import Optional, Sequence

from nexus.telemetry.generator import SyntheticTelemetryGenerator
from nexus.telemetry.models import KPISnapshot
from nexus.telemetry.store import TelemetryStore, get_telemetry_store
from nexus.topology.api import get_topology_registry


class TelemetryPipeline:
    """Explicit application-level orchestration interface connecting generator to store.

    Guarantees:
    - Feeds genuine KPISnapshot instances produced by SyntheticTelemetryGenerator directly into TelemetryStore.
    - Zero background loops or infinite telemetry threads created at import time.
    - Idempotent: invoking generate_step with the same timestamp does not create duplicate snapshots in store.
    - Can ingest externally generated snapshots (e.g. from scenario replay or fault evaluation).
    """

    def __init__(
        self,
        generator: SyntheticTelemetryGenerator,
        store: TelemetryStore,
    ) -> None:
        self._generator = generator
        self._store = store

    @property
    def generator(self) -> SyntheticTelemetryGenerator:
        return self._generator

    @property
    def store(self) -> TelemetryStore:
        return self._store

    def generate_step(self, timestamp: Optional[datetime] = None) -> list[KPISnapshot]:
        """Generate a complete step for all topology nodes and record snapshots into store.

        Args:
            timestamp: Optional explicit UTC timestamp for deterministic snapshot generation.

        Returns:
            List of generated KPISnapshot instances.
        """
        snapshots = self._generator.generate_step(timestamp=timestamp)
        self._store.record_batch(snapshots)
        return snapshots

    def generate_node_snapshot(
        self, node_id: str, timestamp: Optional[datetime] = None
    ) -> KPISnapshot:
        """Generate a single node snapshot and record it into store.

        Args:
            node_id: Target topology node ID.
            timestamp: Optional explicit UTC timestamp.

        Returns:
            The generated KPISnapshot.
        """
        snapshot = self._generator.generate_node_snapshot(node_id, timestamp=timestamp)
        self._store.record(snapshot)
        return snapshot

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
            topo = get_topology_registry()
            store = get_telemetry_store()
            gen = SyntheticTelemetryGenerator(topology=topo)
            _default_pipeline = TelemetryPipeline(generator=gen, store=store)
        return _default_pipeline


def set_telemetry_pipeline(pipeline: TelemetryPipeline) -> None:
    """Override global TelemetryPipeline instance (useful for tests)."""
    global _default_pipeline
    with _pipeline_lock:
        _default_pipeline = pipeline
