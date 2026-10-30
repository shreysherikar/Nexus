"""Domain models for network topology nodes and hierarchy rules."""

from dataclasses import dataclass
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


@dataclass
class Node:
    """Represents a network node entity.

    Attributes:
        node_id: Unique string identifier for the node (e.g. 'CORE-01', 'CELL-01').
        node_type: Tier in the hierarchy (CORE, AGGREGATION, SITE, CELL).
        parent_id: Optional string identifier of the parent node.
        status: Current operational status (ONLINE, OFFLINE, DEGRADED, MAINTENANCE).
    """

    node_id: str
    node_type: NodeType
    parent_id: Optional[str] = None
    status: NodeStatus = NodeStatus.ONLINE

    def __post_init__(self) -> None:
        # Validate node_id
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise InvalidNodeStateError("node_id must be a non-empty string")

        # Validate and coerce node_type
        if not isinstance(self.node_type, NodeType):
            try:
                self.node_type = NodeType(self.node_type)
            except (ValueError, TypeError) as exc:
                raise InvalidNodeStateError(
                    f"Invalid node_type '{self.node_type}'. Expected one of: "
                    f"{', '.join(t.value for t in NodeType)}"
                ) from exc

        # Validate and coerce status
        if not isinstance(self.status, NodeStatus):
            try:
                self.status = NodeStatus(self.status)
            except (ValueError, TypeError) as exc:
                raise InvalidNodeStateError(
                    f"Invalid status '{self.status}'. Expected one of: "
                    f"{', '.join(s.value for s in NodeStatus)}"
                ) from exc

        # Validate parent_id type if provided
        if self.parent_id is not None:
            if not isinstance(self.parent_id, str) or not self.parent_id.strip():
                raise InvalidNodeStateError("parent_id must be None or a non-empty string")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Node):
            return False
        return (
            self.node_id == other.node_id
            and self.node_type == other.node_type
            and self.parent_id == other.parent_id
            and self.status == other.status
        )

    def __hash__(self) -> int:
        return hash(self.node_id)

    def __repr__(self) -> str:
        return (
            f"Node(node_id={self.node_id!r}, node_type={self.node_type.value!r}, "
            f"parent_id={self.parent_id!r}, status={self.status.value!r})"
        )
