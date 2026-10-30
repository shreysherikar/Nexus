"""Unit and integration tests for the Transport Network domain."""

import pytest

from nexus.topology import NodeStatus, NodeType, Topology, build_simulated_network
from nexus.transport import (
    DuplicateLinkError,
    InvalidEndpointError,
    InvalidLinkStateError,
    LinkNotFoundError,
    TransportLink,
    TransportNetwork,
    build_reference_transport_network,
)


class TestTransportLinkModel:
    """Tests for TransportLink dataclass construction, validation, and immutability."""

    def test_valid_link_creation(self) -> None:
        link = TransportLink(
            link_id="LINK-01",
            upstream_node_id="CORE-01",
            downstream_node_id="AGG-01",
            capacity_mbps=10000.0,
            latency_ms=1.5,
            status=NodeStatus.ONLINE,
        )
        assert link.link_id == "LINK-01"
        assert link.upstream_node_id == "CORE-01"
        assert link.downstream_node_id == "AGG-01"
        assert link.capacity_mbps == 10000.0
        assert link.latency_ms == 1.5
        assert link.status == NodeStatus.ONLINE

    def test_self_link_rejected(self) -> None:
        with pytest.raises(InvalidLinkStateError, match="cannot be a self-link"):
            TransportLink(
                link_id="LINK-01",
                upstream_node_id="CORE-01",
                downstream_node_id="CORE-01",
                capacity_mbps=1000.0,
                latency_ms=1.0,
            )

    @pytest.mark.parametrize("invalid_id", ["", "   ", None])
    def test_invalid_identifiers_rejected(self, invalid_id: object) -> None:
        with pytest.raises(InvalidLinkStateError):
            TransportLink(
                link_id=invalid_id,  # type: ignore[arg-type]
                upstream_node_id="CORE-01",
                downstream_node_id="AGG-01",
                capacity_mbps=1000.0,
                latency_ms=1.0,
            )

    @pytest.mark.parametrize("bad_val", [-1.0, 0.0, float("nan"), float("inf"), True, False, "1000"])
    def test_invalid_capacity_rejected(self, bad_val: object) -> None:
        with pytest.raises(InvalidLinkStateError):
            TransportLink(
                link_id="LINK-01",
                upstream_node_id="CORE-01",
                downstream_node_id="AGG-01",
                capacity_mbps=bad_val,  # type: ignore[arg-type]
                latency_ms=1.0,
            )

    @pytest.mark.parametrize("bad_lat", [-0.5, float("nan"), float("inf"), True, False, "1.0"])
    def test_invalid_latency_rejected(self, bad_lat: object) -> None:
        with pytest.raises(InvalidLinkStateError):
            TransportLink(
                link_id="LINK-01",
                upstream_node_id="CORE-01",
                downstream_node_id="AGG-01",
                capacity_mbps=1000.0,
                latency_ms=bad_lat,  # type: ignore[arg-type]
            )

    def test_status_coercion_and_validation(self) -> None:
        link = TransportLink("L1", "CORE-01", "AGG-01", 1000.0, 1.0, status="DEGRADED")  # type: ignore[arg-type]
        assert link.status == NodeStatus.DEGRADED

        with pytest.raises(InvalidLinkStateError, match="Invalid status"):
            TransportLink("L1", "CORE-01", "AGG-01", 1000.0, 1.0, status="DESTROYED")  # type: ignore[arg-type]


