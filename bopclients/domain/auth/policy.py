"""Role-Based Access Control (RBAC) policy and permission evaluation engine."""

from enum import Enum
from typing import Set, Dict, Union
from bopclients.domain.enums import MemberRole
from bopclients.domain.exceptions import MemberRolePermissionError


class Permission(str, Enum):
    """Fine-grained permission actions in BopClients product API."""

    ORGANIZATION_READ = "organization.read"
    ORGANIZATION_MANAGE = "organization.manage"
    MEMBERS_READ = "members.read"
    MEMBERS_MANAGE = "members.manage"

    CAMPAIGN_READ = "campaign.read"
    CAMPAIGN_CREATE = "campaign.create"
    CAMPAIGN_UPDATE = "campaign.update"
    CAMPAIGN_DELETE = "campaign.delete"

    ICP_READ = "icp.read"
    ICP_MANAGE = "icp.manage"

    PROSPECT_READ = "prospect.read"
    PROSPECT_UPDATE = "prospect.update"

    SIGNALS_READ = "signals.read"
    RESEARCH_RUN = "research.run"

    MONITORING_READ = "monitoring.read"
    MONITORING_MANAGE = "monitoring.manage"

    INTEGRATION_READ = "integration.read"
    INTEGRATION_MANAGE = "integration.manage"

    ORGANIZATION_DELETE = "organization.delete"
    OWNER_TRANSFER = "owner.transfer"


# Role to Permission Matrix
ROLE_PERMISSIONS: Dict[MemberRole, Set[Permission]] = {
    MemberRole.VIEWER: {
        Permission.ORGANIZATION_READ,
        Permission.MEMBERS_READ,
        Permission.CAMPAIGN_READ,
        Permission.ICP_READ,
        Permission.PROSPECT_READ,
        Permission.SIGNALS_READ,
        Permission.MONITORING_READ,
    },
    MemberRole.MEMBER: {
        # All viewer permissions plus operational mutations
        Permission.ORGANIZATION_READ,
        Permission.MEMBERS_READ,
        Permission.CAMPAIGN_READ,
        Permission.CAMPAIGN_CREATE,
        Permission.CAMPAIGN_UPDATE,
        Permission.ICP_READ,
        Permission.ICP_MANAGE,
        Permission.PROSPECT_READ,
        Permission.PROSPECT_UPDATE,
        Permission.SIGNALS_READ,
        Permission.RESEARCH_RUN,
        Permission.MONITORING_READ,
        Permission.MONITORING_MANAGE,
    },
    MemberRole.ADMIN: {
        # All member permissions plus campaign deletion, member management, and integration admin
        Permission.ORGANIZATION_READ,
        Permission.ORGANIZATION_MANAGE,
        Permission.MEMBERS_READ,
        Permission.MEMBERS_MANAGE,
        Permission.CAMPAIGN_READ,
        Permission.CAMPAIGN_CREATE,
        Permission.CAMPAIGN_UPDATE,
        Permission.CAMPAIGN_DELETE,
        Permission.ICP_READ,
        Permission.ICP_MANAGE,
        Permission.PROSPECT_READ,
        Permission.PROSPECT_UPDATE,
        Permission.SIGNALS_READ,
        Permission.RESEARCH_RUN,
        Permission.MONITORING_READ,
        Permission.MONITORING_MANAGE,
        Permission.INTEGRATION_READ,
        Permission.INTEGRATION_MANAGE,
    },
    MemberRole.OWNER: {
        # Full tenant control
        perm for perm in Permission
    },
}


class AuthorizationPolicy:
    """Policy evaluator verifying role capabilities."""

    @staticmethod
    def normalize_role(role: Union[MemberRole, str]) -> MemberRole:
        """Normalize string or enum to canonical MemberRole."""
        if isinstance(role, MemberRole):
            return role
        role_str = str(role).strip().lower()
        try:
            return MemberRole(role_str)
        except ValueError:
            raise MemberRolePermissionError(f"Unknown organization member role: '{role}'")

    @classmethod
    def has_permission(cls, role: Union[MemberRole, str], permission: Union[Permission, str]) -> bool:
        """Check if role grants the requested permission."""
        try:
            normalized_role = cls.normalize_role(role)
        except MemberRolePermissionError:
            return False
        try:
            perm = Permission(permission) if not isinstance(permission, Permission) else permission
        except ValueError:
            return False
        allowed = ROLE_PERMISSIONS.get(normalized_role, set())
        return perm in allowed

    @classmethod
    def enforce(cls, role: Union[MemberRole, str], permission: Union[Permission, str], context_message: str = "") -> None:
        """Enforce permission check, raising MemberRolePermissionError if denied."""
        if not cls.has_permission(role, permission):
            perm_name = permission.value if isinstance(permission, Permission) else str(permission)
            role_name = cls.normalize_role(role).value.upper()
            detail = f" ({context_message})" if context_message else ""
            raise MemberRolePermissionError(
                f"Role '{role_name}' lacks required permission '{perm_name}'{detail}"
            )


PolicyEngine = AuthorizationPolicy
