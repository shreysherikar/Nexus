"""Topology domain enumerations."""

from enum import Enum


class NodeType(str, Enum):
    """Network hierarchy node types."""

    CORE = "CORE"
    AGGREGATION = "AGGREGATION"
    SITE = "SITE"
    CELL = "CELL"

    def __str__(self) -> str:
        return self.value


class NodeStatus(str, Enum):
    """Operational status values for network nodes."""

    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"
    MAINTENANCE = "MAINTENANCE"

    def __str__(self) -> str:
        return self.value