class TestTransportNetworkOperations:
    """Tests for TransportNetwork link registration, adjacency, and hierarchy invariants."""

    @pytest.fixture
    def net(self) -> Topology:
        return build_simulated_network()

    @pytest.fixture
    def transport(self, net: Topology) -> TransportNetwork:
        return build_reference_transport_network(net)

    def test_reference_transport_network_counts_and_endpoints(self, net: Topology, transport: TransportNetwork) -> None:
        """Reference transport network must have exactly 26 links matching all non-root hierarchy edges."""
        assert len(transport) == 26
        assert len(transport.all_links()) == 26

        # Check Core-Agg links
        core_agg1 = transport.get_link("LINK-CORE-AGG-01")
        assert core_agg1.upstream_node_id == "CORE-01"
        assert core_agg1.downstream_node_id == "AGG-01"
        assert core_agg1.capacity_mbps == 10000.0

        # Check Agg-Site links
        agg_site1 = transport.get_link("LINK-AGG-01-SITE-01")
        assert agg_site1.upstream_node_id == "AGG-01"
        assert agg_site1.downstream_node_id == "SITE-01"
        assert agg_site1.capacity_mbps == 2500.0

        # Check Site-Cell links
        site_cell1 = transport.get_link("LINK-SITE-01-CELL-01")
        assert site_cell1.upstream_node_id == "SITE-01"
        assert site_cell1.downstream_node_id == "CELL-01"
        assert site_cell1.capacity_mbps == 1000.0

    def test_duplicate_link_id_rejected(self, net: Topology, transport: TransportNetwork) -> None:
        with pytest.raises(DuplicateLinkError, match="already exists"):
            transport.add_link(
                TransportLink("LINK-CORE-AGG-01", "CORE-01", "AGG-01", 5000.0, 1.0)
            )

    def test_missing_endpoints_rejected(self, net: Topology) -> None:
        tn = TransportNetwork(topology=net)
        with pytest.raises(InvalidEndpointError, match="Upstream node 'UNKNOWN' does not exist"):
            tn.add_link(TransportLink("L1", "UNKNOWN", "AGG-01", 1000.0, 1.0))

        with pytest.raises(InvalidEndpointError, match="Downstream node 'UNKNOWN' does not exist"):
            tn.add_link(TransportLink("L2", "CORE-01", "UNKNOWN", 1000.0, 1.0))

    def test_invalid_hierarchy_endpoint_relationship_rejected(self, net: Topology) -> None:
        tn = TransportNetwork(topology=net)
        # Attempt to link CORE-01 directly to SITE-01 (skipping AGG-01)
        with pytest.raises(InvalidEndpointError, match="Invalid link hierarchy"):
            tn.add_link(TransportLink("L_SKIP", "CORE-01", "SITE-01", 1000.0, 1.0))

        # Attempt to reverse parent-child direction (upstream=AGG-01, downstream=CORE-01)
        with pytest.raises(InvalidEndpointError, match="Invalid link hierarchy"):
            tn.add_link(TransportLink("L_REV", "AGG-01", "CORE-01", 1000.0, 1.0))

    def test_get_links_for_node(self, transport: TransportNetwork) -> None:
        """CORE-01 should connect to 2 links (downlinks to AGG-01, AGG-02)."""
        core_links = transport.get_links_for_node("CORE-01")
        assert len(core_links) == 2
        assert {l.link_id for l in core_links} == {"LINK-CORE-AGG-01", "LINK-CORE-AGG-02"}

        # AGG-01 connects to 4 links (1 uplink from CORE, 3 downlinks to SITE-01..03)
        agg1_links = transport.get_links_for_node("AGG-01")
        assert len(agg1_links) == 4

        # SITE-01 connects to 4 links (1 uplink from AGG-01, 3 downlinks to CELL-01..03)
        site1_links = transport.get_links_for_node("SITE-01")
        assert len(site1_links) == 4

        # CELL-01 connects to 1 link (uplink from SITE-01)
        cell1_links = transport.get_links_for_node("CELL-01")
        assert len(cell1_links) == 1
        assert cell1_links[0].link_id == "LINK-SITE-01-CELL-01"

    def test_get_link_not_found(self, transport: TransportNetwork) -> None:
        with pytest.raises(LinkNotFoundError):
            transport.get_link("LINK-NON-EXISTENT")

    def test_get_links_for_unknown_node(self, transport: TransportNetwork) -> None:
        with pytest.raises(InvalidEndpointError):
            transport.get_links_for_node("UNKNOWN-NODE")

    def test_set_link_status_returns_updated_instance(self, transport: TransportNetwork) -> None:
        updated = transport.set_link_status("LINK-CORE-AGG-01", NodeStatus.OFFLINE)
        assert updated.status == NodeStatus.OFFLINE
        assert transport.get_link("LINK-CORE-AGG-01").status == NodeStatus.OFFLINE

        # Setting same status is a no-op
        same = transport.set_link_status("LINK-CORE-AGG-01", NodeStatus.OFFLINE)
        assert same == updated

    def test_set_link_status_string_coercion(self, transport: TransportNetwork) -> None:
        updated = transport.set_link_status("LINK-CORE-AGG-01", "DEGRADED")
        assert updated.status == NodeStatus.DEGRADED
        assert transport.get_link("LINK-CORE-AGG-01").status == NodeStatus.DEGRADED

    @pytest.mark.parametrize("bad_status", ["INVALID_STATUS", "BROKEN", "", 123, None, True])
    def test_set_link_status_invalid_raises_and_preserves_state(
        self, transport: TransportNetwork, bad_status: object
    ) -> None:
        original = transport.get_link("LINK-CORE-AGG-01")
        with pytest.raises(InvalidLinkStateError):
            transport.set_link_status("LINK-CORE-AGG-01", bad_status)  # type: ignore[arg-type]
        # Verify link in network remains untouched
        assert transport.get_link("LINK-CORE-AGG-01") == original

    def test_build_reference_transport_network_missing_root_rejected(self) -> None:
        empty_topo = Topology()
        with pytest.raises(InvalidEndpointError, match="Reference transport network requires root node 'CORE-01'"):
            build_reference_transport_network(empty_topo)

    def test_build_reference_transport_network_invalid_root_type_rejected(self) -> None:
        from nexus.topology.models import Node
        topo = Topology()
        topo.add_node(Node("OTHER-CORE", NodeType.CORE))
        topo.add_node(Node("CORE-01", NodeType.AGGREGATION, parent_id="OTHER-CORE"))
        with pytest.raises(InvalidEndpointError, match="Expected CORE-01 to have type CORE"):
            build_reference_transport_network(topo)
