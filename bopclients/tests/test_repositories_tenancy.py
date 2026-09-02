"""Repository Integration Tests & Multi-tenant Boundary Isolation Tests."""

import pytest
from bopclients.domain.exceptions import TenantAccessError
from bopclients.domain.organization import Organization
from bopclients.domain.service import Service
from bopclients.domain.icp import IdealCustomerProfile
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.infrastructure.db.migrations import run_p1_migrations
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
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


class TestTenantBoundaryIsolation:
    """Rigorous tests proving Organization A cannot read or modify Organization B data."""

    def test_services_tenant_isolation(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        service_repo = ServiceRepository(memory_db)

        org_a = org_repo.save(Organization(name="Org A", slug="org-a"))
        org_b = org_repo.save(Organization(name="Org B", slug="org-b"))

        s_a = service_repo.save(org_a.id, Service(name="Org A Marketing", category="marketing"))
        s_b = service_repo.save(org_b.id, Service(name="Org B Web Design", category="design"))

        # Org A list only returns Org A services
        services_a = service_repo.list_by_organization(org_a.id)
        assert len(services_a) == 1
        assert services_a[0].name == "Org A Marketing"

        # Org B list only returns Org B services
        services_b = service_repo.list_by_organization(org_b.id)
        assert len(services_b) == 1
        assert services_b[0].name == "Org B Web Design"

        # Org A cannot fetch Org B service by ID
        cross_fetch = service_repo.get_by_id(org_a.id, s_b.id)
        assert cross_fetch is None

    def test_prospects_and_signals_tenant_isolation(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        campaign_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)

        org_a = org_repo.save(Organization(name="Org A", slug="org-a"))
        org_b = org_repo.save(Organization(name="Org B", slug="org-b"))

        camp_a = campaign_repo.save(org_a.id, Campaign(name="Camp A"))
        camp_b = campaign_repo.save(org_b.id, Campaign(name="Camp B"))

        from bopclients.domain.campaign_prospect import CampaignProspect

        p_a = prospect_repo.save_prospect(org_a.id, Prospect(name="Prospect A Clinic"))
        p_b = prospect_repo.save_prospect(org_b.id, Prospect(name="Prospect B Law Firm"))

        prospect_repo.add_prospect_to_campaign(
            org_a.id, CampaignProspect(organization_id=org_a.id, campaign_id=camp_a.id, prospect_id=p_a.id)
        )
        prospect_repo.add_prospect_to_campaign(
            org_b.id, CampaignProspect(organization_id=org_b.id, campaign_id=camp_b.id, prospect_id=p_b.id)
        )

        # Record signals for each tenant
        sig_a = prospect_repo.add_signal(org_a.id, Signal(prospect_id=p_a.id, type="website_slow"))
        sig_b = prospect_repo.add_signal(org_b.id, Signal(prospect_id=p_b.id, type="no_chatbot"))

        # Lead scores for each tenant
        prospect_repo.save_lead_score(org_a.id, LeadScore(prospect_id=p_a.id, score=95))
        prospect_repo.save_lead_score(org_b.id, LeadScore(prospect_id=p_b.id, score=40))

        # 1. Prospect cross-query protection
        assert prospect_repo.get_prospect_by_id(org_a.id, p_b.id) is None
        assert prospect_repo.get_prospect_by_id(org_b.id, p_a.id) is None

        # 2. Campaign prospect list protection
        prospects_a = prospect_repo.list_prospects_by_campaign(org_a.id, camp_a.id)
        assert len(prospects_a) == 1
        assert prospects_a[0].name == "Prospect A Clinic"

        prospects_b_cross = prospect_repo.list_prospects_by_campaign(org_a.id, camp_b.id)
        assert len(prospects_b_cross) == 0

        # 3. Signal isolation
        signals_a = prospect_repo.list_signals(org_a.id, p_a.id)
        assert len(signals_a) == 1
        assert signals_a[0].type == "website_slow"

        signals_cross = prospect_repo.list_signals(org_a.id, p_b.id)
        assert len(signals_cross) == 0

        # 4. Lead Score isolation
        score_a = prospect_repo.get_lead_score(org_a.id, p_a.id)
        assert score_a is not None
        assert score_a.score == 95

        score_cross = prospect_repo.get_lead_score(org_a.id, p_b.id)
        assert score_cross is None

    def test_missing_or_invalid_tenant_raises_tenant_access_error(self, memory_db):
        prospect_repo = ProspectRepository(memory_db)
        with pytest.raises(TenantAccessError):
            prospect_repo.list_prospects_by_campaign("", "camp-1")

        with pytest.raises(TenantAccessError):
            prospect_repo.save_prospect("   ", Prospect(name="Invalid Tenant Prospect"))


class TestAdversarialCrossTenantAttacks:
    """Adversarial security tests verifying that cross-tenant access attempts are strictly rejected."""

    def test_multi_organization_user_roles(self, memory_db):
        from bopclients.domain.user import User
        from bopclients.domain.enums import MemberRole
        from bopclients.application.dtos import CreateOrganizationCommand
        from bopclients.application.organization_service import OrganizationService
        from bopclients.infrastructure.repositories.organization_repository import UserRepository

        user_repo = UserRepository(memory_db)
        org_repo = OrganizationRepository(memory_db)
        service_repo = ServiceRepository(memory_db)
        org_service = OrganizationService(org_repo, user_repo, service_repo)

        # Create Org 1 with user as Owner
        org1 = org_service.create_organization(
            CreateOrganizationCommand(name="Org One", slug="org-one", owner_email="multi@user.com", owner_name="Multi User")
        )
        user = user_repo.get_by_email("multi@user.com")

        # Create Org 2 and Org 3 with different owners, then add multi@user.com with different roles
        org2 = org_service.create_organization(
            CreateOrganizationCommand(name="Org Two", slug="org-two", owner_email="other2@user.com")
        )
        org3 = org_service.create_organization(
            CreateOrganizationCommand(name="Org Three", slug="org-three", owner_email="other3@user.com")
        )

        owner2 = user_repo.get_by_email("other2@user.com")
        owner3 = user_repo.get_by_email("other3@user.com")

        # Add user to Org 2 as Admin
        m2 = org_service.add_member(owner2.id, org2.id, "multi@user.com", "Multi User", MemberRole.ADMIN)

        # Add user to Org 3 as Viewer
        m3 = org_service.add_member(owner3.id, org3.id, "multi@user.com", "Multi User", MemberRole.VIEWER)

        # Verify exact 1 User record exists
        users = memory_db.fetch_dicts("SELECT * FROM users WHERE email = 'multi@user.com'")
        assert len(users) == 1

        # Verify 3 distinct memberships with appropriate roles
        m1_check = org_repo.get_member(org1.id, user.id)
        m2_check = org_repo.get_member(org2.id, user.id)
        m3_check = org_repo.get_member(org3.id, user.id)

        assert m1_check.role == MemberRole.OWNER
        assert m2_check.role == MemberRole.ADMIN
        assert m3_check.role == MemberRole.VIEWER

    def test_campaign_creation_with_cross_tenant_icp_rejected(self, memory_db):
        from bopclients.application.campaign_service import CampaignService
        from bopclients.application.dtos import CreateCampaignCommand

        org_repo = OrganizationRepository(memory_db)
        icp_repo = ICPRepository(memory_db)
        campaign_repo = CampaignRepository(memory_db)
        campaign_service = CampaignService(campaign_repo, icp_repo)

        org_a = org_repo.save(Organization(name="Org A", slug="org-a"))
        org_b = org_repo.save(Organization(name="Org B", slug="org-b"))

        icp_b = icp_repo.save(org_b.id, IdealCustomerProfile(name="Org B Dentists"))

        # Org A attempts to create campaign referencing Org B's ICP
        with pytest.raises(TenantAccessError, match="does not belong to organization"):
            campaign_service.create_campaign(
                CreateCampaignCommand(organization_id=org_a.id, icp_id=icp_b.id, name="Malicious Campaign")
            )

    def test_signal_recording_on_cross_tenant_prospect_rejected(self, memory_db):
        from bopclients.application.prospect_service import ProspectService
        from bopclients.application.dtos import RecordSignalCommand

        org_repo = OrganizationRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        prospect_service = ProspectService(prospect_repo)

        org_a = org_repo.save(Organization(name="Org A", slug="org-a"))
        org_b = org_repo.save(Organization(name="Org B", slug="org-b"))

        p_b = prospect_repo.save_prospect(org_b.id, Prospect(name="Org B Prospect"))

        # Org A attempts to record signal on Org B's prospect
        with pytest.raises(TenantAccessError, match="Signal rejected"):
            prospect_service.record_signal(
                RecordSignalCommand(organization_id=org_a.id, prospect_id=p_b.id, signal_type="website_slow")
            )

    def test_lead_score_assignment_on_cross_tenant_prospect_rejected(self, memory_db):
        from bopclients.application.prospect_service import ProspectService

        org_repo = OrganizationRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        prospect_service = ProspectService(prospect_repo)

        org_a = org_repo.save(Organization(name="Org A", slug="org-a"))
        org_b = org_repo.save(Organization(name="Org B", slug="org-b"))

        p_b = prospect_repo.save_prospect(org_b.id, Prospect(name="Org B Prospect"))

        # Org A attempts to assign LeadScore to Org B's prospect
        with pytest.raises(TenantAccessError, match="LeadScore rejected"):
            prospect_service.assign_score(org_id=org_a.id, prospect_id=p_b.id, score=99)

    def test_contact_creation_on_cross_tenant_prospect_rejected(self, memory_db):
        from bopclients.domain.contact import Contact

        org_repo = OrganizationRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)

        org_a = org_repo.save(Organization(name="Org A", slug="org-a"))
        org_b = org_repo.save(Organization(name="Org B", slug="org-b"))

        p_b = prospect_repo.save_prospect(org_b.id, Prospect(name="Org B Prospect"))

        # Org A attempts to add Contact to Org B's prospect
        with pytest.raises(ValueError, match="not found for tenant"):
            prospect_repo.add_contact(org_a.id, Contact(prospect_id=p_b.id, name="Dr. Smith"))

    def test_manual_prospect_and_multiple_sources(self, memory_db):
        from bopclients.domain.prospect_source import ProspectSource

        org_repo = OrganizationRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)

        org_a = org_repo.save(Organization(name="Org A", slug="org-a"))

        # Manual prospect with forge_record_id = None
        p_manual = prospect_repo.save_prospect(
            org_a.id, Prospect(name="Manual Clinic", forge_record_id=None, source="manual")
        )
        assert p_manual.forge_record_id is None

        # Add multiple sources for provenance
        src1 = prospect_repo.add_prospect_source(
            org_a.id, ProspectSource(prospect_id=p_manual.id, source_type="manual", source_url="https://manual.org")
        )
        src2 = prospect_repo.add_prospect_source(
            org_a.id, ProspectSource(prospect_id=p_manual.id, source_type="directory", external_id="dir-999")
        )

        sources = memory_db.fetch_dicts("SELECT * FROM prospect_sources WHERE prospect_id = ?", (p_manual.id,))
        assert len(sources) == 2


