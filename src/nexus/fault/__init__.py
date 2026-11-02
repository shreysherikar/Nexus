"""Fault domain package."""

from nexus.fault.api import router
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
from nexus.fault.service import FaultService, get_fault_service, set_fault_service

__all__ = [
    "ConflictingFaultError",
    "EffectDimension",
    "FAULT_EFFECT_DIMENSIONS",
    "Fault",
    "FaultError",
    "FaultScenarioEngine",
    "FaultService",
    "FaultType",
    "GroundTruthRecord",
    "IncompatibleTargetError",
    "InvalidFaultStateError",
    "ScenarioError",
    "build_reference_scenarios",
    "get_fault_service",
    "router",
    "set_fault_service",
]
