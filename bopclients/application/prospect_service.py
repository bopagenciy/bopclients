"""Prospect, CampaignProspect, Contact, Signal, and LeadScore application use cases."""

from typing import List, Optional
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.contact import Contact
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.prospect_source import ProspectSource
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.dtos import AddProspectCommand, RecordSignalCommand
from bopclients.application.interfaces.repositories import IProspectRepository
from bopclients.application.interfaces.forge_gateways import IForgeDiscoveryGateway, DiscoveryQuery


class ProspectService:
    """Use case handler for Prospecting operations with deterministic deduplication and campaign membership."""

    def __init__(
        self,
        prospect_repo: IProspectRepository,
        discovery_gateway: Optional[IForgeDiscoveryGateway] = None,
    ):
        self.prospect_repo = prospect_repo
        self.discovery_gateway = discovery_gateway

    def add_prospect(self, cmd: AddProspectCommand) -> Prospect:
        """Add or retrieve a prospect, deduplicating within the organization, and link to campaign if provided."""
        # 1. Deduplication check within the organization
        existing = self.prospect_repo.find_existing_prospect(
            cmd.organization_id,
            forge_record_id=cmd.forge_record_id,
            website_url=cmd.website_url,
        )

        if existing:
            prospect = existing
        else:
            prospect = Prospect(
                organization_id=cmd.organization_id,
                forge_record_id=cmd.forge_record_id,
                name=cmd.name,
                website_url=cmd.website_url,
                phone=cmd.phone,
                email=cmd.email,
                address=cmd.address,
                city=cmd.city,
                state=cmd.state,
                country=cmd.country,
                postal_code=cmd.postal_code,
                industry=cmd.industry,
                source=cmd.source,
            )
            prospect.validate()
            prospect = self.prospect_repo.save_prospect(cmd.organization_id, prospect)

            # Create source provenance record
            ps = ProspectSource(
                organization_id=cmd.organization_id,
                prospect_id=prospect.id,
                source_type=cmd.source,
                source_url=cmd.website_url,
                external_id=cmd.forge_record_id,
            )
            self.prospect_repo.add_prospect_source(cmd.organization_id, ps)

        # 2. If campaign_id provided, create CampaignProspect membership
        if cmd.campaign_id:
            cp = CampaignProspect(
                organization_id=cmd.organization_id,
                campaign_id=cmd.campaign_id,
                prospect_id=prospect.id,
                status="added",
            )
            cp.validate()
            self.prospect_repo.add_prospect_to_campaign(cmd.organization_id, cp)

        return prospect

    def discover_and_import(
        self,
        org_id: str,
        campaign_id: str,
        zip_code: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        industry: Optional[str] = None,
        limit: int = 100,
    ) -> List[Prospect]:
        """Discover businesses via FORGE Gateway and import them into BopClients tenant campaign with deduplication."""
        if not self.discovery_gateway:
            raise ValueError("Discovery gateway is not configured")

        query = DiscoveryQuery(
            zip_code=zip_code,
            city=city,
            state=state,
            industry=industry,
            limit=limit,
        )
        discovered = self.discovery_gateway.discover_businesses(query)

        imported: List[Prospect] = []
        for biz in discovered:
            cmd = AddProspectCommand(
                organization_id=org_id,
                campaign_id=campaign_id,
                forge_record_id=biz.overture_id,
                name=biz.name,
                website_url=biz.website_url,
                phone=biz.phone,
                address=biz.address,
                city=biz.city,
                state=biz.state,
                postal_code=biz.zip_code,
                industry=biz.forge_industry or biz.category,
                source="overture",
            )
            imported.append(self.add_prospect(cmd))
        return imported

    def record_signal(self, cmd: RecordSignalCommand) -> Signal:
        """Record a buying/opportunity signal on a prospect, validating tenant ownership."""
        prospect = self.prospect_repo.get_prospect_by_id(cmd.organization_id, cmd.prospect_id)
        if not prospect:
            raise TenantAccessError(
                f"Signal rejected: Prospect '{cmd.prospect_id}' not found in organization '{cmd.organization_id}'"
            )

        signal = Signal(
            organization_id=cmd.organization_id,
            prospect_id=cmd.prospect_id,
            type=cmd.signal_type,
            value=cmd.value,
            confidence=cmd.confidence,
            source=cmd.source,
        )
        signal.validate()
        return self.prospect_repo.add_signal(cmd.organization_id, signal)

    def assign_score(
        self, org_id: str, prospect_id: str, score: int, explanation: Optional[str] = None
    ) -> LeadScore:
        """Assign or update a Lead Score for a prospect, validating tenant ownership."""
        prospect = self.prospect_repo.get_prospect_by_id(org_id, prospect_id)
        if not prospect:
            raise TenantAccessError(
                f"LeadScore rejected: Prospect '{prospect_id}' not found in organization '{org_id}'"
            )

        lead_score = LeadScore(
            organization_id=org_id,
            prospect_id=prospect_id,
            score=score,
            explanation=explanation,
        )
        lead_score.validate()
        return self.prospect_repo.save_lead_score(org_id, lead_score)