class TestResearchRunTenancy:
    """Tests covering ResearchRun creation, tenant boundaries, and status updates."""

    def test_research_run_scenarios(self, memory_db):
        from bopclients.domain.research_run import ResearchRun
        from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository

        org_repo = OrganizationRepository(memory_db)
        campaign_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        rr_repo = ResearchRunRepository(memory_db)

        org_a = org_repo.save(Organization(name="Org A", slug="org-a"))
        org_b = org_repo.save(Organization(name="Org B", slug="org-b"))

        camp_a = campaign_repo.save(org_a.id, Campaign(name="Camp A"))
        camp_b = campaign_repo.save(org_b.id, Campaign(name="Camp B"))

        p_a = prospect_repo.save_prospect(org_a.id, Prospect(name="Prospect A"))
        p_b = prospect_repo.save_prospect(org_b.id, Prospect(name="Prospect B"))

        # Test A: Create ResearchRun for valid Campaign of same tenant
        rr1 = rr_repo.save(org_a.id, ResearchRun(campaign_id=camp_a.id, run_type="discovery"))
        assert rr1.id is not None

        # Test B: Create ResearchRun for valid Prospect of same tenant
        rr2 = rr_repo.save(org_a.id, ResearchRun(prospect_id=p_a.id, run_type="enrichment"))
        assert rr2.id is not None

        # Test C: General ResearchRun without Campaign or Prospect
        rr3 = rr_repo.save(org_a.id, ResearchRun(run_type="intent_research"))
        assert rr3.campaign_id is None
        assert rr3.prospect_id is None

        # Test D: Org A attempts to use Campaign of Org B -> TenantAccessError
        with pytest.raises(TenantAccessError, match="Campaign .* not found for organization"):
            rr_repo.save(org_a.id, ResearchRun(campaign_id=camp_b.id, run_type="discovery"))

        # Test E: Org A attempts to use Prospect of Org B -> TenantAccessError
        with pytest.raises(TenantAccessError, match="Prospect .* not found for organization"):
            rr_repo.save(org_a.id, ResearchRun(prospect_id=p_b.id, run_type="enrichment"))

        # Test F: Org A attempts to update status of ResearchRun belonging to Org B -> TenantAccessError
        rr_b = rr_repo.save(org_b.id, ResearchRun(campaign_id=camp_b.id, run_type="discovery"))
        with pytest.raises(TenantAccessError, match="not found for organization"):
            rr_repo.update_status(org_a.id, rr_b.id, status="completed")

        # Test G: Listing ResearchRuns for Org A returns ONLY Org A records
        runs_a = rr_repo.list_by_organization(org_a.id)
        assert len(runs_a) == 3
        a_ids = {r.id for r in runs_a}
        assert rr_b.id not in a_ids
