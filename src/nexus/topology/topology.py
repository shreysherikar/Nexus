"""Topology container and graph operations."""

from collections import deque
from typing import Iterator, Optional

from nexus.topology.enums import NodeType
from nexus.topology.exceptions import (
    CycleDetectedError,
    DuplicateNodeError,
    InvalidHierarchyError,
    MissingParentError,
    NodeNotFoundError,
)
from nexus.topology.models import ALLOWED_PARENT_TYPES, Node


class Topology:
    """Manages the network topology graph, node registry, and hierarchy constraints."""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._children: dict[str, list[str]] = {}

    def add_node(self, node: Node) -> None:
        """Add a node to the topology, validating hierarchy, parent existence, and uniqueness.

        Args:
            node: The Node instance to register.

        Raises:
            DuplicateNodeError: If a node with the same node_id already exists.
            InvalidHierarchyError: If the node's parent relationship violates hierarchy rules.
            MissingParentError: If the specified parent_id does not exist.
            CycleDetectedError: If a self-referencing relationship is detected.
        """
        if node.node_id in self._nodes:
            raise DuplicateNodeError(f"Node '{node.node_id}' already exists in the topology")

        # Validate self-parenting
        if node.parent_id is not None and node.parent_id == node.node_id:
            raise CycleDetectedError(
                f"Node '{node.node_id}' cannot specify itself as its parent"
            )

        # Validate hierarchy and parent existence
        expected_parent_type = ALLOWED_PARENT_TYPES[node.node_type]
        if expected_parent_type is None:
            # CORE nodes must not have a parent
            if node.parent_id is not None:
                raise InvalidHierarchyError(
                    f"{node.node_type.value} node '{node.node_id}' cannot have a parent"
                )
        else:
            # Non-CORE nodes must specify a valid parent
            if node.parent_id is None:
                raise InvalidHierarchyError(
                    f"{node.node_type.value} node '{node.node_id}' requires a parent "
                    f"of type {expected_parent_type.value}"
                )
            if node.parent_id not in self._nodes:
                raise MissingParentError(
                    f"Parent node '{node.parent_id}' does not exist in the topology"
                )

            parent_node = self._nodes[node.parent_id]
            if parent_node.node_type != expected_parent_type:
                raise InvalidHierarchyError(
                    f"Invalid hierarchy: {node.node_type.value} node '{node.node_id}' "
                    f"cannot have parent '{parent_node.node_id}' of type {parent_node.node_type.value}. "
                    f"Expected parent type: {expected_parent_type.value}"
                )

        # Register node
        self._nodes[node.node_id] = node
        self._children[node.node_id] = []
        if node.parent_id is not None:
            self._children[node.parent_id].append(node.node_id)

    def get_node(self, node_id: str) -> Node:
        """Retrieve a node by its identifier.

        Args:
            node_id: Identifier of the node.

        Returns:
            The requested Node.

        Raises:
            NodeNotFoundError: If the node is not in the topology.
        """
        if node_id not in self._nodes:
            raise NodeNotFoundError(f"Node '{node_id}' does not exist in the topology")
        return self._nodes[node_id]

    def has_node(self, node_id: str) -> bool:
        """Check whether a node ID exists in the topology."""
        return node_id in self._nodes

    def get_parent(self, node_id: str) -> Optional[Node]:
        """Retrieve the immediate parent of a node.

        Args:
            node_id: Identifier of the node.

        Returns:
            The parent Node, or None if the node has no parent.

        Raises:
            NodeNotFoundError: If the node does not exist.
        """
        node = self.get_node(node_id)
        if node.parent_id is None:
            return None
        return self.get_node(node.parent_id)

    def get_children(self, node_id: str) -> list[Node]:
        """Retrieve the direct children of a node.

        Args:
            node_id: Identifier of the parent node.

        Returns:
            List of direct child Node entities.

        Raises:
            NodeNotFoundError: If the node does not exist.
        """
        self.get_node(node_id)  # Validate node existence
        child_ids = self._children.get(node_id, [])
        return [self._nodes[cid] for cid in child_ids]

    def get_ancestors(self, node_id: str) -> list[Node]:
        """Retrieve all ancestors of a node, ordered from immediate parent to root.

        Args:
            node_id: Identifier of the starting node.

        Returns:
            List of ancestor Nodes [parent, grandparent, ...].

        Raises:
            NodeNotFoundError: If the node does not exist.
            CycleDetectedError: If a cycle is detected during traversal.
        """
        self.get_node(node_id)  # Validate node existence
        ancestors: list[Node] = []
        visited: set[str] = {node_id}
        current_id = self._nodes[node_id].parent_id

        while current_id is not None:
            if current_id in visited:
                raise CycleDetectedError(
                    f"Cycle detected while traversing ancestors of '{node_id}'"
                )
            visited.add(current_id)
            parent_node = self.get_node(current_id)
            ancestors.append(parent_node)
            current_id = parent_node.parent_id

        return ancestors

    def get_descendants(self, node_id: str) -> list[Node]:
        """Retrieve all descendants of a node using breadth-first traversal.

        Args:
            node_id: Identifier of the starting node.

        Returns:
            List of all descendant Nodes across all subordinate tiers.

        Raises:
            NodeNotFoundError: If the node does not exist.
            CycleDetectedError: If a cycle is detected during traversal.
        """
        self.get_node(node_id)  # Validate node existence
        descendants: list[Node] = []
        visited: set[str] = {node_id}
        queue: deque[str] = deque(self._children.get(node_id, []))

        while queue:
            child_id = queue.popleft()
            if child_id in visited:
                raise CycleDetectedError(
                    f"Cycle detected while traversing descendants of '{node_id}'"
                )
            visited.add(child_id)
            child_node = self.get_node(child_id)
            descendants.append(child_node)
            queue.extend(self._children.get(child_id, []))

        return descendants

    def set_parent(self, child_id: str, new_parent_id: Optional[str]) -> None:
        """Establish or update a parent-child relationship between two existing nodes.

        Args:
            child_id: Node whose parent is to be updated.
            new_parent_id: Node ID of the new parent, or None for root nodes.

        Raises:
            NodeNotFoundError: If child or parent node does not exist.
            InvalidHierarchyError: If the relationship violates hierarchy rules.
            CycleDetectedError: If the relationship creates a cycle.
        """
        child = self.get_node(child_id)

        if new_parent_id is not None and new_parent_id == child_id:
            raise CycleDetectedError(f"Node '{child_id}' cannot specify itself as its parent")

        expected_parent_type = ALLOWED_PARENT_TYPES[child.node_type]
        if expected_parent_type is None:
            if new_parent_id is not None:
                raise InvalidHierarchyError(
                    f"{child.node_type.value} node '{child_id}' cannot have a parent"
                )
        else:
            if new_parent_id is None:
                raise InvalidHierarchyError(
                    f"{child.node_type.value} node '{child_id}' requires a parent "
                    f"of type {expected_parent_type.value}"
                )
            if new_parent_id not in self._nodes:
                raise MissingParentError(
                    f"Parent node '{new_parent_id}' does not exist in the topology"
                )

            new_parent = self._nodes[new_parent_id]
            if new_parent.node_type != expected_parent_type:
                raise InvalidHierarchyError(
                    f"Invalid hierarchy: {child.node_type.value} node '{child_id}' "
                    f"cannot have parent '{new_parent.node_id}' of type {new_parent.node_type.value}. "
                    f"Expected parent type: {expected_parent_type.value}"
                )

            # Cycle detection: Ensure child_id is not an ancestor of new_parent
            curr: Optional[str] = new_parent_id
            while curr is not None:
                if curr == child_id:
                    raise CycleDetectedError(
                        f"Cycle detected: '{child_id}' is already an ancestor of '{new_parent_id}'"
                    )
                curr = self._nodes[curr].parent_id

        # Disconnect from current parent
        if child.parent_id is not None and child.parent_id in self._children:
            if child_id in self._children[child.parent_id]:
                self._children[child.parent_id].remove(child_id)

        # Connect to new parent
        child.parent_id = new_parent_id
        if new_parent_id is not None:
            self._children[new_parent_id].append(child_id)

    def link_nodes(self, parent_id: str, child_id: str) -> None:
        """Convenience method to link an existing child to an existing parent."""
        self.set_parent(child_id=child_id, new_parent_id=parent_id)

    def get_nodes_by_type(self, node_type: NodeType) -> list[Node]:
        """Return all nodes belonging to a specific tier."""
        return [node for node in self._nodes.values() if node.node_type == node_type]

    def all_nodes(self) -> list[Node]:
        """Return a list of all nodes registered in the topology."""
        return list(self._nodes.values())

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: str) -> bool:
        return node_id in self._nodes

    def __iter__(self) -> Iterator[Node]:
        return iter(self._nodes.values())
