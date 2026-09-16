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


class LastOwnerProtectionError(BopClientsDomainError):
    """Raised when an action would leave the organization without an owner."""


class InvalidRoleTransitionError(BopClientsDomainError):
    """Raised when a requested role transition is invalid."""


class SearchIntentError(BopClientsDomainError):
    """Raised when search intent parsing fails."""


class SearchPlanningError(BopClientsDomainError):
    """Raised when search planning fails."""


class LocationResolutionError(BopClientsDomainError):
    """Raised when location resolution fails or is unsupported."""


class DiscoveryProviderError(BopClientsDomainError):
    """Raised when a discovery provider fails."""


class DiscoveryExecutionError(BopClientsDomainError):
    """Raised when discovery execution fails."""


class AIResearchError(BopClientsDomainError):
    """Base exception for AI Research provider errors."""


class AIConfigurationError(AIResearchError):
    """Raised when AI provider configuration or API key is missing."""


class AIAuthenticationError(AIResearchError):
    """Raised when AI provider authentication fails (e.g. 401)."""


class AIRateLimitError(AIResearchError):
    """Raised when AI provider rate limit is exceeded (e.g. 429)."""


class AITimeoutError(AIResearchError):
    """Raised when AI provider request times out."""


class AIProviderError(AIResearchError):
    """Raised when AI provider returns a server error (e.g. 5xx)."""


class AIResponseValidationError(AIResearchError):
    """Raised when AI provider response fails JSON or schema validation."""


class InvitationNotFoundError(EntityNotFoundError):
    """Raised when an invitation is not found by ID or token hash."""


class InvitationExpiredError(BopClientsDomainError):
    """Raised when attempting to accept or interact with an expired invitation."""


class InvitationAlreadyAcceptedError(BopClientsDomainError):
    """Raised when an invitation has already been accepted."""


class InvitationRevokedError(BopClientsDomainError):
    """Raised when an invitation has been revoked."""


class AlreadyOrganizationMemberError(BopClientsDomainError):
    """Raised when attempting to invite or accept for a user already in the organization."""


class DuplicateInvitationError(BopClientsDomainError):
    """Raised when an active pending invitation already exists for the email and organization."""


class InvitationEmailMismatchError(BopClientsDomainError):
    """Raised when accepting user's email does not match the invitation email."""
