"""Campaign application use cases."""

from typing import List, Optional
from bopclients.domain.campaign import Campaign
from bopclients.domain.enums import CampaignStatus
from bopclients.application.dtos import CreateCampaignCommand
from bopclients.application.interfaces.repositories import ICampaignRepository


from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.interfaces.repositories import ICampaignRepository, IICPRepository


class CampaignService:
    """Use case handler for Campaigns."""

    def __init__(self, campaign_repo: ICampaignRepository, icp_repo: Optional[IICPRepository] = None):
        self.campaign_repo = campaign_repo
        self.icp_repo = icp_repo

    def create_campaign(self, cmd: CreateCampaignCommand) -> Campaign:
        """Create a new prospecting campaign for an organization, validating ICP tenant ownership."""
        if cmd.icp_id and self.icp_repo:
            icp = self.icp_repo.get_by_id(cmd.organization_id, cmd.icp_id)
            if not icp:
                raise TenantAccessError(
                    f"Campaign creation failed: ICP '{cmd.icp_id}' does not belong to organization '{cmd.organization_id}'"
                )

        campaign = Campaign(
            organization_id=cmd.organization_id,
            icp_id=cmd.icp_id,
            name=cmd.name,
            description=cmd.description,
            status=CampaignStatus.DRAFT,
        )
        campaign.validate()
        return self.campaign_repo.save(cmd.organization_id, campaign)

    def list_campaigns(self, org_id: str) -> List[Campaign]:
        """List all campaigns for an organization."""
        return self.campaign_repo.list_by_organization(org_id)
