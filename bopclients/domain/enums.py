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


class SignalCategory(str, Enum):
    """Classification taxonomy for detected signals."""

    NEED = "need"
    BUYING_INTENT = "buying_intent"
    COMPANY_ACTIVITY = "company_activity"
    DATA_QUALITY = "data_quality"


class IntentStrength(str, Enum):
    """Buying intent strength level."""

    NONE = "none"
    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"


class SignalType(str, Enum):
    """Buying signals and opportunity indicators detected on prospects."""

    # Need signals
    WEBSITE_SLOW = "website_slow"
    NO_CHATBOT = "no_chatbot"
    NO_BOOKING = "no_booking"
    OLD_WEBSITE = "old_website"
    NO_ANALYTICS = "no_analytics"
    NO_SSL = "no_ssl"

    # Buying / Intent signals
    HIRING_MARKETING = "hiring_marketing"
    HIRING_SALES = "hiring_sales"
    OPENED_NEW_LOCATION = "opened_new_location"
    NEW_FUNDING = "new_funding"
    WEBSITE_RELAUNCH = "website_relaunch"
    NEW_SERVICE_LAUNCH = "new_service_launch"
    ACTIVE_ADS = "active_ads"
    VENDOR_SEARCH = "vendor_search"
    PUBLIC_REQUEST_FOR_PROPOSAL = "public_request_for_proposal"

    # Company activity signals
    RECENT_NEWS = "recent_news"
    LOCATION_EXPANSION = "location_expansion"
    LEADERSHIP_CHANGE = "leadership_change"
    TECHNOLOGY_CHANGE = "technology_change"
    RECENT_WEBSITE_CHANGE = "recent_website_change"
    NEW_CONTACT_FOUND = "new_contact_found"
    NEW_SIGNAL_DETECTED = "new_signal_detected"

    # Data quality signals
    SCRAPE_TIMEOUT = "scrape_timeout"
    LIMITED_SOURCE_COVERAGE = "limited_source_coverage"
    STALE_RESEARCH = "stale_research"

    # Other
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
