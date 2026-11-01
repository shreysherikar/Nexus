"""Domain models and enumerations for real-time live events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Mapping, Optional


class EventType(str, Enum):
    """Officially supported real-time live event classifications."""

    TELEMETRY_SNAPSHOT = "TELEMETRY_SNAPSHOT"
    ALARM_CREATED = "ALARM_CREATED"
    ALARM_UPDATED = "ALARM_UPDATED"
    ALARM_CLEARED = "ALARM_CLEARED"
    INCIDENT_CREATED = "INCIDENT_CREATED"
    INCIDENT_ACKNOWLEDGED = "INCIDENT_ACKNOWLEDGED"
    INCIDENT_RESOLVED = "INCIDENT_RESOLVED"
    TOPOLOGY_STATUS_CHANGED = "TOPOLOGY_STATUS_CHANGED"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class LiveEvent:
    """Envelope representation for real-time WebSocket events.

    Attributes:
        type: Classification name of the event.
        timestamp: Normalized UTC timestamp of the event occurrence.
        payload: Structured contextual event attributes.
    """

    type: str
    timestamp: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.type, str) or not self.type.strip():
            raise ValueError("Event type must be a non-empty string")

        if not isinstance(self.timestamp, datetime):
            raise ValueError(f"timestamp must be a datetime, got {type(self.timestamp).__name__}")

        norm_ts = (
            self.timestamp.replace(tzinfo=timezone.utc)
            if self.timestamp.tzinfo is None
            else self.timestamp.astimezone(timezone.utc)
        )
        object.__setattr__(self, "timestamp", norm_ts)

        if not isinstance(self.payload, Mapping):
            raise ValueError(f"payload must be a mapping, got {type(self.payload).__name__}")

    def to_dict(self) -> dict[str, Any]:
        """Serialize event into canonical envelope dictionary."""
        return {
            "type": self.type,
            "timestamp": self.timestamp.isoformat(),
            "payload": dict(self.payload),
        }
