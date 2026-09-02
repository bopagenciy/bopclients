"""Unit tests for BopClients P4 - AI Intelligence & Prospect Research (v1.0 Audit)."""

import pytest
import time
from datetime import datetime, timezone, timedelta
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.service import Service
from bopclients.domain.icp import IdealCustomerProfile
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.contact import Contact
from bopclients.domain.enrichment_result import EnrichmentResult
from bopclients.domain.enums import CampaignStatus
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.enrichment_dto import EnrichmentSnapshot
from bopclients.application.research_dto import (
    ResearchClaim,
    CommercialOpportunity,
    ProspectResearchContext,
    ProspectResearchDraft,
)
from bopclients.application.research_validation_policy import ResearchValidationPolicy
from bopclients.application.providers.deterministic_research_provider import DeterministicResearchProvider
from bopclients.application.providers.ai_research_provider import AIProspectResearchProviderStub
from bopclients.application.prospect_research_orchestrator import ProspectResearchOrchestrator, is_intelligence_stale
from bopclients.application.prospect_research_service import ProspectResearchService
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.repositories.enrichment_result_repository import EnrichmentResultRepository
from bopclients.infrastructure.repositories.prospect_intelligence_repository import ProspectIntelligenceRepository
from bopclients.infrastructure.repositories.service_repository import ServiceRepository
from bopclients.infrastructure.repositories.icp_repository import ICPRepository
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


@pytest.fixture
def memory_db():
    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)
    return db


class TestResearchValidationPolicy:
    def test_observed_claim_without_evidence_rejected(self):
        policy = ResearchValidationPolicy()
        draft = ProspectResearchDraft(
            claims=[
                ResearchClaim(
                    id="c1",
                    claim_type="no_booking",
                    statement="No online booking observed",
                    classification="observed",
                    evidence_refs=[],  # Missing evidence! Must be REJECTED!
                )
            ]
        )
        validated, warnings, rejected = policy.validate(draft)
        assert len(rejected) == 1
        assert len(validated.claims) == 0
        assert "REJECTED_UNSUPPORTED_OBSERVED_CLAIM" in warnings[0]

    def test_unsupported_factual_assertions_rejected(self):
        policy = ResearchValidationPolicy()
        draft = ProspectResearchDraft(
            claims=[
                ResearchClaim(
                    id="c2",
                    claim_type="hallucinated_revenue",
                    statement="Company generates $5M in annual revenue",
                    classification="derived",
                    evidence_refs=[],  # Missing evidence! Factual claim MUST BE REJECTED!
                ),
                ResearchClaim(
                    id="c3",
                    claim_type="hallucinated_employees",
                    statement="Company has employee count of 50",
                    classification="derived",
                    evidence_refs=[],
                ),
            ]
        )
        validated, warnings, rejected = policy.validate(draft)
        assert len(rejected) == 2
        assert len(validated.claims) == 0
        assert any("REJECTED_UNSUPPORTED_FACTUAL_CLAIM" in w for w in warnings)

    def test_unverified_contact_claim_rejected(self):
        policy = ResearchValidationPolicy()
        draft = ProspectResearchDraft(
            claims=[
                ResearchClaim(
                    id="c4",
                    claim_type="unverified_contact",
                    statement="John Smith is the Marketing Director",
                    classification="derived",
                    evidence_refs=[],
                )
            ]
        )
        # Pass verified contacts where John Smith is NOT listed
        verified_contacts = [Contact(name="Alice Brown", title="CEO")]
        validated, warnings, rejected = policy.validate(draft, verified_contacts=verified_contacts)
        assert len(rejected) == 1
        assert len(validated.claims) == 0
        assert "REJECTED_UNVERIFIED_CONTACT_CLAIM" in warnings[0]


class TestAIProviderProvenance:
    def test_ai_stub_provider_name_provenance(self):
        stub = AIProspectResearchProviderStub()
        assert stub.name == "ai_stub:deterministic"
        assert "ai_gemini" not in stub.name


