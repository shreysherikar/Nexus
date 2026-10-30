"""Factory functions for building standard network topologies."""

from nexus.topology.enums import NodeStatus, NodeType
from nexus.topology.models import Node
from nexus.topology.topology import Topology


def build_simulated_network(default_status: NodeStatus = NodeStatus.ONLINE) -> Topology:
    """Build and return the validated reference simulated network topology.

    The topology specification:
    - 1 CORE node: CORE-01
    - 2 AGGREGATION nodes: AGG-01, AGG-02 (children of CORE-01)
    - 6 SITE nodes: SITE-01..SITE-03 (children of AGG-01), SITE-04..SITE-06 (children of AGG-02)
    - 18 CELL nodes: 3 cells per site (CELL-01..CELL-18)
    Total nodes: 27

    Args:
        default_status: Operational status assigned to created nodes (defaults to ONLINE).

    Returns:
        A fully validated Topology instance.
    """
    topology = Topology()

    # 1. CORE tier
    topology.add_node(
        Node(node_id="CORE-01", node_type=NodeType.CORE, parent_id=None, status=default_status)
    )

    # 2. AGGREGATION tier (2 nodes)
    agg_nodes = ["AGG-01", "AGG-02"]
    for agg_id in agg_nodes:
        topology.add_node(
            Node(
                node_id=agg_id,
                node_type=NodeType.AGGREGATION,
                parent_id="CORE-01",
                status=default_status,
            )
        )

    # 3. SITE tier (6 nodes, 3 per aggregation node)
    site_mapping: dict[str, list[str]] = {
        "AGG-01": ["SITE-01", "SITE-02", "SITE-03"],
        "AGG-02": ["SITE-04", "SITE-05", "SITE-06"],
    }
    for agg_id, site_ids in site_mapping.items():
        for site_id in site_ids:
            topology.add_node(
                Node(
                    node_id=site_id,
                    node_type=NodeType.SITE,
                    parent_id=agg_id,
                    status=default_status,
                )
            )

    # 4. CELL tier (18 nodes, 3 per site)
    cell_idx = 1
    all_sites = ["SITE-01", "SITE-02", "SITE-03", "SITE-04", "SITE-05", "SITE-06"]
    for site_id in all_sites:
        for _ in range(3):
            cell_id = f"CELL-{cell_idx:02d}"
            topology.add_node(
                Node(
                    node_id=cell_id,
                    node_type=NodeType.CELL,
                    parent_id=site_id,
                    status=default_status,
                )
            )
            cell_idx += 1

    return topology
