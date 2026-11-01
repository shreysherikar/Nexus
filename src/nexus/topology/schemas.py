"""Pydantic schemas for network topology REST endpoints."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class TopologyNodeResponse(BaseModel):
    """Schema representing a network topology node."""

    node_id: str = Field(..., description="Unique node identifier")
    node_type: str = Field(..., description="Tier type (CORE, AGGREGATION, SITE, CELL)")
    parent_id: Optional[str] = Field(None, description="Parent node ID or null for root")
    status: str = Field(..., description="Operational status (ONLINE, OFFLINE, DEGRADED, MAINTENANCE)")
    latitude: Optional[float] = Field(None, description="Physical latitude or null if unavailable")
    longitude: Optional[float] = Field(None, description="Physical longitude or null if unavailable")
    children: list[str] = Field(default_factory=list, description="Direct children node IDs")


class TopologyResponse(BaseModel):
    """Schema representing the complete network topology registry."""

    nodes: list[TopologyNodeResponse] = Field(..., description="All topology nodes")
    total_nodes: int = Field(..., description="Total count of nodes in topology")
    tiers: dict[str, int] = Field(..., description="Node count distribution per tier")
