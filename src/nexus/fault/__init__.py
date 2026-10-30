"""Fault domain package."""

from nexus.fault.engine import FaultScenarioEngine
from nexus.fault.exceptions import (
    ConflictingFaultError,
    FaultError,
    IncompatibleTargetError,
    InvalidFaultStateError,
    ScenarioError,
)
from nexus.fault.models import EffectDimension, FAULT_EFFECT_DIMENSIONS, Fault, FaultType, GroundTruthRecord
from nexus.fault.scenarios import build_reference_scenarios

__all__ = [
    "ConflictingFaultError",
    "EffectDimension",
    "FAULT_EFFECT_DIMENSIONS",
    "Fault",
    "FaultError",
    "FaultScenarioEngine",
    "FaultType",
    "GroundTruthRecord",
    "IncompatibleTargetError",
    "InvalidFaultStateError",
    "ScenarioError",
    "build_reference_scenarios",
]
