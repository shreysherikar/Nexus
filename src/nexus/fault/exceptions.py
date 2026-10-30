"""Fault domain exceptions."""


class FaultError(Exception):
    """Base exception for all fault domain errors."""


class InvalidFaultStateError(FaultError, ValueError):
    """Raised when a Fault definition violates structural, type, or boundary constraints."""


class ConflictingFaultError(FaultError):
    """Raised when two faults have temporal overlap, shared affected nodes, and shared operational effect dimensions."""


class IncompatibleTargetError(FaultError, ValueError):
    """Raised when a fault is applied to an incompatible node or link target."""


class ScenarioError(FaultError):
    """Raised when a scenario definition or execution constraint is violated."""
