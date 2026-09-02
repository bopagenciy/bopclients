"""Ideal Customer Profile (ICP) application use cases."""

from typing import List, Optional
from bopclients.domain.icp import IdealCustomerProfile, TargetMarket
from bopclients.application.dtos import CreateICPCommand
from bopclients.application.interfaces.repositories import IICPRepository


class ICPService:
    """Use case handler for Ideal Customer Profiles."""

    def __init__(self, icp_repo: IICPRepository):
        self.icp_repo = icp_repo

    def create_icp(self, cmd: CreateICPCommand) -> IdealCustomerProfile:
        """Create a new Ideal Customer Profile for an organization."""
        icp = IdealCustomerProfile(
            organization_id=cmd.organization_id,
            name=cmd.name,
            description=cmd.description,
            industries=cmd.industries,
            company_sizes=cmd.company_sizes,
            decision_maker_roles=cmd.decision_maker_roles,
            pain_points=cmd.pain_points,
            desired_signals=cmd.desired_signals,
            excluded_signals=cmd.excluded_signals,
            countries=cmd.countries,
            languages=cmd.languages,
        )
        icp.validate()
        return self.icp_repo.save(cmd.organization_id, icp)

    def list_icps(self, org_id: str) -> List[IdealCustomerProfile]:
        """List all ICPs for an organization."""
        return self.icp_repo.list_by_organization(org_id)
