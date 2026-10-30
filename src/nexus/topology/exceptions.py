"""Topology domain exceptions."""


class TopologyError(Exception):
    """Base exception for all topology-related errors."""


class NodeNotFoundError(TopologyError):
    """Raised when a requested node does not exist in the topology."""


class DuplicateNodeError(TopologyError):
    """Raised when attempting to add a node with an ID that already exists."""


class MissingParentError(TopologyError):
    """Raised when a node references a parent node ID that does not exist in the topology."""


class InvalidHierarchyError(TopologyError):
    """Raised when a parent-child relationship violates the defined network hierarchy."""


class CycleDetectedError(TopologyError):
    """Raised when a relationship would introduce a circular reference in the topology."""


class InvalidNodeStateError(TopologyError, ValueError):
    """Raised when a node entity is instantiated or configured with invalid state or attributes."""
