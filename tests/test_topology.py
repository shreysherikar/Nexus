"""Unit and integration tests for the Network Topology domain."""

from dataclasses import FrozenInstanceError
import pytest

from nexus.topology import (
    CycleDetectedError,
    DuplicateNodeError,
    InvalidHierarchyError,
    InvalidNodeStateError,
    MissingParentError,
    NodeNotFoundError,
    NodeStatus,
    NodeType,
    Node,
    Topology,
    build_simulated_network,
)


class TestReferenceTopology:
    """Tests validating the reference 27-node simulated network specification."""

    @pytest.fixture
    def net(self) -> Topology:
        return build_simulated_network()

    def test_total_node_count(self, net: Topology) -> None:
        """Verify the topology contains exactly 27 nodes."""
        assert len(net) == 27
        assert len(net.all_nodes()) == 27

    def test_expected_node_counts_by_type(self, net: Topology) -> None:
        """Verify expected counts per tier: 1 Core, 2 Aggregation, 6 Site, 18 Cell."""
        core_nodes = net.get_nodes_by_type(NodeType.CORE)
        agg_nodes = net.get_nodes_by_type(NodeType.AGGREGATION)
        site_nodes = net.get_nodes_by_type(NodeType.SITE)
        cell_nodes = net.get_nodes_by_type(NodeType.CELL)

        assert len(core_nodes) == 1
        assert len(agg_nodes) == 2
        assert len(site_nodes) == 6
        assert len(cell_nodes) == 18

        assert core_nodes[0].node_id == "CORE-01"
        assert {n.node_id for n in agg_nodes} == {"AGG-01", "AGG-02"}

    def test_unique_node_ids(self, net: Topology) -> None:
        """Verify that all node IDs across the network are strictly unique."""
        all_ids = [node.node_id for node in net]
        assert len(all_ids) == len(set(all_ids)) == 27

    def test_valid_parent_child_relationships(self, net: Topology) -> None:
        """Verify parent and child links across every tier."""
        # CORE-01
        core = net.get_node("CORE-01")
        assert core.parent_id is None
        assert net.get_parent("CORE-01") is None
        core_children = net.get_children("CORE-01")
        assert [c.node_id for c in core_children] == ["AGG-01", "AGG-02"]

        # Aggregation nodes
        for agg_id in ["AGG-01", "AGG-02"]:
            agg_node = net.get_node(agg_id)
            assert agg_node.parent_id == "CORE-01"
            assert net.get_parent(agg_id) == core
            assert len(net.get_children(agg_id)) == 3

        # Site nodes (each aggregation owns exactly 3 sites)
        agg1_sites = [c.node_id for c in net.get_children("AGG-01")]
        agg2_sites = [c.node_id for c in net.get_children("AGG-02")]
        assert agg1_sites == ["SITE-01", "SITE-02", "SITE-03"]
        assert agg2_sites == ["SITE-04", "SITE-05", "SITE-06"]

        # Cell nodes (each site owns exactly 3 cells)
        for site in net.get_nodes_by_type(NodeType.SITE):
            site_cells = net.get_children(site.node_id)
            assert len(site_cells) == 3
            for cell in site_cells:
                assert cell.parent_id == site.node_id
                assert len(net.get_children(cell.node_id)) == 0

    def test_correct_children_and_descendants_of_agg_01(self, net: Topology) -> None:
        """Verify direct children and full descendants for AGG-01."""
        # Direct children: exactly 3 sites
        children = net.get_children("AGG-01")
        child_ids = [c.node_id for c in children]
        assert child_ids == ["SITE-01", "SITE-02", "SITE-03"]

        # Descendants: 3 sites + 9 cells = 12 total descendants
        descendants = net.get_descendants("AGG-01")
        descendant_ids = [d.node_id for d in descendants]
        assert len(descendant_ids) == 12

        expected_descendant_ids = [
            "SITE-01",
            "SITE-02",
            "SITE-03",
            "CELL-01",
            "CELL-02",
            "CELL-03",
            "CELL-04",
            "CELL-05",
            "CELL-06",
            "CELL-07",
            "CELL-08",
            "CELL-09",
        ]
        assert set(descendant_ids) == set(expected_descendant_ids)

    def test_correct_parent_and_ancestors_of_cell_01(self, net: Topology) -> None:
        """Verify parent and ancestors for CELL-01."""
        parent = net.get_parent("CELL-01")
        assert parent is not None
        assert parent.node_id == "SITE-01"
        assert parent.node_type == NodeType.SITE

        ancestors = net.get_ancestors("CELL-01")
        ancestor_ids = [a.node_id for a in ancestors]
        # Ancestors ordered immediate parent to root
        assert ancestor_ids == ["SITE-01", "AGG-01", "CORE-01"]
        assert [a.node_type for a in ancestors] == [
            NodeType.SITE,
            NodeType.AGGREGATION,
            NodeType.CORE,
        ]

    def test_builder_default_status(self, net: Topology) -> None:
        """Verify builder assigns default ONLINE status across all nodes."""
        for node in net:
            assert node.status == NodeStatus.ONLINE

    def test_builder_custom_default_status(self) -> None:
        """Verify builder applies a custom default status to all nodes."""
        custom_net = build_simulated_network(default_status=NodeStatus.MAINTENANCE)
        assert len(custom_net) == 27
        for node in custom_net:
            assert node.status == NodeStatus.MAINTENANCE


