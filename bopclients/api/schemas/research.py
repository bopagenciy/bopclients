"""Prospect research orchestration schemas."""

from typing import Optional
from pydantic import BaseModel, Field


class ResearchTriggerRequest(BaseModel):
    """Trigger background research run for a prospect."""

    campaign_id: Optional[str] = Field(default=None, description="Optional associated campaign ID")
    run_type: str = Field(default="full_diligence", description="Research run type")


class ResearchRunResponse(BaseModel):
    """Research run status response."""

    id: str
    organization_id: str
    prospect_id: Optional[str] = None
    campaign_id: Optional[str] = None
    run_type: str
    status: str = Field(description="Execution status: pending, in_progress, completed, failed")
    display_key: str = Field(description="Localization display key for status")
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
