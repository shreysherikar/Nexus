"""Transport network domain exceptions."""


class TransportError(Exception):
    """Base exception for transport network domain errors."""


class InvalidLinkStateError(TransportError, ValueError):
    """Raised when a TransportLink is configured with invalid state or bounds."""


class DuplicateLinkError(TransportError):
    """Raised when attempting to add a link with an ID that already exists."""


class LinkNotFoundError(TransportError):
    """Raised when a requested transport link does not exist."""


class InvalidEndpointError(TransportError, ValueError):
    """Raised when transport link endpoints violate network or hierarchy constraints."""
