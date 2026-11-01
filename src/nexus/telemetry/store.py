"""In-memory telemetry store for real KPISnapshot retention and querying."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import threading
from typing import Callable, Optional, Sequence

from nexus.telemetry.models import KPISnapshot
from nexus.topology.enums import NodeType
from nexus.topology.topology import Topology

EventPublisher = Callable[[str, dict], None]


class TelemetryStore:
    """Thread-safe, bounded in-memory chronological store for genuine KPISnapshot records.

    Retention Limitation Notice:
        In Milestone 7.2, telemetry snapshots are retained in a thread-safe,
        bounded in-memory ring buffer (default capacity: 10,000 snapshots).
        Snapshots are not persisted to SQL database storage; older snapshots
        are safely evicted in FIFO order when buffer capacity is reached.
        Restarting the backend application process clears in-memory snapshots.
    """

    def __init__(
        self,
        max_capacity: int = 10000,
        event_publisher: Optional[EventPublisher] = None,
        topology: Optional[Topology] = None,
    ) -> None:
        self._max_capacity = max_capacity
        self._buffer: deque[KPISnapshot] = deque(maxlen=max_capacity)
        self._seen_keys: set[tuple[str, datetime]] = set()
        self._event_publisher = event_publisher
        self._topology = topology
        self._lock = threading.RLock()

    @property
    def capacity(self) -> int:
        with self._lock:
            return self._max_capacity

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._buffer)

    def set_event_publisher(self, publisher: Optional[EventPublisher]) -> None:
        with self._lock:
            self._event_publisher = publisher

    def set_topology(self, topology: Optional[Topology]) -> None:
        with self._lock:
            self._topology = topology

    def record(self, snapshot: KPISnapshot) -> bool:
        """Record an authentic telemetry snapshot into the buffer with deduplication.

        Returns:
            True if recorded, False if already present (duplicate).
        """
        if not isinstance(snapshot, KPISnapshot):
            raise TypeError(f"Expected KPISnapshot, got {type(snapshot).__name__}")

        key = (snapshot.node_id, snapshot.timestamp)
        publisher = None

        with self._lock:
            if key in self._seen_keys:
                return False

            if len(self._buffer) >= self._max_capacity:
                oldest = self._buffer[0]
                self._seen_keys.discard((oldest.node_id, oldest.timestamp))

            self._buffer.append(snapshot)
            self._seen_keys.add(key)
            publisher = self._event_publisher

        # Crucial: publish event OUTSIDE the lock to avoid deadlocks
        if publisher:
            try:
                publisher(
                    "TELEMETRY_SNAPSHOT",
                    {
                        "node_id": snapshot.node_id,
                        "timestamp": snapshot.timestamp.isoformat(),
                        "metrics": snapshot.to_metric_dict(),
                    },
                )
            except Exception:
                pass

        return True

    def record_batch(self, snapshots: Sequence[KPISnapshot]) -> int:
        """Record a sequence of authentic telemetry snapshots with deduplication.

        Returns:
            Count of newly recorded snapshots.
        """
        to_publish: list[KPISnapshot] = []
        publisher = None

        with self._lock:
            for s in snapshots:
                if not isinstance(s, KPISnapshot):
                    raise TypeError(f"Expected KPISnapshot, got {type(s).__name__}")
                key = (s.node_id, s.timestamp)
                if key in self._seen_keys:
                    continue

                if len(self._buffer) >= self._max_capacity:
                    oldest = self._buffer[0]
                    self._seen_keys.discard((oldest.node_id, oldest.timestamp))

                self._buffer.append(s)
                self._seen_keys.add(key)
                to_publish.append(s)
            publisher = self._event_publisher

        # Crucial: publish events OUTSIDE the lock to avoid deadlocks
        if publisher and to_publish:
            for s in to_publish:
                try:
                    publisher(
                        "TELEMETRY_SNAPSHOT",
                        {
                            "node_id": s.node_id,
                            "timestamp": s.timestamp.isoformat(),
                            "metrics": s.to_metric_dict(),
                        },
                    )
                except Exception:
                    pass

        return len(to_publish)

    def query(
        self,
        node_id: Optional[str] = None,
        node_type: Optional[NodeType] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[KPISnapshot], int]:
        """Query snapshots with deterministic ordering and filtering over a consistent snapshot.

        Args:
            node_id: Optional node ID exact match.
            node_type: Optional NodeType filter (resolved using topology if available).
            start_time: Optional inclusive start time (normalized to UTC).
            end_time: Optional inclusive end time (normalized to UTC).
            limit: Maximum snapshots to return (pagination size).
            offset: Number of items to skip.

        Returns:
            Tuple of (paginated list of KPISnapshot, total matching count).
        """
        norm_start = (
            start_time.replace(tzinfo=timezone.utc)
            if start_time and start_time.tzinfo is None
            else start_time.astimezone(timezone.utc)
            if start_time
            else None
        )
        norm_end = (
            end_time.replace(tzinfo=timezone.utc)
            if end_time and end_time.tzinfo is None
            else end_time.astimezone(timezone.utc)
            if end_time
            else None
        )

        # Obtain consistent snapshot of buffer and topology reference under lock
        with self._lock:
            buffer_snapshot = list(self._buffer)
            topo = self._topology

        filtered: list[KPISnapshot] = []
        for s in buffer_snapshot:
            if node_id and s.node_id != node_id:
                continue
            if norm_start and s.timestamp < norm_start:
                continue
            if norm_end and s.timestamp > norm_end:
                continue
            if node_type is not None:
                if topo and topo.has_node(s.node_id):
                    if topo.get_node(s.node_id).node_type != node_type:
                        continue
                else:
                    # In absence of topology instance, infer from standard naming prefix
                    if s.node_id.startswith("CORE") and node_type != NodeType.CORE:
                        continue
                    elif s.node_id.startswith("AGG") and node_type != NodeType.AGGREGATION:
                        continue
                    elif s.node_id.startswith("SITE") and node_type != NodeType.SITE:
                        continue
                    elif s.node_id.startswith("CELL") and node_type != NodeType.CELL:
                        continue
            filtered.append(s)

        # Deterministic ordering: timestamp descending (newest first), then node_id ascending
        filtered.sort(key=lambda s: (-s.timestamp.timestamp(), s.node_id))

        total = len(filtered)
        paginated = filtered[offset : offset + limit]
        return paginated, total

    def clear(self) -> None:
        """Clear all stored snapshots (for test cleanup)."""
        with self._lock:
            self._buffer.clear()
            self._seen_keys.clear()


_default_telemetry_store: Optional[TelemetryStore] = None
_store_lock = threading.Lock()


def get_telemetry_store() -> TelemetryStore:
    """Retrieve or initialize global TelemetryStore singleton."""
    global _default_telemetry_store
    with _store_lock:
        if _default_telemetry_store is None:
            _default_telemetry_store = TelemetryStore()
        return _default_telemetry_store


def set_telemetry_store(store: TelemetryStore) -> None:
    """Override global TelemetryStore instance (useful for tests)."""
    global _default_telemetry_store
    with _store_lock:
        _default_telemetry_store = store
