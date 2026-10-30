"""Transport network link domain models."""

from dataclasses import dataclass
import math
from typing import Any

from nexus.topology.enums import NodeStatus
from nexus.transport.exceptions import InvalidLinkStateError


def _validate_link_number(name: str, val: Any, min_val: float) -> float:
    """Validate that val is a finite real number (not bool, NaN, or inf) >= min_val."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise InvalidLinkStateError(f"{name} must be a numeric value, got {type(val).__name__}")
    f_val = float(val)
    if not math.isfinite(f_val):
        raise InvalidLinkStateError(f"{name} must be a finite number, got {f_val}")
    if f_val < min_val:
        raise InvalidLinkStateError(f"{name} ({f_val}) cannot be less than {min_val}")
    return f_val


def coerce_link_status(status: Any) -> NodeStatus:
    """Validate and coerce a status value to NodeStatus enum, raising InvalidLinkStateError on failure."""
    if isinstance(status, NodeStatus):
        return status
    try:
        return NodeStatus(status)
    except (ValueError, TypeError) as exc:
        raise InvalidLinkStateError(
            f"Invalid status '{status}'. Expected one of: "
            f"{', '.join(s.value for s in NodeStatus)}"
        ) from exc


@dataclass(frozen=True)
class TransportLink:
    """Represents an immutable point-to-point physical or logical transport link.

    Links in this milestone are bidirectional for traffic. Upstream and downstream
    labels define hierarchical direction and failure impact propagation.

    Attributes:
        link_id: Unique string identifier for the transport link (e.g. 'LINK-CORE-AGG-01').
        upstream_node_id: Parent / upstream endpoint identifier.
        downstream_node_id: Child / downstream endpoint identifier.
        capacity_mbps: Configured link bandwidth capacity in Mbps (> 0.0).
        latency_ms: Base propagation latency in milliseconds (>= 0.0).
        status: Operational status of the link (ONLINE, OFFLINE, DEGRADED, MAINTENANCE).
    """

    link_id: str
    upstream_node_id: str
    downstream_node_id: str
    capacity_mbps: float
    latency_ms: float
    status: NodeStatus = NodeStatus.ONLINE

    def __post_init__(self) -> None:
        if not isinstance(self.link_id, str) or not self.link_id.strip():
            raise InvalidLinkStateError("link_id must be a non-empty string")

        if not isinstance(self.upstream_node_id, str) or not self.upstream_node_id.strip():
            raise InvalidLinkStateError("upstream_node_id must be a non-empty string")

        if not isinstance(self.downstream_node_id, str) or not self.downstream_node_id.strip():
            raise InvalidLinkStateError("downstream_node_id must be a non-empty string")

        if self.upstream_node_id == self.downstream_node_id:
            raise InvalidLinkStateError(
                f"TransportLink cannot be a self-link between identical endpoints: '{self.upstream_node_id}'"
            )

        cap_v = _validate_link_number("capacity_mbps", self.capacity_mbps, min_val=0.001)
        lat_v = _validate_link_number("latency_ms", self.latency_ms, min_val=0.0)

        object.__setattr__(self, "capacity_mbps", cap_v)
        object.__setattr__(self, "latency_ms", lat_v)

        coerced_status = coerce_link_status(self.status)
        object.__setattr__(self, "status", coerced_status)
