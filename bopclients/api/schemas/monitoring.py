"""Continuous monitoring schedule schemas."""

from typing import Optional, List
from pydantic import BaseModel, Field


class MonitoringScheduleUpdate(BaseModel):
    """Update continuous monitoring schedule configuration."""

    status: Optional[str] = Field(default=None, description="Schedule status: ACTIVE, PAUSED")
    recommended_interval_days: Optional[int] = Field(default=None, ge=1, le=365)


class MonitoringScheduleResponse(BaseModel):
    """Monitoring schedule status response."""

    id: str
    organization_id: str
    prospect_id: Optional[str] = None
    status: str
    display_key: str = Field(description="Localization display key for status")
    next_check_at: str
    last_check_at: Optional[str] = None
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    recommended_interval_days: int
    failure_count: int
    last_error: Optional[str] = None
