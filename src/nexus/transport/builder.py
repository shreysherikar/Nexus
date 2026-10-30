"""Factory builder for standard reference transport network links."""

from nexus.topology.enums import NodeStatus, NodeType
from nexus.topology.topology import Topology
from nexus.transport.exceptions import InvalidEndpointError
from nexus.transport.models import TransportLink
from nexus.transport.network import TransportNetwork


def build_reference_transport_network(
    topology: Topology,
    default_status: NodeStatus = NodeStatus.ONLINE,
) -> TransportNetwork:
    """Build and return standard transport links matching the 27-node reference topology.

    Link allocations:
    - 2 Core-to-Aggregation links:
      * LINK-CORE-AGG-01: CORE-01 -> AGG-01 (10000 Mbps, 1.5 ms)
      * LINK-CORE-AGG-02: CORE-01 -> AGG-02 (10000 Mbps, 1.5 ms)
    - 6 Aggregation-to-Site links:
      * LINK-AGG-SITE-01..03: AGG-01 -> SITE-01..03 (2500 Mbps, 5.0 ms)
      * LINK-AGG-SITE-04..06: AGG-02 -> SITE-04..06 (2500 Mbps, 5.0 ms)
    - 18 Site-to-Cell links:
      * LINK-SITE-CELL-01..18: SITE-XX -> CELL-YY (1000 Mbps, 1.0 ms)
    Total links: 26 (matching all 26 non-root parent-child edges).

    Args:
        topology: The 27-node reference topology.
        default_status: Initial operational status for created links (defaults to ONLINE).

    Returns:
        A validated TransportNetwork instance containing all 26 links.

    Raises:
        InvalidEndpointError: If the topology does not have the expected reference structure
                              or nodes are missing valid parent relationships.
    """
    # Explicit validation of expected reference topology hierarchy root
    if not topology.has_node("CORE-01"):
        raise InvalidEndpointError("Reference transport network requires root node 'CORE-01' in topology")
    core_node = topology.get_node("CORE-01")
    if core_node.node_type != NodeType.CORE:
        raise InvalidEndpointError(f"Expected CORE-01 to have type CORE, got {core_node.node_type.value}")

    transport = TransportNetwork(topology=topology)

    # 1. Core -> Aggregation links (2 links)
    for agg in topology.get_nodes_by_type(NodeType.AGGREGATION):
        if agg.parent_id != "CORE-01":
            raise InvalidEndpointError(
                f"Reference aggregation node '{agg.node_id}' must have parent 'CORE-01', got {agg.parent_id!r}"
            )
        link_id = f"LINK-CORE-{agg.node_id}"
        transport.add_link(
            TransportLink(
                link_id=link_id,
                upstream_node_id="CORE-01",
                downstream_node_id=agg.node_id,
                capacity_mbps=10000.0,
                latency_ms=1.5,
                status=default_status,
            )
        )

    # 2. Aggregation -> Site links (6 links)
    for site in topology.get_nodes_by_type(NodeType.SITE):
        if site.parent_id is None:
            raise InvalidEndpointError(
                f"Site node '{site.node_id}' has no parent_id configured"
            )
        link_id = f"LINK-{site.parent_id}-{site.node_id}"
        transport.add_link(
            TransportLink(
                link_id=link_id,
                upstream_node_id=site.parent_id,
                downstream_node_id=site.node_id,
                capacity_mbps=2500.0,
                latency_ms=5.0,
                status=default_status,
            )
        )

    # 3. Site -> Cell links (18 links)
    for cell in topology.get_nodes_by_type(NodeType.CELL):
        if cell.parent_id is None:
            raise InvalidEndpointError(
                f"Cell node '{cell.node_id}' has no parent_id configured"
            )
        link_id = f"LINK-{cell.parent_id}-{cell.node_id}"
        transport.add_link(
            TransportLink(
                link_id=link_id,
                upstream_node_id=cell.parent_id,
                downstream_node_id=cell.node_id,
                capacity_mbps=1000.0,
                latency_ms=1.0,
                status=default_status,
            )
        )

    return transport
