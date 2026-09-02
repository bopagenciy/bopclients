"""Database repository for Campaigns (Tenant Isolated)."""

from typing import List, Optional
from bopclients.domain.campaign import Campaign
from bopclients.domain.enums import CampaignStatus
from bopclients.application.interfaces.repositories import ICampaignRepository
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class CampaignRepository(BaseTenantRepository, ICampaignRepository):
    """Repository for managing tenant Campaigns."""

    def save(self, org_id: str, campaign: Campaign) -> Campaign:
        org_id = self._validate_tenant(org_id)
        campaign.organization_id = org_id
        p = self._placeholder()
        status_str = campaign.status.value if isinstance(campaign.status, CampaignStatus) else str(campaign.status)
        sql = f"""
        INSERT INTO campaigns (id, organization_id, icp_id, name, description, status, created_at, updated_at)
        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        self.db.execute(
            sql,
            (
                campaign.id,
                org_id,
                campaign.icp_id,
                campaign.name,
                campaign.description,
                status_str,
                campaign.created_at,
                campaign.updated_at,
            ),
        )
        self.db.commit()
        return campaign

    def get_by_id(self, org_id: str, campaign_id: str) -> Optional[Campaign]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM campaigns WHERE organization_id = {p} AND id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id, campaign_id))
        if not rows:
            return None
        r = rows[0]
        return Campaign(
            id=r["id"],
            organization_id=r["organization_id"],
            icp_id=r.get("icp_id"),
            name=r["name"],
            description=r.get("description"),
            status=CampaignStatus(r["status"]),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )

    def list_by_organization(self, org_id: str) -> List[Campaign]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM campaigns WHERE organization_id = {p} ORDER BY created_at DESC"
        rows = self.db.fetch_dicts(sql, (org_id,))
        res = []
        for r in rows:
            res.append(
                Campaign(
                    id=r["id"],
                    organization_id=r["organization_id"],
                    icp_id=r.get("icp_id"),
                    name=r["name"],
                    description=r.get("description"),
                    status=CampaignStatus(r["status"]),
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
            )
        return res
