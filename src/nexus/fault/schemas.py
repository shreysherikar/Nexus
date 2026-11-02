"""Pydantic schemas for Fault Injection and Scenario API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class FaultInfo(BaseModel):
    """Information about an individual fault instance."""

    model_config = ConfigDict(from_attributes=True)

    fault_id: str
    fault_type: str
    target_id: str
    severity: float = Field(ge=0.0, le=1.0)
    start_time: datetime
    end_time: datetime
    affected_nodes: list[str] = Field(default_factory=list)
    description: Optional[str] = None


class FaultScenarioInfo(BaseModel):
    """Catalog representation of a reference fault scenario."""

    model_config = ConfigDict(from_attributes=True)

    id: str  # Reference key, e.g. "radio_interference"
    scenario_id: str  # Canonical ID, e.g. "SCENARIO-INTERFERENCE-01"
    name: str  # Human-readable title
    description: str
    fault_type: str
    target_id: str
    severity: float
    affected_nodes: list[str]
    is_active: bool = False


class FaultScenarioListResponse(BaseModel):
    """Response containing catalog of available reference fault scenarios."""

    items: list[FaultScenarioInfo]
    total: int
    active_scenario_id: Optional[str] = None


class ActiveScenarioResponse(BaseModel):
    """Current runtime active fault scenario state."""

    active: bool
    scenario_id: Optional[str] = None
    scenario_key: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    faults: list[FaultInfo] = Field(default_factory=list)
    activated_at: Optional[datetime] = None


class ActivateScenarioRequest(BaseModel):
    """Optional payload to customize scenario activation."""

    immediate: bool = Field(
        default=True,
        description="Whether fault interval should cover current simulation time immediately",
    )
    base_time: Optional[datetime] = Field(
        default=None,
        description="Optional explicit base time for scenario evaluation window",
    )


class ScenarioActionResponse(BaseModel):
    """Outcome of an activate or deactivate fault operation."""

    success: bool
    message: str
    active_scenario: ActiveScenarioResponse
