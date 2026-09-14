"""Signal schemas with canonical taxonomy and localization display keys."""

from typing import Optional
from pydantic import BaseModel, Field


class SignalResponse(BaseModel):
    """Detected public or private signal response."""

    id: str
    prospect_id: str
    category: str = Field(description="Canonical signal category: NEED, COMPANY_ACTIVITY, BUYING_INTENT")
    display_key: str = Field(description="Localization display key for category translation")
    signal_type: str
    confidence: float
    headline: str
    summary: Optional[str] = None
    source_url: Optional[str] = None
    detected_at: str
    created_at: str
