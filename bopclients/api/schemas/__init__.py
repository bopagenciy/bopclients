"""API request and response schemas."""

from bopclients.api.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    UserResponse,
    UserPreferencesUpdate,
    UserOrganizationItem,
    UserOrganizationsResponse,
)
from bopclients.api.schemas.organizations import (
    OrganizationResponse,
    OrganizationUpdate,
    MemberResponse,
    MemberCreateRequest,
    MemberRoleUpdate,
)
from bopclients.api.schemas.campaigns import (
    CampaignCreate,
    CampaignUpdate,
    CampaignResponse,
)
from bopclients.api.schemas.icps import (
    ICPCreate,
    ICPUpdate,
    ICPResponse,
    TargetMarketCreate,
    TargetMarketUpdate,
    TargetMarketResponse,
)
from bopclients.api.schemas.prospects import (
    ProspectFilterParams,
    ProspectUpdate,
    ProspectResponse,
    ProspectDetailResponse,
)
from bopclients.api.schemas.signals import SignalResponse
from bopclients.api.schemas.research import ResearchTriggerRequest, ResearchRunResponse
from bopclients.api.schemas.monitoring import MonitoringScheduleResponse, MonitoringScheduleUpdate
from bopclients.api.schemas.integrations import (
    DestinationCreate,
    DestinationUpdate,
    DestinationResponse,
    DeliveryResponse,
)

__all__ = [
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "UserResponse",
    "UserPreferencesUpdate",
    "UserOrganizationItem",
    "UserOrganizationsResponse",
    "OrganizationResponse",
    "OrganizationUpdate",
    "MemberResponse",
    "MemberCreateRequest",
    "MemberRoleUpdate",
    "CampaignCreate",
    "CampaignUpdate",
    "CampaignResponse",
    "ICPCreate",
    "ICPUpdate",
    "ICPResponse",
    "TargetMarketCreate",
    "TargetMarketUpdate",
    "TargetMarketResponse",
    "ProspectFilterParams",
    "ProspectUpdate",
    "ProspectResponse",
    "ProspectDetailResponse",
    "SignalResponse",
    "ResearchTriggerRequest",
    "ResearchRunResponse",
    "MonitoringScheduleResponse",
    "MonitoringScheduleUpdate",
    "DestinationCreate",
    "DestinationUpdate",
    "DestinationResponse",
    "DeliveryResponse",
]