class TestDeterministicResearchProvider:
    def test_deterministic_research_generation(self):
        provider = DeterministicResearchProvider()
        p = Prospect(id="p1", organization_id="org-1", name="Dental Clinic", industry="dentist", country="US", website_url="https://dental.com")
        snap = EnrichmentSnapshot(prospect_id="p1", website_reachable=True, scrape_status="success", http_status=200, response_time_ms=2500)
        signals = [
            Signal(organization_id="org-1", prospect_id="p1", type="no_chatbot", value="No chatbot", confidence=0.9),
            Signal(organization_id="org-1", prospect_id="p1", type="no_booking", value="No booking", confidence=0.85),
            Signal(organization_id="org-1", prospect_id="p1", type="website_slow", value="2500ms", confidence=0.6),
        ]
        services = [
            Service(organization_id="org-1", name="Automation & AI Chatbot", category="automation"),
            Service(organization_id="org-1", name="Web Development", category="web_development"),
        ]

        ctx = ProspectResearchContext(
            organization_id="org-1",
            prospect=p,
            enrichment_snapshot=snap,
            signals=signals,
            services=services,
        )

        draft = provider.research(ctx)
        assert draft.overall_confidence >= 0.75
        assert len(draft.claims) >= 3
        assert len(draft.commercial_opportunities) >= 2
        assert any(o.opportunity_type == "contact_and_booking_automation" for o in draft.commercial_opportunities)
        assert len(draft.unknowns) >= 3

    def test_low_evidence_research_generation(self):
        provider = DeterministicResearchProvider()
        p = Prospect(id="p2", organization_id="org-1", name="Unknown Co", website_url="https://unknown.com")
        snap = EnrichmentSnapshot(prospect_id="p2", website_reachable=False, scrape_status="timeout")

        ctx = ProspectResearchContext(organization_id="org-1", prospect=p, enrichment_snapshot=snap)

        draft = provider.research(ctx)
        assert draft.overall_confidence <= 0.50
        assert len(draft.risks) >= 1
        assert "incomplete" in draft.risks[0].lower() or "timed out" in draft.risks[0].lower()


