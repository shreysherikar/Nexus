"""Transport network container and adjacency management."""

from dataclasses import replace
from typing import Any, Iterator, Optional

from nexus.topology.enums import NodeStatus
from nexus.topology.topology import Topology
from nexus.transport.exceptions import (
    DuplicateLinkError,
    InvalidEndpointError,
    LinkNotFoundError,
)
from nexus.transport.models import TransportLink, coerce_link_status


class TransportNetwork:
    """Manages a collection of transport links mapped over a validated network topology.

    Invariants:
    - Endpoints must exist in the underlying topology.
    - Upstream node must be the immediate parent of the downstream node.
    - Each link has a unique link_id.
    - Direct access and bidirectional link indexing per node.
    """

    def __init__(self, topology: Topology) -> None:
        self._topology = topology
        self._links: dict[str, TransportLink] = {}
        # node_id -> list of link_ids connected to this node
        self._node_links: dict[str, list[str]] = {}

    @property
    def topology(self) -> Topology:
        """Return the underlying topology."""
        return self._topology

    def add_link(self, link: TransportLink) -> None:
        """Add a transport link to the network, validating topology and endpoint hierarchy.

        Args:
            link: The TransportLink instance to register.

        Raises:
            DuplicateLinkError: If link_id already exists.
            InvalidEndpointError: If endpoints do not exist or do not have a parent-child relationship.
        """
        if link.link_id in self._links:
            raise DuplicateLinkError(f"Transport link '{link.link_id}' already exists")

        # Validate endpoint existence in topology
        if not self._topology.has_node(link.upstream_node_id):
            raise InvalidEndpointError(
                f"Upstream node '{link.upstream_node_id}' does not exist in topology"
            )
        if not self._topology.has_node(link.downstream_node_id):
            raise InvalidEndpointError(
                f"Downstream node '{link.downstream_node_id}' does not exist in topology"
            )

        # In this milestone, each link connects a direct parent to its child
        downstream_node = self._topology.get_node(link.downstream_node_id)
        if downstream_node.parent_id != link.upstream_node_id:
            raise InvalidEndpointError(
                f"Invalid link hierarchy: '{link.upstream_node_id}' is not the direct parent "
                f"of '{link.downstream_node_id}' (actual parent: {downstream_node.parent_id!r})"
            )

        self._links[link.link_id] = link
        self._node_links.setdefault(link.upstream_node_id, []).append(link.link_id)
        self._node_links.setdefault(link.downstream_node_id, []).append(link.link_id)

    def get_link(self, link_id: str) -> TransportLink:
        """Retrieve a transport link by its identifier."""
        if link_id not in self._links:
            raise LinkNotFoundError(f"Transport link '{link_id}' does not exist")
        return self._links[link_id]

    def has_link(self, link_id: str) -> bool:
        """Check whether a link identifier exists in the transport network."""
        return link_id in self._links

    def all_links(self) -> list[TransportLink]:
        """Return a defensive copy of all registered transport links."""
        return list(self._links.values())

    def get_links_for_node(self, node_id: str) -> list[TransportLink]:
        """Return all transport links connected to a specific node (either upstream or downstream)."""
        if not self._topology.has_node(node_id):
            raise InvalidEndpointError(f"Node '{node_id}' does not exist in topology")
        link_ids = self._node_links.get(node_id, [])
        return [self._links[lid] for lid in link_ids]

    def get_link_between(self, upstream_node_id: str, downstream_node_id: str) -> Optional[TransportLink]:
        """Find a transport link between specific upstream and downstream endpoints."""
        for link in self._links.values():
            if link.upstream_node_id == upstream_node_id and link.downstream_node_id == downstream_node_id:
                return link
        return None

    def set_link_status(self, link_id: str, status: Any) -> TransportLink:
        """Update operational status of a transport link, returning updated immutable instance.

        Raises:
            LinkNotFoundError: If link_id does not exist.
            InvalidLinkStateError: If status is not a valid NodeStatus or convertible string.
        """
        link = self.get_link(link_id)
        coerced_status = coerce_link_status(status)

        if link.status == coerced_status:
            return link
        updated = replace(link, status=coerced_status)
        self._links[link_id] = updated
        return updated

    def __len__(self) -> int:
        return len(self._links)

    def __contains__(self, link_id: str) -> bool:
        return link_id in self._links

    def __iter__(self) -> Iterator[TransportLink]:
        return iter(self._links.values())
