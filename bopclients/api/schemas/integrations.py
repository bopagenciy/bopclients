"""Integration outbox delivery and destination administrative schemas."""

from typing import Optional, Dict
from pydantic import BaseModel, Field


class DestinationCreate(BaseModel):
    """Register external webhook or platform integration destination."""

    target_app_id: str = Field(description="Target system routing key (e.g. bopcrm, hubspot, webhook)")
    destination_name: str = Field(description="Human-readable destination name")
    transport_type: str = Field(default="HTTP", description="Transport mechanism: HTTP")
    endpoint_url: str = Field(description="Destination endpoint HTTPS URL")
    secret_key_ref: Optional[str] = Field(default=None, description="Namespaced environment secret reference (e.g. BOP_INTEGRATION_SECRET_XYZ)")
    headers_template: Optional[Dict[str, str]] = Field(default=None, description="Custom HTTP headers template")


class DestinationUpdate(BaseModel):
    """Update destination settings or soft deactivation."""

    destination_name: Optional[str] = None
    endpoint_url: Optional[str] = None
    secret_key_ref: Optional[str] = None
    is_active: Optional[bool] = None
    headers_template: Optional[Dict[str, str]] = None


class DestinationResponse(BaseModel):
    """Destination metadata response. Strictly conceals raw secret values."""

    id: str
    bop_organization_id: str
    target_app_id: str
    destination_name: str
    transport_type: str
    endpoint_url: str
    secret_key_ref: Optional[str] = None
    is_active: bool
    created_at: str
    updated_at: str


class DeliveryResponse(BaseModel):
    """Outbox delivery status response."""

    id: str
    event_id: str
    destination_id: str
    bop_organization_id: str
    status: str
    display_key: str = Field(description="Localization display key for status")
    attempt_count: int
    max_attempts: int
    next_attempt_at: str
    delivered_at: Optional[str] = None
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    created_at: str
