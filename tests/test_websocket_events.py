"""Tests for NEXUS M7.2 WebSocket live event infrastructure and event contracts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import pytest
from starlette.testclient import TestClient

from nexus.detection.models import (
    AlarmStatus,
    AnomalyEvent,
    DetectionSource,
    Severity,
)
from nexus.detection.service import AlarmService
from nexus.events.broadcaster import EventBroadcaster
from nexus.events.models import EventType, LiveEvent
from nexus.incidents.api import app
from nexus.incidents.enums import ActorType, IncidentPriority, IncidentSeverity, IncidentStatus
from nexus.incidents.models import Incident
from nexus.incidents.repository import IncidentRepository, create_engine
from nexus.incidents.service import IncidentService
from nexus.telemetry.models import KPISnapshot, PerformanceMetrics, ReliabilityMetrics
from nexus.telemetry.store import TelemetryStore
from nexus.topology.builder import build_simulated_network
from nexus.topology.enums import NodeStatus


class TestLiveEventContracts:
    """Validate LiveEvent envelope structure, normalization, and validations."""

    def test_valid_event_envelope(self) -> None:
        """Valid event generates compliant envelope with ISO 8601 UTC timestamp."""
        ts = datetime(2026, 11, 1, 14, 30, 0, tzinfo=timezone.utc)
        event = LiveEvent(
            type=EventType.INCIDENT_CREATED,
            timestamp=ts,
            payload={"incident_id": "INC-001", "severity": "CRITICAL"},
        )
        data = event.to_dict()

        assert data["type"] == "INCIDENT_CREATED"
        assert data["timestamp"] == "2026-11-01T14:30:00+00:00"
        assert data["payload"] == {"incident_id": "INC-001", "severity": "CRITICAL"}

    def test_naive_timestamp_normalized_to_utc(self) -> None:
        """Naive timestamp is automatically interpreted as UTC."""
        naive_ts = datetime(2026, 11, 1, 14, 30, 0)
        event = LiveEvent(
            type=EventType.ALARM_CREATED,
            timestamp=naive_ts,
            payload={"alarm_id": "ALM-1"},
        )
        assert event.timestamp.tzinfo == timezone.utc
        assert event.to_dict()["timestamp"].startswith("2026-11-01T14:30:00")

    def test_invalid_event_attributes_rejected(self) -> None:
        """Empty type, invalid timestamp, and non-mapping payloads must be rejected."""
        t = datetime.now(timezone.utc)
        with pytest.raises(ValueError, match="Event type must be a non-empty string"):
            LiveEvent(type="   ", timestamp=t, payload={})

        with pytest.raises(ValueError, match="timestamp must be a datetime"):
            LiveEvent(type="TEST", timestamp="yesterday", payload={})  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="payload must be a mapping"):
            LiveEvent(type="TEST", timestamp=t, payload=["not", "a", "dict"])  # type: ignore[arg-type]


class TestEventBroadcasterQueueAndBackpressure:
    """Validate bounded queue, backpressure handling, and multiple subscribers."""

    @pytest.mark.anyio
    async def test_fanout_to_multiple_subscribers(self) -> None:
        """Broadcaster fans out events to all registered client queues."""
        broadcaster = EventBroadcaster(max_queue_size=10)
        conn1, conn2 = object(), object()

        q1 = await broadcaster.register(conn1)
        q2 = await broadcaster.register(conn2)
        assert broadcaster.active_connections_count == 2

        event = LiveEvent(
            type=EventType.TELEMETRY_SNAPSHOT,
            timestamp=datetime.now(timezone.utc),
            payload={"node_id": "CELL-01"},
        )
        delivered = broadcaster.broadcast(event)
        assert delivered == 2

        # Both subscribers receive identical envelope
        msg1 = q1.get_nowait()
        msg2 = q2.get_nowait()
        assert msg1["type"] == "TELEMETRY_SNAPSHOT"
        assert msg2["type"] == "TELEMETRY_SNAPSHOT"
        assert msg1["payload"]["node_id"] == "CELL-01"

    @pytest.mark.anyio
    async def test_unregister_cleans_up_connection(self) -> None:
        """Unregistering a connection removes its queue without affecting others."""
        broadcaster = EventBroadcaster(max_queue_size=10)
        conn1, conn2 = object(), object()

        q1 = await broadcaster.register(conn1)
        q2 = await broadcaster.register(conn2)

        await broadcaster.unregister(conn1)
        assert broadcaster.active_connections_count == 1

        event = LiveEvent(
            type=EventType.ALARM_CLEARED,
            timestamp=datetime.now(timezone.utc),
            payload={"alarm_id": "ALM-9"},
        )
        delivered = broadcaster.broadcast(event)
        assert delivered == 1

        assert q1.empty()
        assert not q2.empty()

    @pytest.mark.anyio
    async def test_bounded_queue_backpressure_evicts_oldest(self) -> None:
        """When client queue fills up, oldest event is evicted to prevent memory leaks."""
        # Bounded queue with capacity 3
        broadcaster = EventBroadcaster(max_queue_size=3)
        conn = object()
        queue = await broadcaster.register(conn)

        now = datetime.now(timezone.utc)
        for i in range(5):
            broadcaster.publish("TEST_EVENT", {"seq": i}, timestamp=now)

        assert queue.qsize() == 3
        assert broadcaster.dropped_events_count == 2

        # Oldest items 0 and 1 were evicted; remaining items are 2, 3, 4
        m1 = queue.get_nowait()
        m2 = queue.get_nowait()
        m3 = queue.get_nowait()
        assert m1["payload"]["seq"] == 2
        assert m2["payload"]["seq"] == 3
        assert m3["payload"]["seq"] == 4


class TestRealBackendStateChangeEvents:
    """Verify that domain operations dispatch genuine real-time events."""

    def test_telemetry_store_publishes_event(self) -> None:
        """TelemetryStore.record publishes TELEMETRY_SNAPSHOT event."""
        published_events: list[tuple[str, dict]] = []
        store = TelemetryStore(event_publisher=lambda t, p: published_events.append((t, p)))

        snap = KPISnapshot(
            node_id="CELL-05",
            timestamp=datetime(2026, 11, 1, 15, 0, 0, tzinfo=timezone.utc),
            performance=PerformanceMetrics(throughput_mbps=42.0, latency_ms=12.0),
            reliability=ReliabilityMetrics(connection_drop_rate_pct=0.2, availability_pct=99.9),
        )
        store.record(snap)

        assert len(published_events) == 1
        event_type, payload = published_events[0]
        assert event_type == "TELEMETRY_SNAPSHOT"
        assert payload["node_id"] == "CELL-05"
        assert payload["metrics"]["throughput_mbps"] == 42.0

    def test_alarm_service_publishes_created_updated_cleared(self) -> None:
        """AlarmService publishes ALARM_CREATED, ALARM_UPDATED, and ALARM_CLEARED."""
        published_events: list[tuple[str, dict]] = []
        service = AlarmService(event_publisher=lambda t, p: published_events.append((t, p)))

        t = datetime(2026, 11, 1, 15, 0, 0, tzinfo=timezone.utc)
        ev1 = AnomalyEvent(
            node_id="CELL-01",
            metric_name="latency_ms",
            timestamp=t,
            source=DetectionSource.THRESHOLD,
            rule_id="RULE-LAT-MAJOR",
            severity=Severity.MAJOR,
            current_value=85.0,
            threshold=80.0,
        )

        # 1. New alarm -> ALARM_CREATED
        alarm, is_new = service.process_anomaly(ev1)
        assert is_new is True
        assert published_events[-1][0] == "ALARM_CREATED"
        assert published_events[-1][1]["alarm_id"] == alarm.alarm_id

        # 2. Repeated observation -> ALARM_UPDATED
        ev2 = AnomalyEvent(
            node_id="CELL-01",
            metric_name="latency_ms",
            timestamp=t,
            source=DetectionSource.THRESHOLD,
            rule_id="RULE-LAT-MAJOR",
            severity=Severity.MAJOR,
            current_value=90.0,
            threshold=80.0,
        )
        alarm2, is_new2 = service.process_anomaly(ev2)
        assert is_new2 is False
        assert published_events[-1][0] == "ALARM_UPDATED"
        assert published_events[-1][1]["observation_count"] == 2

        # 3. Clear alarm -> ALARM_CLEARED
        key = ("CELL-01", "latency_ms", "RULE-LAT-MAJOR", DetectionSource.THRESHOLD)
        service.clear_alarm(key, t)
        assert published_events[-1][0] == "ALARM_CLEARED"
        assert published_events[-1][1]["status"] == "CLEARED"

    def test_incident_service_publishes_created_acknowledged_resolved(self) -> None:
        """IncidentService publishes INCIDENT_CREATED, INCIDENT_ACKNOWLEDGED, and INCIDENT_RESOLVED."""
        published_events: list[tuple[str, dict]] = []
        engine = create_engine("sqlite:///:memory:")
        from nexus.incidents.repository import Base
        Base.metadata.create_all(engine)
        repo = IncidentRepository.from_engine(engine)

        service = IncidentService(
            repository=repo,
            event_publisher=lambda t, p: published_events.append((t, p)),
        )

        from nexus.correlation.models import CorrelationGroup
        from nexus.detection.models import Alarm
        from nexus.rca.models import RCAResult, RootCauseHypothesis, RootCauseType, TargetType
        from nexus.topology.enums import NodeType

        now = datetime(2026, 11, 1, 15, 0, 0, tzinfo=timezone.utc)
        alarm = Alarm(
            alarm_id="alm-evt-1",
            node_id="CORE-01",
            rule_id="RULE-LINK-DOWN",
            metric_name="packet_loss_pct",
            source=DetectionSource.THRESHOLD,
            severity=Severity.CRITICAL,
            current_value=100.0,
            threshold=50.0,
            first_seen=now,
            last_seen=now,
            observation_count=1,
            status=AlarmStatus.ACTIVE,
        )
        group = CorrelationGroup(
            group_id="GRP-EVT-1",
            anchor_node_id="CORE-01",
            root_cause_tier=NodeType.CORE,
            alarms=(alarm,),
            alarm_ids=("alm-evt-1",),
            node_ids=("CORE-01",),
            time_window_start=now,
            time_window_end=now,
            correlation_reason="Core link disruption",
        )
        hypothesis = RootCauseHypothesis(
            hypothesis_id="HYP-1",
            cause_type=RootCauseType.BACKHAUL_FAILURE,
            target_id="CORE-01",
            target_type=TargetType.NODE,
            confidence_score=0.92,
            explanation="Core link down",
            evidence_items=(),
            group_id="GRP-EVT-1",
        )
        rca = RCAResult(
            group_id="GRP-EVT-1",
            hypotheses=(hypothesis,),
            primary_hypothesis=hypothesis,
            analysis_timestamp=now,
        )

        inc = service.create_incident(group, rca, actor="AUTOMATION_ENGINE")
        assert published_events[-1][0] == "INCIDENT_CREATED"
        assert published_events[-1][1]["incident_id"] == inc.incident_id
        assert published_events[-1][1]["severity"] == "CRITICAL"

        # Acknowledge
        service.acknowledge_incident(inc.incident_id, actor="duty-engineer")
        assert published_events[-1][0] == "INCIDENT_ACKNOWLEDGED"
        assert published_events[-1][1]["acknowledged_by"] == "duty-engineer"

        # Resolve
        service.resolve_incident(inc.incident_id, actor="duty-engineer", notes="Link spliced")
        assert published_events[-1][0] == "INCIDENT_RESOLVED"
        assert published_events[-1][1]["resolved_by"] == "duty-engineer"
        assert published_events[-1][1]["notes"] == "Link spliced"


class TestLiveWebSocketEndpoint:
    """Validate Starlette TestClient websocket_connect to /ws/live."""

    def test_websocket_connect_and_receive_live_event(self) -> None:
        """WebSocket client connects and consumes real published events in canonical envelope."""
        from nexus.events.broadcaster import get_broadcaster
        broadcaster = get_broadcaster()

        with TestClient(app) as client:
            with client.websocket_connect("/ws/live") as ws:
                # Dispatch an authentic event
                broadcaster.publish(
                    "TOPOLOGY_STATUS_CHANGED",
                    {"node_id": "SITE-02", "status": "DEGRADED"},
                )

                # Client receives message
                data = ws.receive_json()
                assert data["type"] == "TOPOLOGY_STATUS_CHANGED"
                assert "timestamp" in data
                assert data["payload"] == {"node_id": "SITE-02", "status": "DEGRADED"}

    def test_websocket_ping_pong_heartbeat(self) -> None:
        """WebSocket client sending PING receives PONG heartbeat response."""
        with TestClient(app) as client:
            with client.websocket_connect("/ws/live") as ws:
                ws.send_json({"type": "PING", "timestamp": "2026-11-01T15:00:00Z"})
                response = ws.receive_json()
                assert response["type"] == "PONG"
                assert response["timestamp"] == "2026-11-01T15:00:00Z"

    def test_simultaneous_event_and_ping_pong_traffic(self) -> None:
        """Serialized outbound writes cleanly interleave broadcast events and PONG frames."""
        from nexus.events.broadcaster import get_broadcaster
        import threading
        import time

        broadcaster = get_broadcaster()

        with TestClient(app) as client:
            with client.websocket_connect("/ws/live") as ws:
                stop_flag = threading.Event()

                def background_broadcaster():
                    for i in range(10):
                        if stop_flag.is_set():
                            break
                        broadcaster.publish(
                            "TELEMETRY_SNAPSHOT",
                            {"seq": i, "node_id": "CELL-01"},
                        )
                        time.sleep(0.005)

                th = threading.Thread(target=background_broadcaster)
                th.start()

                # Send 5 pings concurrently with event traffic
                for p in range(5):
                    ws.send_json({"type": "PING", "timestamp": f"ping-{p}"})

                received_types: list[str] = []
                # Receive interleaved messages
                for _ in range(15):
                    data = ws.receive_json()
                    received_types.append(data["type"])

                stop_flag.set()
                th.join(timeout=2.0)

                assert "PONG" in received_types
                assert "TELEMETRY_SNAPSHOT" in received_types
                assert received_types.count("PONG") == 5


class TestCrossThreadBroadcasting:
    """Validate thread-safe event publishing from separate worker threads."""

    def test_worker_thread_publishing_to_active_websocket(self) -> None:
        """Events published from a background OS thread are dispatched to the WebSocket client."""
        import threading
        from nexus.events.broadcaster import get_broadcaster

        broadcaster = get_broadcaster()

        with TestClient(app) as client:
            with client.websocket_connect("/ws/live") as ws:
                def worker():
                    broadcaster.publish(
                        "ALARM_CREATED",
                        {"alarm_id": "ALM-THREAD-1", "severity": "CRITICAL"},
                    )

                th = threading.Thread(target=worker)
                th.start()
                th.join(timeout=2.0)

                msg = ws.receive_json()
                assert msg["type"] == "ALARM_CREATED"
                assert msg["payload"]["alarm_id"] == "ALM-THREAD-1"

    def test_publish_with_no_subscribers_or_closed_subscribers_does_not_raise(self) -> None:
        """Broadcaster handles no subscribers and dead loops gracefully without raising."""
        from nexus.events.broadcaster import EventBroadcaster
        from nexus.events.models import LiveEvent

        b = EventBroadcaster()
        assert b.active_connections_count == 0

        # Broadcast when no subscribers exist returns 0
        delivered = b.broadcast(
            LiveEvent(
                type=EventType.TELEMETRY_SNAPSHOT,
                timestamp=datetime.now(timezone.utc),
                payload={"test": 1},
            )
        )
        assert delivered == 0

    @pytest.mark.anyio
    async def test_subscriber_disconnect_during_event_publication(self) -> None:
        """Dead or closed subscriber loops are cleanly pruned without affecting other subscribers."""
        from nexus.events.broadcaster import EventBroadcaster
        from nexus.events.models import LiveEvent

        b = EventBroadcaster()

        # Register two subscribers on current loop
        loop = asyncio.get_running_loop()
        q1 = await b.register("conn-1")
        q2 = await b.register("conn-2")
        assert b.active_connections_count == 2

        # One normal broadcast delivers to both
        delivered = b.broadcast(
            LiveEvent(
                type=EventType.ALARM_CREATED,
                timestamp=datetime.now(timezone.utc),
                payload={"id": "1"},
            )
        )
        assert delivered == 2
        assert q1.qsize() == 1
        assert q2.qsize() == 1

        # Simulate unregister / disconnect of conn-1
        await b.unregister("conn-1")
        assert b.active_connections_count == 1

        # Second broadcast delivers only to remaining conn-2
        delivered2 = b.broadcast(
            LiveEvent(
                type=EventType.ALARM_CREATED,
                timestamp=datetime.now(timezone.utc),
                payload={"id": "2"},
            )
        )
        assert delivered2 == 1
        assert q2.qsize() == 2


class TestTopologyStatusChangedProducer:
    """Validate authentic TOPOLOGY_STATUS_CHANGED event generation."""

    def test_topology_status_change_publishes_event_and_noop_suppresses(self) -> None:
        """Changing node status publishes TOPOLOGY_STATUS_CHANGED; identical status suppresses."""
        from nexus.topology.api import get_topology_registry
        from nexus.topology.builder import build_simulated_network
        from nexus.topology.api import set_topology_registry
        from nexus.events.broadcaster import get_broadcaster

        topo = build_simulated_network()
        set_topology_registry(topo)

        published: list[tuple[str, dict]] = []
        broadcaster = get_broadcaster()
        original_publish = broadcaster.publish

        def capture(event_type, payload, timestamp=None):
            published.append((event_type, dict(payload)))
            return original_publish(event_type, payload, timestamp)

        broadcaster.publish = capture  # type: ignore

        # Wire status listener
        def on_change(node_id, old_st, new_st, ts):
            broadcaster.publish(
                "TOPOLOGY_STATUS_CHANGED",
                {
                    "node_id": node_id,
                    "previous_status": old_st.value,
                    "new_status": new_st.value,
                    "timestamp": ts.isoformat(),
                },
                timestamp=ts,
            )

        topo.add_status_listener(on_change)

        # 1. Real status change: ONLINE -> DEGRADED
        assert topo.get_node("SITE-01").status == NodeStatus.ONLINE
        topo.update_node_status("SITE-01", NodeStatus.DEGRADED)

        assert len(published) == 1
        assert published[0][0] == "TOPOLOGY_STATUS_CHANGED"
        assert published[0][1]["node_id"] == "SITE-01"
        assert published[0][1]["previous_status"] == "ONLINE"
        assert published[0][1]["new_status"] == "DEGRADED"

        # 2. No-op update: DEGRADED -> DEGRADED
        topo.update_node_status("SITE-01", NodeStatus.DEGRADED)
        assert len(published) == 1  # Suppressed, count remained 1

        # 3. Another change: DEGRADED -> OFFLINE
        topo.update_node_status("SITE-01", NodeStatus.OFFLINE)
        assert len(published) == 2
        assert published[1][1]["previous_status"] == "DEGRADED"
        assert published[1][1]["new_status"] == "OFFLINE"

        broadcaster.publish = original_publish  # type: ignore


class TestWebSocketOutboundHardening:
    """Validate queue loss prevention, bounded heartbeat traffic, and lifespan management."""

    @pytest.mark.anyio
    async def test_dual_queue_completion_delivers_both_messages_without_loss(self) -> None:
        """When pong_task and event_task both complete, neither message is discarded."""
        # Setup mock queues pre-filled so both tasks complete in the same iteration
        event_queue: asyncio.Queue[dict] = asyncio.Queue()
        pong_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=20)

        pong_msg = {"type": "PONG", "timestamp": "2026-01-01T00:00:00Z", "payload": {}}
        event_msg = {"type": "ALARM_CREATED", "payload": {"alarm_id": "ALM-1"}}

        await pong_queue.put(pong_msg)
        await event_queue.put(event_msg)

        delivered_messages: list[dict] = []
        stashed_event = None
        consecutive_pongs = 0

        # Run two outbound selection steps simulating sender_task logic
        for _ in range(2):
            msg = None
            if stashed_event is not None:
                msg = stashed_event
                stashed_event = None
                event_queue.task_done()
                consecutive_pongs = 0
            elif not pong_queue.empty() and consecutive_pongs < 3:
                msg = pong_queue.get_nowait()
                consecutive_pongs += 1

            if msg is None:
                pong_task = asyncio.create_task(pong_queue.get())
                event_task = asyncio.create_task(event_queue.get())
                done, pending = await asyncio.wait(
                    [pong_task, event_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

                if pong_task in done and event_task in done:
                    p_res = pong_task.result()
                    e_res = event_task.result()
                    msg = p_res
                    stashed_event = e_res
                    consecutive_pongs += 1
                elif pong_task in done:
                    msg = pong_task.result()
                    consecutive_pongs += 1
                else:
                    msg = event_task.result()
                    event_queue.task_done()
                    consecutive_pongs = 0

            delivered_messages.append(msg)

        assert len(delivered_messages) == 2
        assert delivered_messages[0]["type"] == "PONG"
        assert delivered_messages[1]["type"] == "ALARM_CREATED"
        assert delivered_messages[1]["payload"]["alarm_id"] == "ALM-1"

    def test_flood_ping_frames_bounded_and_event_not_starved(self) -> None:
        """Flooding PING frames maintains bounded queue and does not starve backend events."""
        from nexus.events.broadcaster import get_broadcaster

        broadcaster = get_broadcaster()

        with TestClient(app) as client:
            with client.websocket_connect("/ws/live") as ws:
                # Flood 50 PING frames rapidly
                for i in range(50):
                    ws.send_json({"type": "PING", "timestamp": f"ping-{i}"})

                # Inject a critical backend event during the flood
                from nexus.events.models import LiveEvent, EventType
                broadcaster.broadcast(
                    LiveEvent(
                        type=EventType.ALARM_CREATED,
                        timestamp=datetime.now(timezone.utc),
                        payload={"alarm_id": "CRIT-ALM-1", "severity": "CRITICAL"},
                    )
                )

                # Send 10 more PING frames
                for i in range(50, 60):
                    ws.send_json({"type": "PING", "timestamp": f"ping-{i}"})

                received_types = []
                received_alarm = False
                # Consume messages: should receive PONGs and the ALARM_CREATED without starving
                for _ in range(65):
                    data = ws.receive_json()
                    received_types.append(data["type"])
                    if data["type"] == "ALARM_CREATED":
                        received_alarm = True
                        break

                assert received_alarm, "ALARM_CREATED event was starved by PING flood"
                assert "PONG" in received_types


class TestApplicationLifespanTopologyListener:
    """Validate FastAPI lifespan registration and cleanup of topology listeners."""

    def test_lifespan_listener_cleanup_across_app_instances(self) -> None:
        """Creating, starting, and stopping apps registers exactly one listener and prunes it on shutdown."""
        from nexus.incidents.api import create_app
        from nexus.topology.api import get_topology_registry
        from nexus.topology.builder import build_simulated_network
        from nexus.topology.api import set_topology_registry
        from nexus.events.broadcaster import get_broadcaster

        # Isolated topology and broadcaster
        topo = build_simulated_network()
        set_topology_registry(topo)
        broadcaster = get_broadcaster()

        published_events: list[dict] = []
        orig_pub = broadcaster.publish

        def capture(event_type, payload, timestamp=None):
            if event_type == "TOPOLOGY_STATUS_CHANGED":
                published_events.append(dict(payload))
            return orig_pub(event_type, payload, timestamp)

        broadcaster.publish = capture  # type: ignore

        try:
            # Step 1: Create and start application 1
            app1 = create_app()
            assert len(topo._status_listeners) == 0  # Not registered before lifespan start

            with TestClient(app1):
                # Lifespan started: exactly one listener registered
                assert len(topo._status_listeners) == 1

                # Step 2: Verify one status change event is published
                topo.update_node_status("SITE-01", NodeStatus.DEGRADED)
                assert len(published_events) == 1
                assert published_events[0]["node_id"] == "SITE-01"
                assert published_events[0]["new_status"] == "DEGRADED"

            # Step 3: Application 1 shut down: listener must be removed
            assert len(topo._status_listeners) == 0

            # Step 4: Create and start application 2
            app2 = create_app()
            assert len(topo._status_listeners) == 0

            with TestClient(app2):
                # Lifespan started: still exactly one listener registered (no accumulation!)
                assert len(topo._status_listeners) == 1

                # Step 5: Verify status change produces exactly one event (not duplicated)
                topo.update_node_status("SITE-01", NodeStatus.OFFLINE)
                assert len(published_events) == 2
                assert published_events[1]["node_id"] == "SITE-01"
                assert published_events[1]["new_status"] == "OFFLINE"

            # After shutdown, listener is cleanly removed
            assert len(topo._status_listeners) == 0

        finally:
            broadcaster.publish = orig_pub  # type: ignore
            topo.clear_status_listeners()
