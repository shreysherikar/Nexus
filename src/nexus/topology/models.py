"""Domain models for network topology nodes and hierarchy rules."""

from dataclasses import dataclass
import math
from typing import Optional

from nexus.topology.enums import NodeStatus, NodeType
from nexus.topology.exceptions import InvalidNodeStateError

# Strict hierarchy rules defining the expected parent node type for each tier.
ALLOWED_PARENT_TYPES: dict[NodeType, Optional[NodeType]] = {
    NodeType.CORE: None,
    NodeType.AGGREGATION: NodeType.CORE,
    NodeType.SITE: NodeType.AGGREGATION,
    NodeType.CELL: NodeType.SITE,
}


@dataclass(frozen=True)
class Node:
    """Represents an immutable network node entity.

    Attributes:
        node_id: Unique string identifier for the node (e.g. 'CORE-01', 'CELL-01').
        node_type: Tier in the hierarchy (CORE, AGGREGATION, SITE, CELL).
        parent_id: Optional string identifier of the parent node.
        status: Current operational status (ONLINE, OFFLINE, DEGRADED, MAINTENANCE).
        latitude: Optional physical latitude in WGS-84 degrees [-90.0, 90.0].
        longitude: Optional physical longitude in WGS-84 degrees [-180.0, 180.0].
    """

    node_id: str
    node_type: NodeType
    parent_id: Optional[str] = None
    status: NodeStatus = NodeStatus.ONLINE
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    def __post_init__(self) -> None:
        # Validate node_id
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise InvalidNodeStateError("node_id must be a non-empty string")

        # Validate and coerce node_type
        if not isinstance(self.node_type, NodeType):
            try:
                coerced_type = NodeType(self.node_type)
            except (ValueError, TypeError) as exc:
                raise InvalidNodeStateError(
                    f"Invalid node_type '{self.node_type}'. Expected one of: "
                    f"{', '.join(t.value for t in NodeType)}"
                ) from exc
            object.__setattr__(self, "node_type", coerced_type)

        # Validate and coerce status
        if not isinstance(self.status, NodeStatus):
            try:
                coerced_status = NodeStatus(self.status)
            except (ValueError, TypeError) as exc:
                raise InvalidNodeStateError(
                    f"Invalid status '{self.status}'. Expected one of: "
                    f"{', '.join(s.value for s in NodeStatus)}"
                ) from exc
            object.__setattr__(self, "status", coerced_status)

        # Validate parent_id type if provided
        if self.parent_id is not None:
            if not isinstance(self.parent_id, str) or not self.parent_id.strip():
                raise InvalidNodeStateError("parent_id must be None or a non-empty string")

        # Validate coordinates: must be both present or both absent
        if (self.latitude is None) != (self.longitude is None):
            raise InvalidNodeStateError(
                "Incomplete coordinate pair: latitude and longitude must both be present or both absent"
            )

        if self.latitude is not None and self.longitude is not None:
            # Check booleans (bool is a subclass of int in Python)
            if isinstance(self.latitude, bool) or not isinstance(self.latitude, (int, float)):
                raise InvalidNodeStateError(
                    f"latitude must be a numeric value, got {type(self.latitude).__name__}"
                )
            if isinstance(self.longitude, bool) or not isinstance(self.longitude, (int, float)):
                raise InvalidNodeStateError(
                    f"longitude must be a numeric value, got {type(self.longitude).__name__}"
                )

            lat_f = float(self.latitude)
            lon_f = float(self.longitude)

            if not math.isfinite(lat_f):
                raise InvalidNodeStateError(f"latitude must be a finite number, got {lat_f}")
            if not math.isfinite(lon_f):
                raise InvalidNodeStateError(f"longitude must be a finite number, got {lon_f}")

            if not (-90.0 <= lat_f <= 90.0):
                raise InvalidNodeStateError(f"latitude ({lat_f}) is out of range [-90.0, 90.0]")
            if not (-180.0 <= lon_f <= 180.0):
                raise InvalidNodeStateError(f"longitude ({lon_f}) is out of range [-180.0, 180.0]")

            object.__setattr__(self, "latitude", lat_f)
            object.__setattr__(self, "longitude", lon_f)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Node):
            return False
        return (
            self.node_id == other.node_id
            and self.node_type == other.node_type
            and self.parent_id == other.parent_id
            and self.status == other.status
            and self.latitude == other.latitude
            and self.longitude == other.longitude
        )

    def __hash__(self) -> int:
        return hash(self.node_id)

    def __repr__(self) -> str:
        coords = f", latitude={self.latitude}, longitude={self.longitude}" if self.latitude is not None else ""
        return (
            f"Node(node_id={self.node_id!r}, node_type={self.node_type.value!r}, "
            f"parent_id={self.parent_id!r}, status={self.status.value!r}{coords})"
        )
