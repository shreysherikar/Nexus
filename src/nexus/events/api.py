"""WebSocket route handler for real-time live event streaming with serialized outbound writes."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from nexus.events.broadcaster import EventBroadcaster, get_broadcaster

logger = logging.getLogger("nexus.events.api")

router = APIRouter(tags=["events"])

PONG_QUEUE_MAXSIZE = 20
MAX_CONSECUTIVE_PONGS = 3


@router.websocket("/ws/live")
async def live_events_websocket(
    websocket: WebSocket,
    broadcaster: EventBroadcaster = Depends(get_broadcaster),
) -> None:
    """Real-time live WebSocket endpoint delivering authentic backend event streams.

    Outbound Serialization:
        All outbound frames (both event messages and heartbeat PONG responses)
        are routed strictly through a single outbound sending task (sender_task).
        The receiver_task only reads from the socket and enqueues PONG responses,
        preventing concurrent calls to websocket.send_text().

    Envelope Contract:
        {
            "type": "<EVENT_TYPE>",
            "timestamp": "2026-11-01T04:00:00Z",
            "payload": { ... }
        }
    """
    await websocket.accept()
    event_queue = await broadcaster.register(websocket)
    pong_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=PONG_QUEUE_MAXSIZE)

    async def sender_task() -> None:
        """Single outbound writer serializing all frames to the WebSocket connection.

        Invariants:
        - Never discards completed queue-get results: retained in stashed_event.
        - Heartbeat PONG priority preserved without starving broadcast events
          (at most MAX_CONSECUTIVE_PONGS sent before yielding to waiting events).
        - Single outbound writer.
        - All cancelled pending tasks are explicitly awaited.
        """
        stashed_event: Optional[dict[str, Any]] = None
        consecutive_pongs: int = 0

        try:
            while True:
                msg: Optional[dict[str, Any]] = None

                # 1. Check if we already have a stashed event from a previous dual-completion
                if stashed_event is not None:
                    if consecutive_pongs >= MAX_CONSECUTIVE_PONGS or pong_queue.empty():
                        msg = stashed_event
                        stashed_event = None
                        event_queue.task_done()
                        consecutive_pongs = 0
                    else:
                        msg = pong_queue.get_nowait()
                        consecutive_pongs += 1

                # 2. Check for immediately available messages without waiting
                elif not pong_queue.empty() and consecutive_pongs < MAX_CONSECUTIVE_PONGS:
                    msg = pong_queue.get_nowait()
                    consecutive_pongs += 1

                elif consecutive_pongs >= MAX_CONSECUTIVE_PONGS:
                    if not event_queue.empty():
                        msg = event_queue.get_nowait()
                        event_queue.task_done()
                        consecutive_pongs = 0
                    else:
                        # event_queue empty, reset counter to allow PONG dispatch
                        consecutive_pongs = 0
                        if not pong_queue.empty():
                            msg = pong_queue.get_nowait()
                            consecutive_pongs += 1

                # 3. Both queues empty; concurrently await either pong or event
                if msg is None:
                    pong_task = asyncio.create_task(pong_queue.get())
                    event_task = asyncio.create_task(event_queue.get())

                    try:
                        done, pending = await asyncio.wait(
                            [pong_task, event_task],
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                    except asyncio.CancelledError:
                        for t in (pong_task, event_task):
                            if not t.done():
                                t.cancel()
                        await asyncio.gather(pong_task, event_task, return_exceptions=True)
                        raise

                    for t in pending:
                        t.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)

                    if pong_task in done and event_task in done:
                        # BOTH completed: retrieve both results so neither is ever lost!
                        pong_res = pong_task.result()
                        event_res = event_task.result()

                        if consecutive_pongs >= MAX_CONSECUTIVE_PONGS:
                            # Event has priority
                            msg = event_res
                            event_queue.task_done()
                            consecutive_pongs = 0
                            # Put pong back or handle: pong_queue is dedicated so put_nowait
                            try:
                                pong_queue.put_nowait(pong_res)
                            except asyncio.QueueFull:
                                pass
                        else:
                            msg = pong_res
                            consecutive_pongs += 1
                            # Retain unselected event result for next send iteration
                            stashed_event = event_res
                    elif pong_task in done:
                        msg = pong_task.result()
                        consecutive_pongs += 1
                    else:
                        msg = event_task.result()
                        event_queue.task_done()
                        consecutive_pongs = 0

                await websocket.send_text(json.dumps(msg))

        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            logger.debug("Sender task outbound exception: %s", exc)
        finally:
            if stashed_event is not None:
                try:
                    event_queue.task_done()
                except ValueError:
                    pass
                stashed_event = None

    async def receiver_task() -> None:
        """Inbound reader routing control frames through the bounded outbound queue.

        Bounded Heartbeat Traffic Policy:
            pong_queue is bounded to PONG_QUEUE_MAXSIZE. When full (due to a PING flood
            exceeding transmission speed), the oldest pending PONG is evicted (FIFO),
            strictly bounding memory while ensuring fresh timestamps are returned.
        """
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    payload = json.loads(data)
                    if isinstance(payload, dict) and payload.get("type") == "PING":
                        if pong_queue.full():
                            try:
                                pong_queue.get_nowait()
                                logger.warning(
                                    "Heartbeat pong_queue full (%d). Evicted oldest PONG to bound memory.",
                                    PONG_QUEUE_MAXSIZE,
                                )
                            except asyncio.QueueEmpty:
                                pass

                        try:
                            pong_queue.put_nowait({
                                "type": "PONG",
                                "timestamp": payload.get("timestamp"),
                                "payload": {},
                            })
                        except asyncio.QueueFull:
                            pass
                except Exception:
                    pass
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            logger.debug("Receiver task inbound exception: %s", exc)

    sender = asyncio.create_task(sender_task())
    receiver = asyncio.create_task(receiver_task())

    try:
        # Wait until either the receiver (disconnect) or sender completes/fails
        done, pending = await asyncio.wait(
            [sender, receiver],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    except Exception as exc:
        logger.debug("WebSocket connection closed: %s", exc)
    finally:
        for task in [sender, receiver]:
            if not task.done():
                task.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)
        await broadcaster.unregister(websocket)
