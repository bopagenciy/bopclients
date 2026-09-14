"""Campaign schemas."""

from typing import Optional
from pydantic import BaseModel, Field


class CampaignCreate(BaseModel):
    """Campaign creation payload."""

    name: str = Field(description="Descriptive campaign name")
    description: Optional[str] = None
    icp_id: Optional[str] = Field(default=None, description="Associated ICP identifier")
    status: Optional[str] = Field(default="draft", description="Campaign lifecycle status")


class CampaignUpdate(BaseModel):
    """Campaign update payload."""

    name: Optional[str] = None
    description: Optional[str] = None
    icp_id: Optional[str] = None
    status: Optional[str] = None


class CampaignResponse(BaseModel):
    """Campaign entity response."""

    id: str
    organization_id: str
    icp_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    status: str
    display_key: str = Field(description="Localization display key for frontend translation")
    created_at: str
    updated_at: str
