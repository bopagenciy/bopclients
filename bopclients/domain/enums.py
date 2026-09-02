"""Domain enumerations for BopClients multi-tenant SaaS platform."""

from enum import Enum


class MemberRole(str, Enum):
    """User roles within an organization."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class CampaignStatus(str, Enum):
    """Lifecycle status of a prospecting campaign."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ServiceCategory(str, Enum):
    """Categories of services offered by an organization."""

    MARKETING = "marketing"
    DESIGN = "design"
    WEB_DEVELOPMENT = "web_development"
    AI_AUTOMATION = "ai_automation"
    LEGAL = "legal"
    CONSULTING = "consulting"
    HEALTHCARE = "healthcare"
    FINANCE = "finance"
    OTHER = "other"


class SignalType(str, Enum):
    """Buying signals and opportunity indicators detected on prospects."""

    WEBSITE_SLOW = "website_slow"
    NO_CHATBOT = "no_chatbot"
    NO_BOOKING = "no_booking"
    OLD_WEBSITE = "old_website"
    HIRING_MARKETING = "hiring_marketing"
    ACTIVE_ADS = "active_ads"
    NEW_LOCATION = "new_location"
    POOR_REVIEWS = "poor_reviews"
    HIGH_SOCIAL_ACTIVITY = "high_social_activity"
    CUSTOM = "custom"


class ProspectSourceType(str, Enum):
    """Traceability source types for discovered prospect leads."""

    OVERTURE = "overture"
    GOOGLE = "google"
    GOOGLE_MAPS = "google_maps"
    WEBSITE = "website"
    LINKEDIN = "linkedin"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    DIRECTORY = "directory"
    MANUAL = "manual"
