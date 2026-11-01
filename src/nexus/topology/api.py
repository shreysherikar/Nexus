"""FastAPI REST router for network topology."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status

from nexus.topology.builder import build_simulated_network
from nexus.topology.exceptions import NodeNotFoundError
from nexus.topology.schemas import TopologyNodeResponse, TopologyResponse
from nexus.topology.topology import Topology

_topology_instance: Optional[Topology] = None


def get_topology_registry() -> Topology:
    """Retrieve or initialize the active topology source of truth."""
    global _topology_instance
    if _topology_instance is None:
        _topology_instance = build_simulated_network()
    return _topology_instance


def set_topology_registry(topo: Topology) -> None:
    """Override active topology source of truth (e.g. for testing)."""
    global _topology_instance
    _topology_instance = topo


router = APIRouter(prefix="/api/v1", tags=["topology"])


@router.get(
    "/topology",
    response_model=TopologyResponse,
    summary="Get network topology",
    description="Retrieve the complete network topology registry with nodes, hierarchy, and coordinates.",
)
def get_topology(
    topo: Topology = Depends(get_topology_registry),
) -> TopologyResponse:
    """Return all nodes from the topology registry with hierarchy and coordinate details."""
    tier_order = {"CORE": 0, "AGGREGATION": 1, "SITE": 2, "CELL": 3}

    sorted_nodes = sorted(
        topo.all_nodes(),
        key=lambda n: (tier_order.get(n.node_type.value, 99), n.node_id),
    )

    node_responses: list[TopologyNodeResponse] = []
    tier_counts: dict[str, int] = {}

    for node in sorted_nodes:
        t_val = node.node_type.value
        tier_counts[t_val] = tier_counts.get(t_val, 0) + 1
        children_ids = [c.node_id for c in topo.get_children(node.node_id)]
        node_responses.append(
            TopologyNodeResponse(
                node_id=node.node_id,
                node_type=t_val,
                parent_id=node.parent_id,
                status=node.status.value,
                latitude=node.latitude,
                longitude=node.longitude,
                children=children_ids,
            )
        )

    return TopologyResponse(
        nodes=node_responses,
        total_nodes=len(node_responses),
        tiers=tier_counts,
    )


@router.get(
    "/topology/nodes/{node_id}",
    response_model=TopologyNodeResponse,
    summary="Get topology node by ID",
    description="Retrieve details and children for a single network topology node.",
)
def get_topology_node(
    node_id: str,
    topo: Topology = Depends(get_topology_registry),
) -> TopologyNodeResponse:
    """Return single node from topology registry with hierarchical links."""
    try:
        node = topo.get_node(node_id)
    except (KeyError, NodeNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{node_id}' not found in topology registry",
        )

    children_ids = [c.node_id for c in topo.get_children(node.node_id)]
    return TopologyNodeResponse(
        node_id=node.node_id,
        node_type=node.node_type.value,
        parent_id=node.parent_id,
        status=node.status.value,
        latitude=node.latitude,
        longitude=node.longitude,
        children=children_ids,
    )
