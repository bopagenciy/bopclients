"""Ideal Customer Profile (ICP) and Target Market schemas."""

from typing import List, Optional
from pydantic import BaseModel, Field


class TargetMarketCreate(BaseModel):
    """Target market creation schema."""

    icp_id: Optional[str] = None
    country: str = "US"
    region: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    radius_miles: Optional[int] = None
    language: str = "en"


class TargetMarketUpdate(BaseModel):
    """Target market update schema."""

    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    radius_miles: Optional[int] = None
    language: Optional[str] = None


class TargetMarketResponse(BaseModel):
    """Target market response schema."""

    id: str
    icp_id: Optional[str] = None
    country: str
    region: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    radius_miles: Optional[int] = None
    language: str


class ICPCreate(BaseModel):
    """Ideal Customer Profile creation schema."""

    name: str = Field(description="Profile name")
    description: Optional[str] = None
    industries: List[str] = Field(default_factory=list)
    company_sizes: List[str] = Field(default_factory=list)
    decision_maker_roles: List[str] = Field(default_factory=list)
    pain_points: List[str] = Field(default_factory=list)
    desired_signals: List[str] = Field(default_factory=list)
    excluded_signals: List[str] = Field(default_factory=list)
    countries: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    target_markets: List[TargetMarketCreate] = Field(default_factory=list)


class ICPUpdate(BaseModel):
    """Ideal Customer Profile update schema."""

    name: Optional[str] = None
    description: Optional[str] = None
    industries: Optional[List[str]] = None
    company_sizes: Optional[List[str]] = None
    decision_maker_roles: Optional[List[str]] = None
    pain_points: Optional[List[str]] = None
    desired_signals: Optional[List[str]] = None
    excluded_signals: Optional[List[str]] = None
    countries: Optional[List[str]] = None
    languages: Optional[List[str]] = None


class ICPResponse(BaseModel):
    """Ideal Customer Profile response schema."""

    id: str
    organization_id: str
    name: str
    description: Optional[str] = None
    industries: List[str]
    company_sizes: List[str]
    decision_maker_roles: List[str]
    pain_points: List[str]
    desired_signals: List[str]
    excluded_signals: List[str]
    countries: List[str]
    languages: List[str]
    target_markets: List[TargetMarketResponse] = Field(default_factory=list)
    created_at: str
