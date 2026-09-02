"""Domain exceptions for BopClients."""


class BopClientsDomainError(Exception):
    """Base exception for BopClients domain errors."""


class TenantAccessError(BopClientsDomainError):
    """Raised when tenant boundary is violated or tenant ID is missing."""


class EntityNotFoundError(BopClientsDomainError):
    """Raised when a requested domain entity is not found within tenant scope."""


class ValidationError(BopClientsDomainError):
    """Raised when entity validation rules fail."""


class MemberRolePermissionError(BopClientsDomainError):
    """Raised when an operation is prohibited for the user's role in the organization."""