class TestTopologyValidationAndErrors:
    """Tests covering error cases, hierarchy constraints, and reparenting safety."""

    def test_duplicate_node_id(self) -> None:
        """Adding a node with an existing node_id must raise DuplicateNodeError."""
        topo = Topology()
        topo.add_node(Node("CORE-01", NodeType.CORE))
        with pytest.raises(DuplicateNodeError, match="already exists"):
            topo.add_node(Node("CORE-01", NodeType.CORE))

    def test_missing_parent_on_add(self) -> None:
        """Adding a non-root node referencing a missing parent must raise MissingParentError."""
        topo = Topology()
        with pytest.raises(MissingParentError, match="does not exist in the topology"):
            topo.add_node(Node("AGG-01", NodeType.AGGREGATION, parent_id="CORE-99"))

    def test_missing_parent_on_set_parent(self) -> None:
        """Setting parent to a non-existent parent ID must raise MissingParentError."""
        topo = Topology()
        topo.add_node(Node("CORE-01", NodeType.CORE))
        topo.add_node(Node("AGG-01", NodeType.AGGREGATION, parent_id="CORE-01"))
        with pytest.raises(MissingParentError, match="does not exist in the topology"):
            topo.set_parent("AGG-01", "NON-EXISTENT")

    def test_invalid_hierarchy_core_with_parent(self) -> None:
        """A CORE node must not have a parent."""
        topo = Topology()
        with pytest.raises(InvalidHierarchyError, match="cannot have a parent"):
            topo.add_node(Node("CORE-01", NodeType.CORE, parent_id="SOME-PARENT"))

    def test_invalid_hierarchy_non_core_missing_parent(self) -> None:
        """Non-CORE nodes must specify a parent."""
        topo = Topology()
        with pytest.raises(InvalidHierarchyError, match="requires a parent"):
            topo.add_node(Node("AGG-01", NodeType.AGGREGATION, parent_id=None))
        with pytest.raises(InvalidHierarchyError, match="requires a parent"):
            topo.add_node(Node("SITE-01", NodeType.SITE, parent_id=None))
        with pytest.raises(InvalidHierarchyError, match="requires a parent"):
            topo.add_node(Node("CELL-01", NodeType.CELL, parent_id=None))

    def test_invalid_hierarchy_wrong_parent_types(self) -> None:
        """Verify strict parent tier rules."""
        topo = Topology()
        topo.add_node(Node("CORE-01", NodeType.CORE))
        topo.add_node(Node("AGG-01", NodeType.AGGREGATION, parent_id="CORE-01"))
        topo.add_node(Node("SITE-01", NodeType.SITE, parent_id="AGG-01"))
        topo.add_node(Node("CELL-01", NodeType.CELL, parent_id="SITE-01"))

        # AGGREGATION cannot have SITE as parent
        with pytest.raises(InvalidHierarchyError, match="cannot have parent 'SITE-01' of type SITE"):
            topo.add_node(Node("AGG-02", NodeType.AGGREGATION, parent_id="SITE-01"))

        # SITE cannot have CORE as parent
        with pytest.raises(InvalidHierarchyError, match="cannot have parent 'CORE-01' of type CORE"):
            topo.add_node(Node("SITE-02", NodeType.SITE, parent_id="CORE-01"))

        # CELL cannot have AGGREGATION as parent
        with pytest.raises(InvalidHierarchyError, match="cannot have parent 'AGG-01' of type AGGREGATION"):
            topo.add_node(Node("CELL-02", NodeType.CELL, parent_id="AGG-01"))

        # CELL cannot have CORE as parent
        with pytest.raises(InvalidHierarchyError, match="cannot have parent 'CORE-01' of type CORE"):
            topo.add_node(Node("CELL-03", NodeType.CELL, parent_id="CORE-01"))

    def test_cycle_detection_self_parent(self) -> None:
        """A node specifying itself as its parent must raise CycleDetectedError."""
        topo = Topology()
        with pytest.raises(CycleDetectedError, match="cannot specify itself as its parent"):
            topo.add_node(Node("AGG-01", NodeType.AGGREGATION, parent_id="AGG-01"))

    def test_cycle_detection_set_parent_self(self) -> None:
        """set_parent with child_id == new_parent_id must raise CycleDetectedError."""
        topo = Topology()
        topo.add_node(Node("CORE-01", NodeType.CORE))
        topo.add_node(Node("AGG-01", NodeType.AGGREGATION, parent_id="CORE-01"))
        with pytest.raises(CycleDetectedError, match="cannot specify itself as its parent"):
            topo.set_parent("AGG-01", "AGG-01")

    def test_set_parent_root_node_raises_invalid_hierarchy(self) -> None:
        """Attempting to assign a parent to a CORE root node must raise InvalidHierarchyError."""
        topo = Topology()
        topo.add_node(Node("CORE-01", NodeType.CORE))
        topo.add_node(Node("AGG-01", NodeType.AGGREGATION, parent_id="CORE-01"))

        with pytest.raises(InvalidHierarchyError, match="CORE node 'CORE-01' cannot have a parent"):
            topo.set_parent("CORE-01", "AGG-01")

    def test_defensive_ancestor_traversal_cycle_protection(self) -> None:
        """Defensive test: If internal state were ever corrupted into a cycle, get_ancestors raises CycleDetectedError."""
        topo = Topology()
        topo.add_node(Node("CORE-01", NodeType.CORE))
        topo.add_node(Node("AGG-01", NodeType.AGGREGATION, parent_id="CORE-01"))
        topo.add_node(Node("SITE-01", NodeType.SITE, parent_id="AGG-01"))

        # Intentionally introduce a corrupted loop in internal dictionary without public API
        corrupted_site = Node("SITE-01", NodeType.SITE, parent_id="SITE-01")
        topo._nodes["SITE-01"] = corrupted_site

        with pytest.raises(CycleDetectedError, match="Cycle detected while traversing ancestors"):
            topo.get_ancestors("SITE-01")

    def test_defensive_descendant_traversal_cycle_protection(self) -> None:
        """Defensive test: If internal state were ever corrupted into a cycle, get_descendants raises CycleDetectedError."""
        topo = Topology()
        topo.add_node(Node("CORE-01", NodeType.CORE))
        topo.add_node(Node("AGG-01", NodeType.AGGREGATION, parent_id="CORE-01"))

        # Introduce a corrupted child back-reference in internal child list
        topo._children["AGG-01"].append("AGG-01")

        with pytest.raises(CycleDetectedError, match="Cycle detected while traversing descendants"):
            topo.get_descendants("CORE-01")

    def test_node_not_found_errors(self) -> None:
        """Querying non-existent nodes must raise NodeNotFoundError."""
        topo = Topology()
        with pytest.raises(NodeNotFoundError):
            topo.get_node("UNKNOWN")
        with pytest.raises(NodeNotFoundError):
            topo.get_parent("UNKNOWN")
        with pytest.raises(NodeNotFoundError):
            topo.get_children("UNKNOWN")
        with pytest.raises(NodeNotFoundError):
            topo.get_ancestors("UNKNOWN")
        with pytest.raises(NodeNotFoundError):
            topo.get_descendants("UNKNOWN")

    def test_set_parent_reparents_successfully_preserving_attributes(self) -> None:
        """Verify valid reparenting replaces frozen Node, preserving status and type."""
        topo = build_simulated_network()
        # Reparent SITE-01 from AGG-01 to AGG-02
        site_before = topo.get_node("SITE-01")
        assert site_before.parent_id == "AGG-01"

        topo.set_parent("SITE-01", "AGG-02")
        site_after = topo.get_node("SITE-01")

        assert site_after.parent_id == "AGG-02"
        assert site_after.node_type == site_before.node_type
        assert site_after.status == site_before.status
        assert site_after.node_id == "SITE-01"

        # Verify child index updates
        assert "SITE-01" not in [c.node_id for c in topo.get_children("AGG-01")]
        assert "SITE-01" in [c.node_id for c in topo.get_children("AGG-02")]

    def test_link_nodes_convenience_method(self) -> None:
        """Verify link_nodes delegates to set_parent."""
        topo = build_simulated_network()
        topo.link_nodes(parent_id="AGG-02", child_id="SITE-01")
        assert topo.get_node("SITE-01").parent_id == "AGG-02"

    def test_failed_reparenting_preserves_original_state(self) -> None:
        """When reparenting fails validation, neither parent nor child indices are modified."""
        topo = build_simulated_network()
        agg1_children_before = [c.node_id for c in topo.get_children("AGG-01")]
        agg2_children_before = [c.node_id for c in topo.get_children("AGG-02")]

        # Attempt invalid reparenting: SITE cannot have CORE as parent
        with pytest.raises(InvalidHierarchyError):
            topo.set_parent("SITE-01", "CORE-01")

        # SITE-01 parent remains AGG-01
        assert topo.get_node("SITE-01").parent_id == "AGG-01"
        assert [c.node_id for c in topo.get_children("AGG-01")] == agg1_children_before
        assert [c.node_id for c in topo.get_children("AGG-02")] == agg2_children_before

        # Attempt reparenting to non-existent parent
        with pytest.raises(MissingParentError):
            topo.set_parent("SITE-01", "AGG-99")

        assert topo.get_node("SITE-01").parent_id == "AGG-01"
        assert [c.node_id for c in topo.get_children("AGG-01")] == agg1_children_before

    def test_reparenting_to_existing_parent_preserves_child_order(self) -> None:
        """Reparenting to the already assigned parent is a no-op that preserves exact child ordering."""
        topo = build_simulated_network()
        agg1_children_before = [c.node_id for c in topo.get_children("AGG-01")]

        # SITE-02 is already a child of AGG-01
        topo.set_parent("SITE-02", "AGG-01")
        agg1_children_after = [c.node_id for c in topo.get_children("AGG-01")]

        assert agg1_children_before == agg1_children_after


