"""Topology domain package."""

from nexus.topology.builder import build_simulated_network
from nexus.topology.enums import NodeStatus, NodeType
from nexus.topology.exceptions import (
    CycleDetectedError,
    DuplicateNodeError,
    InvalidHierarchyError,
    InvalidNodeStateError,
    MissingParentError,
    NodeNotFoundError,
    TopologyError,
)
from nexus.topology.models import ALLOWED_PARENT_TYPES, Node
from nexus.topology.topology import Topology

__all__ = [
    "ALLOWED_PARENT_TYPES",
    "CycleDetectedError",
    "DuplicateNodeError",
    "InvalidHierarchyError",
    "InvalidNodeStateError",
    "MissingParentError",
    "NodeNotFoundError",
    "NodeStatus",
    "NodeType",
    "Node",
    "Topology",
    "TopologyError",
    "build_simulated_network",
]
