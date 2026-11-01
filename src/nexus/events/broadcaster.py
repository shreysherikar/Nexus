"""Real-time event broadcasting and WebSocket connection management across threads."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
from typing import Any, Mapping, Optional

from nexus.events.models import LiveEvent

logger = logging.getLogger("nexus.events")


@dataclass
class _Subscriber:
    """Internal record associating a connection with its dedicated queue and event loop."""

    connection: Any
    queue: asyncio.Queue[dict[str, Any]]
    loop: asyncio.AbstractEventLoop


class EventBroadcaster:
    """Manages active live WebSocket subscribers, backpressure queues, and fan-out dispatch.

    Thread Safety Guarantees:
    - Safe cross-thread broadcasting: events published from synchronous worker threads
      (such as IncidentService or background tasks) are dispatched onto each subscriber's
      captured asyncio event loop via loop.call_soon_threadsafe.
    - asyncio.Queue operations (get_nowait, put_nowait) are strictly executed inside the
      event loop owning the queue.
    - If a slow client's queue reaches max_queue_size, the oldest event is evicted (FIFO
      backpressure), ensuring bounded memory without blocking publisher threads.
    - Subscriber isolation: disconnects or exceptions on one subscriber do not affect others.
    """

    def __init__(self, max_queue_size: int = 100) -> None:
        self._max_queue_size = max_queue_size
        self._lock = threading.Lock()
        self._subscribers: dict[Any, _Subscriber] = {}
        self._dropped_events_count: int = 0

    @property
    def max_queue_size(self) -> int:
        return self._max_queue_size

    @property
    def active_connections_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    @property
    def dropped_events_count(self) -> int:
        with self._lock:
            return self._dropped_events_count

    async def register(self, connection: Any) -> asyncio.Queue[dict[str, Any]]:
        """Register a new active WebSocket connection with a dedicated bounded queue.

        Must be called from an async context so that the current running event loop is captured.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue_size)
        subscriber = _Subscriber(connection=connection, queue=queue, loop=loop)

        with self._lock:
            self._subscribers[connection] = subscriber
            logger.debug(
                "Registered WebSocket connection on loop %s. Total active: %d",
                id(loop),
                len(self._subscribers),
            )
        return queue

    async def unregister(self, connection: Any) -> None:
        """Unregister a disconnected WebSocket and discard its queue."""
        with self._lock:
            if connection in self._subscribers:
                del self._subscribers[connection]
                logger.debug(
                    "Unregistered WebSocket connection. Remaining active: %d",
                    len(self._subscribers),
                )

    def _enqueue_on_loop(
        self, queue: asyncio.Queue[dict[str, Any]], msg: dict[str, Any]
    ) -> None:
        """Enqueue message onto queue with FIFO backpressure.

        MUST be executed on the event loop that owns the queue.
        """
        if queue.full():
            try:
                queue.get_nowait()
                with self._lock:
                    self._dropped_events_count += 1
                logger.warning(
                    "Subscriber queue full (%d). Evicted oldest event to preserve real-time continuity.",
                    self._max_queue_size,
                )
            except asyncio.QueueEmpty:
                pass

        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            with self._lock:
                self._dropped_events_count += 1

    def broadcast(self, event: LiveEvent) -> int:
        """Fan-out an authentic LiveEvent to all active subscribers across threads.

        Thread-safe:
        - If executed from the subscriber's loop thread, enqueues directly.
        - If executed from a synchronous worker thread, dispatches to loop.call_soon_threadsafe.
        - If subscriber's event loop is closed, removes the dead connection gracefully.

        Returns:
            Count of active subscribers to which the event was dispatched.
        """
        msg = event.to_dict()

        with self._lock:
            subscribers = list(self._subscribers.values())

        if not subscribers:
            return 0

        delivered = 0
        dead_connections: list[Any] = []

        try:
            current_loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        for sub in subscribers:
            if sub.loop.is_closed():
                dead_connections.append(sub.connection)
                continue

            if current_loop is sub.loop:
                try:
                    self._enqueue_on_loop(sub.queue, msg)
                    delivered += 1
                except Exception as exc:
                    logger.debug("Failed direct enqueue to subscriber: %s", exc)
            else:
                try:
                    sub.loop.call_soon_threadsafe(self._enqueue_on_loop, sub.queue, msg)
                    delivered += 1
                except RuntimeError:
                    # Loop closed during scheduling
                    dead_connections.append(sub.connection)
                except Exception as exc:
                    logger.debug("Failed cross-thread dispatch to subscriber: %s", exc)

        if dead_connections:
            with self._lock:
                for conn in dead_connections:
                    self._subscribers.pop(conn, None)

        return delivered

    def publish(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        timestamp: Optional[datetime] = None,
    ) -> LiveEvent:
        """Helper to create and broadcast an event."""
        ts = timestamp if timestamp is not None else datetime.now(timezone.utc)
        event = LiveEvent(type=event_type, timestamp=ts, payload=payload)
        self.broadcast(event)
        return event

    def clear(self) -> None:
        """Clear all subscriber connections (for testing)."""
        with self._lock:
            self._subscribers.clear()
            self._dropped_events_count = 0


_default_broadcaster: Optional[EventBroadcaster] = None
_broadcaster_lock = threading.Lock()


def get_broadcaster() -> EventBroadcaster:
    """Retrieve or initialize global EventBroadcaster singleton."""
    global _default_broadcaster
    with _broadcaster_lock:
        if _default_broadcaster is None:
            _default_broadcaster = EventBroadcaster()
        return _default_broadcaster


def set_broadcaster(broadcaster: EventBroadcaster) -> None:
    """Override global EventBroadcaster instance (useful for tests)."""
    global _default_broadcaster
    with _broadcaster_lock:
        _default_broadcaster = broadcaster
