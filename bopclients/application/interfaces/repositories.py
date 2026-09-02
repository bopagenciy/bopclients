"""Abstract repository interfaces with tenant isolation contracts."""

from abc import ABC, abstractmethod
from typing import List, Optional, Any
from bopclients.domain.organization import Organization, OrganizationMember, OrganizationSettings
from bopclients.domain.user import User
from bopclients.domain.service import Service
from bopclients.domain.icp import IdealCustomerProfile
from bopclients.domain.campaign import Campaign
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.prospect import Prospect
from bopclients.domain.contact import Contact
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.prospect_source import ProspectSource
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.enrichment_result import EnrichmentResult


class IUserRepository(ABC):
    """Abstract repository for Users."""

    @abstractmethod
    def save(self, user: User) -> User: ...

    @abstractmethod
    def get_by_id(self, user_id: str) -> Optional[User]: ...

    @abstractmethod
    def get_by_email(self, email: str) -> Optional[User]: ...


class IOrganizationRepository(ABC):
    """Abstract repository for Organizations and Memberships."""

    @abstractmethod
    def save(self, org: Organization) -> Organization: ...

    @abstractmethod
    def get_by_id(self, org_id: str) -> Optional[Organization]: ...

    @abstractmethod
    def get_by_slug(self, slug: str) -> Optional[Organization]: ...

    @abstractmethod
    def add_member(self, member: OrganizationMember) -> OrganizationMember: ...

    @abstractmethod
    def get_members(self, org_id: str) -> List[OrganizationMember]: ...

    @abstractmethod
    def get_member(self, org_id: str, user_id: str) -> Optional[OrganizationMember]: ...


class IServiceRepository(ABC):
    """Abstract repository for Organization Services (Tenant Isolated)."""

    @abstractmethod
    def save(self, org_id: str, service: Service) -> Service: ...

    @abstractmethod
    def get_by_id(self, org_id: str, service_id: str) -> Optional[Service]: ...

    @abstractmethod
    def list_by_organization(self, org_id: str) -> List[Service]: ...


class IICPRepository(ABC):
    """Abstract repository for Ideal Customer Profiles (Tenant Isolated)."""

    @abstractmethod
    def save(self, org_id: str, icp: IdealCustomerProfile) -> IdealCustomerProfile: ...

    @abstractmethod
    def get_by_id(self, org_id: str, icp_id: str) -> Optional[IdealCustomerProfile]: ...

    @abstractmethod
    def list_by_organization(self, org_id: str) -> List[IdealCustomerProfile]: ...


class ICampaignRepository(ABC):
    """Abstract repository for Campaigns (Tenant Isolated)."""

    @abstractmethod
    def save(self, org_id: str, campaign: Campaign) -> Campaign: ...

    @abstractmethod
    def get_by_id(self, org_id: str, campaign_id: str) -> Optional[Campaign]: ...

    @abstractmethod
    def list_by_organization(self, org_id: str) -> List[Campaign]: ...


class IProspectRepository(ABC):
    """Abstract repository for Prospects, Campaign Memberships, Contacts, Signals, and Scores (Tenant Isolated)."""

    @abstractmethod
    def save_prospect(self, org_id: str, prospect: Prospect) -> Prospect: ...

    @abstractmethod
    def get_prospect_by_id(self, org_id: str, prospect_id: str) -> Optional[Prospect]: ...

    @abstractmethod
    def find_existing_prospect(
        self,
        org_id: str,
        forge_record_id: Optional[str] = None,
        website_url: Optional[str] = None,
        external_id: Optional[str] = None,
    ) -> Optional[Prospect]: ...

    @abstractmethod
    def add_prospect_to_campaign(
        self, org_id: str, campaign_prospect: CampaignProspect
    ) -> CampaignProspect: ...

    @abstractmethod
    def list_prospects_by_campaign(
        self, org_id: str, campaign_id: str, limit: int = 100, offset: int = 0
    ) -> List[Prospect]: ...

    @abstractmethod
    def list_prospect_campaigns(self, org_id: str, prospect_id: str) -> List[CampaignProspect]: ...

    @abstractmethod
    def add_contact(self, org_id: str, contact: Contact) -> Contact: ...

    @abstractmethod
    def list_contacts(self, org_id: str, prospect_id: str) -> List[Contact]: ...

    @abstractmethod
    def add_signal(self, org_id: str, signal: Signal) -> Signal: ...

    @abstractmethod
    def list_signals(self, org_id: str, prospect_id: str) -> List[Signal]: ...

    @abstractmethod
    def save_lead_score(self, org_id: str, score: LeadScore) -> LeadScore: ...

    @abstractmethod
    def get_lead_score(self, org_id: str, prospect_id: str) -> Optional[LeadScore]: ...

    @abstractmethod
    def add_prospect_source(self, org_id: str, source: ProspectSource) -> ProspectSource: ...

    @abstractmethod
    def list_prospect_sources(self, org_id: str, prospect_id: str) -> List[ProspectSource]: ...


class IResearchRunRepository(ABC):
    """Abstract repository for ResearchRun execution tracking (Tenant Isolated)."""

    @abstractmethod
    def save(self, org_id: str, run: ResearchRun) -> ResearchRun: ...

    @abstractmethod
    def get_by_id(self, org_id: str, run_id: str) -> Optional[ResearchRun]: ...

    @abstractmethod
    def update_status(
        self,
        org_id: str,
        run_id: str,
        status: str,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[ResearchRun]: ...

    @abstractmethod
    def list_by_organization(
        self,
        org_id: str,
        campaign_id: Optional[str] = None,
        prospect_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ResearchRun]: ...


class IEnrichmentResultRepository(ABC):
    """Abstract repository for latest enrichment result snapshots (Tenant Isolated)."""

    @abstractmethod
    def save(self, org_id: str, result: EnrichmentResult) -> EnrichmentResult: ...

    @abstractmethod
    def get_latest(
        self, org_id: str, prospect_id: str, provider: str = "forge"
    ) -> Optional[EnrichmentResult]: ...


class IProspectIntelligenceRepository(ABC):
    """Abstract repository for latest sales prospect intelligence snapshots (Tenant Isolated)."""

    @abstractmethod
    def save(
        self, org_id: str, intelligence: Any
    ) -> Any: ...

    @abstractmethod
    def get_latest(
        self, org_id: str, prospect_id: str, provider: str = "deterministic"
    ) -> Optional[Any]: ...
