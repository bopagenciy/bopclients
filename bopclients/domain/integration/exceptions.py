"""Domain exceptions for Bop Platform integration events and contracts."""


class IntegrationError(Exception):
    """Base exception for all Bop Platform integration errors."""


class InvalidEntityRef(IntegrationError):
    """Raised when a BopEntityRef contains invalid, missing, or malformed fields."""


class InvalidIntegrationEvent(IntegrationError):
    """Raised when an integration event fails structural, type, or contract validation."""


class CrossTenantIntegrationEvent(InvalidIntegrationEvent):
    """Raised when an event envelope tenant does not match the subject tenant."""


class UnsupportedEventVersion(IntegrationError):
    """Raised when an event version is unsupported or unrecognized by the domain registry."""


class DuplicateIntegrationEvent(IntegrationError):
    """Raised when an event with identical event_id has already been registered or stored."""


class UnknownLocalTenantIntegrationError(InvalidIntegrationEvent):
    """Raised when a local outbound event is staged for an unprovisioned or unknown local tenant."""
