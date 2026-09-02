"""DTOs and capabilities structures for P7 Public Signal Monitoring."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.signal import Signal


@dataclass
class PublicSignalProviderCapabilities:
    """Declared capabilities for a public signal discovery provider."""

    supports_company_news: bool = False
    supports_jobs: bool = False
    supports_rfp: bool = False
    supports_press_releases: bool = False
    supports_website_change: bool = False
    supports_ads: bool = False
    requires_api_key: bool = False
    network_access: bool = True


@dataclass
class PublicSignalDiscoveryResult:
    """Standardized output from a public signal discovery provider run."""

    observations: List[PublicSignalObservation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    pages_scanned: int = 0
    queried_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ProspectSignalMonitorResult:
    """Summary of a signal monitoring execution run on a prospect or campaign."""

    prospect_id: str
    provider: str
    observations_found: int = 0
    observations_created: int = 0
    observations_reused: int = 0
    signals_activated: int = 0
    signals_updated: int = 0
    signals_expired: int = 0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SignalMonitorPlan:
    """Actionable monitoring plan recommendation for a prospect."""

    prospect_id: str
    provider_names: List[str] = field(default_factory=list)
    recommended_interval_days: int = 14
    signals_to_watch: List[str] = field(default_factory=list)
    reason: str = ""
