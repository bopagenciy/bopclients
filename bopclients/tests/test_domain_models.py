"""Unit tests for BopClients domain entities, value objects, and validations."""

import pytest
from bopclients.domain.enums import MemberRole, CampaignStatus, ServiceCategory, SignalType
from bopclients.domain.exceptions import TenantAccessError, ValidationError
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.user import User
from bopclients.domain.service import Service
from bopclients.domain.icp import IdealCustomerProfile, TargetMarket
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.contact import Contact
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore


class TestDomainValidation:
    def test_user_validation(self):
        u = User(email="test@bopclients.com", full_name="John Doe")
        u.validate()

        invalid_u = User(email="invalid_email", full_name="John")
        with pytest.raises(ValueError, match="Invalid user email"):
            invalid_u.validate()

    def test_organization_validation(self):
        org = Organization(name="BopAgency", slug="bopagency")
        org.validate()

        invalid_org = Organization(name="", slug="slug")
        with pytest.raises(ValueError, match="Organization name cannot be empty"):
            invalid_org.validate()

    def test_service_validation(self):
        s = Service(organization_id="org-1", name="AI Automation", category=ServiceCategory.AI_AUTOMATION.value)
        s.validate()

        invalid_s = Service(organization_id="", name="AI Automation")
        with pytest.raises(ValueError, match="organization_id required"):
            invalid_s.validate()

    def test_icp_validation(self):
        icp = IdealCustomerProfile(
            organization_id="org-1",
            name="Dental Clinics FL",
            industries=["healthcare", "dentist"],
            pain_points=["no_booking", "old_website"],
        )
        icp.validate()

    def test_prospect_validation(self):
        p = Prospect(organization_id="org-1", name="Sunshine Dentistry", website_url="https://sunshinedental.com")
        p.validate()

        invalid_p = Prospect(organization_id="org-1", name="")
        with pytest.raises(ValueError, match="Prospect name cannot be empty"):
            invalid_p.validate()

    def test_signal_validation(self):
        sig = Signal(organization_id="org-1", prospect_id="p-1", type=SignalType.WEBSITE_SLOW.value, confidence=0.95)
        sig.validate()

        invalid_sig = Signal(organization_id="org-1", prospect_id="p-1", type="slow", confidence=1.5)
        with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
            invalid_sig.validate()

    def test_lead_score_validation(self):
        ls = LeadScore(organization_id="org-1", prospect_id="p-1", score=85, explanation="Slow site + no chatbot")
        ls.validate()

        invalid_ls = LeadScore(organization_id="org-1", prospect_id="p-1", score=120)
        with pytest.raises(ValueError, match="Score must be between 0 and 100"):
            invalid_ls.validate()

    def test_research_run_validation(self):
        from bopclients.domain.research_run import ResearchRun
        rr = ResearchRun(organization_id="org-1", run_type="discovery", status="running")
        rr.validate()

        invalid_rr = ResearchRun(organization_id="org-1", run_type="discovery", status="invalid_status")
        with pytest.raises(ValueError, match="Invalid status"):
            invalid_rr.validate()