class TestTopologyGraphInvariantsAndEncapsulation:
    """Tests for graph immutability, encapsulation, and empty topology states."""

    def test_empty_topology_behavior(self) -> None:
        """Verify behavior of an empty Topology instance."""
        topo = Topology()
        assert len(topo) == 0
        assert topo.all_nodes() == []
        assert topo.get_nodes_by_type(NodeType.CORE) == []
        assert topo.get_nodes_by_type(NodeType.CELL) == []
        assert not topo.has_node("CORE-01")
        assert "CORE-01" not in topo
        with pytest.raises(NodeNotFoundError):
            topo.get_node("CORE-01")

    def test_deterministic_traversal_ordering(self) -> None:
        """Verify deterministic BFS descendant ordering and bottom-up ancestor ordering."""
        topo = build_simulated_network()

        # Ancestors of CELL-18: strictly bottom-up
        ancestor_ids = [a.node_id for a in topo.get_ancestors("CELL-18")]
        assert ancestor_ids == ["SITE-06", "AGG-02", "CORE-01"]

        # Descendants of CORE-01: deterministic BFS tier ordering
        descendant_nodes = topo.get_descendants("CORE-01")
        assert len(descendant_nodes) == 26
        descendant_ids = [d.node_id for d in descendant_nodes]
        # Tier 1: Aggregation
        assert descendant_ids[:2] == ["AGG-01", "AGG-02"]
        # Tier 2: Sites
        assert descendant_ids[2:8] == [f"SITE-{i:02d}" for i in range(1, 7)]
        # Tier 3: Cells
        assert descendant_ids[8:] == [f"CELL-{i:02d}" for i in range(1, 19)]

    def test_returned_collections_are_defensive_copies(self) -> None:
        """Clearing or modifying returned lists must not mutate internal topology structures."""
        topo = build_simulated_network()

        children = topo.get_children("AGG-01")
        assert len(children) == 3
        children.clear()
        assert len(topo.get_children("AGG-01")) == 3

        all_nodes = topo.all_nodes()
        all_nodes.clear()
        assert len(topo.all_nodes()) == 27

        descendants = topo.get_descendants("AGG-01")
        descendants.clear()
        assert len(topo.get_descendants("AGG-01")) == 12

    def test_returned_node_objects_cannot_mutate_stored_topology(self) -> None:
        """Frozen Node guarantees external callers cannot mutate node attributes."""
        topo = build_simulated_network()
        node = topo.get_node("SITE-01")

        with pytest.raises(FrozenInstanceError):
            node.parent_id = "AGG-02"  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            node.status = NodeStatus.DEGRADED  # type: ignore[misc]

        with pytest.raises(FrozenInstanceError):
            node.node_type = NodeType.CORE  # type: ignore[misc]

        # Stored topology remains completely untouched
        assert topo.get_node("SITE-01").parent_id == "AGG-01"
        assert topo.get_node("SITE-01").status == NodeStatus.ONLINE
        assert "SITE-01" in [c.node_id for c in topo.get_children("AGG-01")]


