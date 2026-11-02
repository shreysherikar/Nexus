"""FastAPI router exposing Fault Injection & Scenario Management API."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status

from nexus.fault.exceptions import FaultError, ScenarioError
from nexus.fault.schemas import (
    ActivateScenarioRequest,
    ActiveScenarioResponse,
    FaultScenarioListResponse,
    ScenarioActionResponse,
)
from nexus.fault.service import FaultService, get_fault_service

router = APIRouter(prefix="/api/v1/faults", tags=["faults"])


@router.get(
    "/scenarios",
    response_model=FaultScenarioListResponse,
    summary="List predefined reference fault scenarios",
    description="Returns the catalog of 5 standard reference fault scenarios and their current activation status.",
)
def list_fault_scenarios(
    service: FaultService = Depends(get_fault_service),
) -> FaultScenarioListResponse:
    """Query available reference fault scenarios."""
    return service.get_reference_scenarios()


@router.get(
    "/active",
    response_model=ActiveScenarioResponse,
    summary="Get active fault scenario status",
    description="Returns current active fault scenario and active fault details influencing telemetry.",
)
def get_active_fault_scenario(
    service: FaultService = Depends(get_fault_service),
) -> ActiveScenarioResponse:
    """Retrieve active fault scenario."""
    return service.get_active_scenario()


@router.post(
    "/scenarios/{scenario_id}/activate",
    response_model=ScenarioActionResponse,
    summary="Activate a predefined reference fault scenario",
    description="Activates a fault scenario. Transformed telemetry will be produced during subsequent operator simulation steps.",
)
def activate_fault_scenario(
    scenario_id: str,
    request: Optional[ActivateScenarioRequest] = None,
    service: FaultService = Depends(get_fault_service),
) -> ScenarioActionResponse:
    """Activate specified fault scenario."""
    immediate = request.immediate if request else True
    base_time = request.base_time if request else None

    try:
        active_state = service.activate_scenario(
            scenario_key=scenario_id.lower().strip(),
            immediate=immediate,
            base_time=base_time,
        )
        return ScenarioActionResponse(
            success=True,
            message=f"Fault scenario '{active_state.name}' activated successfully.",
            active_scenario=active_state,
        )
    except ScenarioError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except FaultError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.post(
    "/scenarios/deactivate",
    response_model=ScenarioActionResponse,
    summary="Deactivate any active fault scenario",
    description="Deactivates active fault scenario, returning the network simulation to nominal baseline.",
)
def deactivate_fault_scenario(
    service: FaultService = Depends(get_fault_service),
) -> ScenarioActionResponse:
    """Deactivate active fault scenario."""
    active_state = service.deactivate_scenario()
    return ScenarioActionResponse(
        success=True,
        message="All fault scenarios deactivated. Network operating under nominal conditions.",
        active_scenario=active_state,
    )