class TestProspectResearchOrchestratorAndFreshness:
    def test_full_prospect_research_lifecycle(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        camp_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        rr_repo = ResearchRunRepository(memory_db)
        res_repo = EnrichmentResultRepository(memory_db)
        intel_repo = ProspectIntelligenceRepository(memory_db)
        service_repo = ServiceRepository(memory_db)
        icp_repo = ICPRepository(memory_db)

        org = org_repo.save(Organization(name="Research Agency"))
        camp = camp_repo.save(org.id, Campaign(name="Dental Research Camp", status=CampaignStatus.ACTIVE))

        p = prospect_repo.save_prospect(org.id, Prospect(name="Miami Dental", website_url="https://miamidental.com", industry="dentist"))
        prospect_repo.add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p.id))

        service_repo.save(org.id, Service(name="Automation", category="automation"))
        prospect_repo.add_signal(org.id, Signal(organization_id=org.id, prospect_id=p.id, type="no_booking", confidence=0.85))

        res_repo.save(
            org.id,
            EnrichmentResult(
                organization_id=org.id,
                prospect_id=p.id,
                status="success",
                website_url="https://miamidental.com",
                completed_at="2026-09-02T10:00:00Z",
                data={"http_status": 200},
            )
        )

        provider = DeterministicResearchProvider()
        policy = ResearchValidationPolicy()
        orchestrator = ProspectResearchOrchestrator(
            provider, policy, prospect_repo, rr_repo, res_repo, intel_repo, service_repo, icp_repo
        )
        service = ProspectResearchService(orchestrator, camp_repo, prospect_repo)

        res = service.research_prospect(org.id, p.id, camp.id)

        assert res.prospect_id == p.id
        assert res.confidence >= 0.70
        assert len(res.claims) >= 1

        # Verify intelligence persisted in DB
        intel = intel_repo.get_latest(org.id, p.id)
        assert intel is not None
        assert intel.provider == "deterministic"
        assert intel.data["executive_summary"] == res.executive_summary

    def test_research_freshness_and_stale_detection(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        camp_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        rr_repo = ResearchRunRepository(memory_db)
        res_repo = EnrichmentResultRepository(memory_db)
        intel_repo = ProspectIntelligenceRepository(memory_db)
        service_repo = ServiceRepository(memory_db)

        org = org_repo.save(Organization(name="Fresh Agency"))
        p = prospect_repo.save_prospect(org.id, Prospect(name="Stale Test Co"))

        provider = DeterministicResearchProvider()
        policy = ResearchValidationPolicy()
        orchestrator = ProspectResearchOrchestrator(
            provider, policy, prospect_repo, rr_repo, res_repo, intel_repo, service_repo
        )

        # 1. Research prospect
        res1 = orchestrator.research_prospect(org.id, p.id)
        intel1 = intel_repo.get_latest(org.id, p.id)
        assert intel1 is not None
        assert not is_intelligence_stale(intel1)

        # 2. Add newer signal timestamp -> is_stale becomes True!
        newer_signal_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        assert is_intelligence_stale(intel1, latest_signal_detected_at=newer_signal_time)

        # 3. Refresh research -> is_stale becomes False!
        res2 = orchestrator.research_prospect(org.id, p.id)
        intel2 = intel_repo.get_latest(org.id, p.id)
        assert not is_intelligence_stale(intel2)

    def test_fingerprint_freshness_scenarios(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        camp_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        rr_repo = ResearchRunRepository(memory_db)
        res_repo = EnrichmentResultRepository(memory_db)
        intel_repo = ProspectIntelligenceRepository(memory_db)
        service_repo = ServiceRepository(memory_db)

        org = org_repo.save(Organization(name="Fingerprint Freshness Agency"))
        p = prospect_repo.save_prospect(org.id, Prospect(name="Fresh Clinic"))

        s1 = service_repo.save(org.id, Service(name="Web Dev", category="web_development"))
        s2 = service_repo.save(org.id, Service(name="Automation", category="automation"))

        sig1 = prospect_repo.add_signal(org.id, Signal(organization_id=org.id, prospect_id=p.id, type="no_booking", confidence=0.85))

        orchestrator = ProspectResearchOrchestrator(
            DeterministicResearchProvider(), ResearchValidationPolicy(),
            prospect_repo, rr_repo, res_repo, intel_repo, service_repo
        )
        service = ProspectResearchService(orchestrator, camp_repo, prospect_repo)

        # Generate initial intelligence snapshot
        res1 = service.research_prospect(org.id, p.id)
        intel1 = intel_repo.get_latest(org.id, p.id)
        assert intel1 is not None

        # Current state: not stale
        curr_signals = prospect_repo.list_signals(org.id, p.id)
        curr_services = service_repo.list_by_organization(org.id)
        assert not is_intelligence_stale(intel1, current_signals=curr_signals, current_services=curr_services)

        # Test A: Swap active service category (same total service count = 2) -> is_stale == True!
        mod_services = [
            Service(id=s1.id, organization_id=org.id, name="Web Dev", category="marketing"),
            Service(id=s2.id, organization_id=org.id, name="Automation", category="automation"),
        ]
        assert is_intelligence_stale(intel1, current_services=mod_services)

        # Test B: Signal removal/reconciliation -> is_stale == True!
        assert is_intelligence_stale(intel1, current_signals=[])

        # Test C: Update LeadScore -> is_stale == True!
        ls = prospect_repo.save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p.id, score=85.0))
        assert is_intelligence_stale(intel1, lead_score=ls)

        # Test D: refresh_research() -> is_stale == False!
        res2 = service.refresh_research(org.id, p.id)
        intel2 = intel_repo.get_latest(org.id, p.id)
        fresh_services = service_repo.list_by_organization(org.id)
        fresh_ls = prospect_repo.get_lead_score(org.id, p.id)
        assert not is_intelligence_stale(intel2, current_signals=curr_signals, lead_score=fresh_ls, current_services=fresh_services)

    def test_tenant_isolation_on_research(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        camp_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        rr_repo = ResearchRunRepository(memory_db)
        res_repo = EnrichmentResultRepository(memory_db)
        intel_repo = ProspectIntelligenceRepository(memory_db)
        service_repo = ServiceRepository(memory_db)

        org1 = org_repo.save(Organization(name="Org One", slug="org-one"))
        org2 = org_repo.save(Organization(name="Org Two", slug="org-two"))

        p1 = prospect_repo.save_prospect(org1.id, Prospect(name="Prospect Org 1"))

        orchestrator = ProspectResearchOrchestrator(
            DeterministicResearchProvider(),
            ResearchValidationPolicy(),
            prospect_repo, rr_repo, res_repo, intel_repo, service_repo
        )
        service = ProspectResearchService(orchestrator, camp_repo, prospect_repo)

        with pytest.raises(TenantAccessError, match="not found for organization"):
            service.research_prospect(org2.id, p1.id)