class TestNodeEntityValidation:
    """Tests for Node entity state, validation, immutability, and representation."""

    def test_valid_node_creation(self) -> None:
        node = Node(
            node_id="CORE-01",
            node_type=NodeType.CORE,
            parent_id=None,
            status=NodeStatus.ONLINE,
        )
        assert node.node_id == "CORE-01"
        assert node.node_type == NodeType.CORE
        assert node.parent_id is None
        assert node.status == NodeStatus.ONLINE

    def test_frozen_node_rejects_direct_attribute_assignment(self) -> None:
        """Node instances must reject attribute mutation with FrozenInstanceError."""
        node = Node("CORE-01", NodeType.CORE)
        with pytest.raises(FrozenInstanceError):
            node.node_id = "CORE-02"  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            node.status = NodeStatus.OFFLINE  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            node.parent_id = "SOME-PARENT"  # type: ignore[misc]

    def test_string_coercion_for_enums(self) -> None:
        """Valid string names for enums should be coerced successfully in frozen dataclass."""
        node = Node(
            node_id="CELL-01",
            node_type="CELL",  # type: ignore[arg-type]
            parent_id="SITE-01",
            status="DEGRADED",  # type: ignore[arg-type]
        )
        assert node.node_type == NodeType.CELL
        assert node.status == NodeStatus.DEGRADED

    def test_invalid_node_type(self) -> None:
        """Invalid node_type must raise InvalidNodeStateError."""
        with pytest.raises(InvalidNodeStateError, match="Invalid node_type"):
            Node(node_id="ROUTER-01", node_type="ROUTER")  # type: ignore[arg-type]

    def test_invalid_node_status(self) -> None:
        """Invalid status must raise InvalidNodeStateError."""
        with pytest.raises(InvalidNodeStateError, match="Invalid status"):
            Node(
                node_id="CORE-01",
                node_type=NodeType.CORE,
                status="EXPLODED",  # type: ignore[arg-type]
            )

    def test_invalid_node_id_empty(self) -> None:
        """Empty node_id must raise InvalidNodeStateError."""
        with pytest.raises(InvalidNodeStateError, match="node_id must be a non-empty string"):
            Node(node_id="   ", node_type=NodeType.CORE)

    def test_invalid_parent_id_empty(self) -> None:
        """Empty string parent_id must raise InvalidNodeStateError."""
        with pytest.raises(InvalidNodeStateError, match="parent_id must be None or a non-empty string"):
            Node(node_id="AGG-01", node_type=NodeType.AGGREGATION, parent_id="  ")

    def test_node_equality_and_hash(self) -> None:
        n1 = Node("CORE-01", NodeType.CORE, None, NodeStatus.ONLINE)
        n2 = Node("CORE-01", NodeType.CORE, None, NodeStatus.ONLINE)
        n3 = Node("CORE-01", NodeType.CORE, None, NodeStatus.OFFLINE)
        assert n1 == n2
        assert n1 != n3
        assert hash(n1) == hash(n2)
