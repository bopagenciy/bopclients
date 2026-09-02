"""Unit tests for BopClients Application Use Cases with deduplication and CampaignProspect normalization."""

import pytest
from bopclients.domain.enums import MemberRole, CampaignStatus, ServiceCategory, SignalType
from bopclients.domain.exceptions import TenantAccessError
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.application.dtos import (
    CreateOrganizationCommand,
    CreateServiceCommand,
    CreateICPCommand,
    CreateCampaignCommand,
    AddProspectCommand,
    RecordSignalCommand,
)
from bopclients.application.organization_service import OrganizationService
from bopclients.application.icp_service import ICPService
from bopclients.application.campaign_service import CampaignService
from bopclients.application.prospect_service import ProspectService
from bopclients.infrastructure.db.migrations import run_p1_migrations
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository, UserRepository
from bopclients.infrastructure.repositories.service_repository import ServiceRepository
from bopclients.infrastructure.repositories.icp_repository import ICPRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


@pytest.fixture
def memory_db():
    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)
    return db


class TestApplicationUseCases:
    def test_create_organization_flow(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        user_repo = UserRepository(memory_db)
        service_repo = ServiceRepository(memory_db)
        org_service = OrganizationService(org_repo, user_repo, service_repo)

        cmd = CreateOrganizationCommand(
            name="BopAgency",
            slug="bopagency",
            owner_email="ceo@bopagency.com",
            owner_name="Bop CEO",
        )
        org = org_service.create_organization(cmd)

        assert org.id is not None
        assert org.name == "BopAgency"

        # Verify owner membership
        owner_user = user_repo.get_by_email("ceo@bopagency.com")
        assert owner_user is not None
        member = org_repo.get_member(org.id, owner_user.id)
        assert member is not None
        assert member.role == MemberRole.OWNER

    def test_add_member_permission(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        user_repo = UserRepository(memory_db)
        service_repo = ServiceRepository(memory_db)
        org_service = OrganizationService(org_repo, user_repo, service_repo)

        org = org_service.create_organization(
            CreateOrganizationCommand(name="Org1", slug="org1", owner_email="owner@org1.com", owner_name="Owner")
        )
        owner_user = user_repo.get_by_email("owner@org1.com")

        # Owner adds admin
        admin_member = org_service.add_member(
            requester_user_id=owner_user.id,
            org_id=org.id,
            target_email="admin@org1.com",
            target_name="Admin",
            role=MemberRole.ADMIN,
        )
        assert admin_member.role == MemberRole.ADMIN

        # Viewer trying to add member fails
        viewer_user = user_repo.get_by_email("admin@org1.com")
        admin_member.role = MemberRole.VIEWER
        org_repo.add_member(admin_member)

        with pytest.raises(TenantAccessError, match="Only Owners or Admins"):
            org_service.add_member(
                requester_user_id=viewer_user.id,
                org_id=org.id,
                target_email="other@org1.com",
                target_name="Other",
                role=MemberRole.MEMBER,
            )

    def test_full_prospecting_lifecycle_with_campaign_prospect(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        user_repo = UserRepository(memory_db)
        service_repo = ServiceRepository(memory_db)
        icp_repo = ICPRepository(memory_db)
        campaign_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)

        org_service = OrganizationService(org_repo, user_repo, service_repo)
        icp_service = ICPService(icp_repo)
        campaign_service = CampaignService(campaign_repo, icp_repo)
        prospect_service = ProspectService(prospect_repo)

        org = org_service.create_organization(
            CreateOrganizationCommand(name="Dental Agency", slug="dental-agency", owner_email="dental@agency.com")
        )

        # 1. Add Service offered
        s = org_service.add_service(
            CreateServiceCommand(
                organization_id=org.id,
                name="AI Web Design & Chatbot",
                description="Custom website + AI booking chatbot",
                category=ServiceCategory.AI_AUTOMATION.value,
            )
        )
        assert s.id is not None

        # 2. Create ICP
        icp = icp_service.create_icp(
            CreateICPCommand(
                organization_id=org.id,
                name="FL Dental Clinics",
                description="Small to mid-size dental practices in Florida",
                industries=["healthcare", "dentist"],
                pain_points=["no_chatbot", "website_slow"],
            )
        )
        assert icp.id is not None

        # 3. Create Campaign 1
        camp1 = campaign_service.create_campaign(
            CreateCampaignCommand(
                organization_id=org.id,
                icp_id=icp.id,
                name="Miami Dentists Sept 2026",
            )
        )

        # 4. Add Prospect to Campaign 1
        p = prospect_service.add_prospect(
            AddProspectCommand(
                organization_id=org.id,
                campaign_id=camp1.id,
                forge_record_id="ov-dentist-1",
                name="Miami Smile Dental",
                website_url="https://miamismile.com",
                phone="305-555-0199",
                city="Miami",
                state="FL",
                industry="dentist",
            )
        )
        assert p.id is not None

        # 5. Create Campaign 2 & Add SAME Prospect to Campaign 2 without duplicating Prospect record
        camp2 = campaign_service.create_campaign(
            CreateCampaignCommand(
                organization_id=org.id,
                icp_id=icp.id,
                name="Florida Clinics Q4",
            )
        )
        p2 = prospect_service.add_prospect(
            AddProspectCommand(
                organization_id=org.id,
                campaign_id=camp2.id,
                forge_record_id="ov-dentist-1",  # Same forge_record_id!
                name="Miami Smile Dental",
                website_url="https://miamismile.com",
            )
        )

        # PROSPECT DEDUPLICATION PROOF:
        assert p2.id == p.id  # Same Prospect ID reused!

        # Total prospects in org = 1
        org_prospects = memory_db.fetch_dicts("SELECT * FROM prospects WHERE organization_id = ?", (org.id,))
        assert len(org_prospects) == 1

        # Campaign memberships = 2
        p_campaigns = prospect_repo.list_prospect_campaigns(org.id, p.id)
        assert len(p_campaigns) == 2
        c_ids = {cp.campaign_id for cp in p_campaigns}
        assert c_ids == {camp1.id, camp2.id}

        # 6. Record Signal & Score (shared at Prospect level!)
        sig = prospect_service.record_signal(
            RecordSignalCommand(
                organization_id=org.id,
                prospect_id=p.id,
                signal_type=SignalType.NO_CHATBOT.value,
                confidence=1.0,
            )
        )
        assert sig.type == "no_chatbot"

        ls = prospect_service.assign_score(
            org_id=org.id,
            prospect_id=p.id,
            score=90,
            explanation="High priority: No AI chatbot detected",
        )
        assert ls.score == 90

    def test_campaign_prospect_cross_tenant_rejection(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        campaign_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)

        org_a = org_repo.save(Organization(name="Org A", slug="org-a"))
        org_b = org_repo.save(Organization(name="Org B", slug="org-b"))

        camp_a = campaign_repo.save(org_a.id, Campaign(name="Camp A"))
        p_b = prospect_repo.save_prospect(org_b.id, Prospect(name="Prospect B"))

        # Attempt to add Org B's prospect to Org A's campaign -> REJECTED
        cp_cross = CampaignProspect(
            organization_id=org_a.id,
            campaign_id=camp_a.id,
            prospect_id=p_b.id,
        )
        with pytest.raises(TenantAccessError, match="not found for tenant"):
            prospect_repo.add_prospect_to_campaign(org_a.id, cp_cross)
