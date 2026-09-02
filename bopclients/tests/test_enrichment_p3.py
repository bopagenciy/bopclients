"""Unit tests for BopClients P3 - Prospect Enrichment & Opportunity Signals (v1.1 Audit)."""

import pytest
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.service import Service
from bopclients.domain.icp import IdealCustomerProfile
from bopclients.domain.signal import Signal
from bopclients.domain.enrichment_result import EnrichmentResult
from bopclients.domain.enums import CampaignStatus
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.enrichment_dto import EnrichmentSnapshot
from bopclients.application.signal_detectors.detectors import (
    NoWebsiteDetector,
    WebsiteUnreachableDetector,
    WebsiteSlowDetector,
    NoSSLDetector,
    NoChatbotDetector,
    NoBookingDetector,
    NoAnalyticsDetector,
)
from bopclients.application.opportunity_scorer import RuleBasedOpportunityScorer
from bopclients.infrastructure.providers.forge_enrichment_provider import ForgeEnrichmentProvider
from bopclients.application.enrichment_orchestrator import EnrichmentOrchestrator
from bopclients.application.enrichment_service import EnrichmentService
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.repositories.enrichment_result_repository import EnrichmentResultRepository
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


class MockEnrichmentGateway:
    """Mock gateway returning predictable enrichment results."""

    def __init__(self, records=None, should_fail=False):
        self.records = records or [{
            "status": "success",
            "scrape_status": "success",
            "status_code": 200,
            "emails": ["info@miamismile.com"],
            "technologies": ["WordPress"],
            "cms": "WordPress",
            "ssl_valid": True,
            "response_time_ms": 3500.0,
            "raw_html": "<html><body>Welcome to Miami Smile</body></html>",
        }]
        self.should_fail = should_fail

    def enrich_batch(self, task):
        if self.should_fail:
            raise RuntimeError("Simulated network failure during enrichment")
        return self.records


class TestSignalDetectors:
    def test_no_website_detector(self):
        detector = NoWebsiteDetector()
        p_no = Prospect(organization_id="org-1", name="No Web Inc", website_url=None)
        p_yes = Prospect(organization_id="org-1", name="Web Inc", website_url="https://web.com")

        snap = EnrichmentSnapshot()
        assert len(detector.detect(p_no, snap)) == 1
        assert len(detector.detect(p_yes, snap)) == 0

    def test_website_unreachable_requires_conclusive_failure(self):
        detector = WebsiteUnreachableDetector()
        p = Prospect(organization_id="org-1", name="Target Inc", website_url="https://target.com")

        # 403 Forbidden is NOT website_unreachable
        assert len(detector.detect(p, EnrichmentSnapshot(scrape_status="forbidden", http_status=403))) == 0

        # HTTP 500 Server Error is NOT website_unreachable
        assert len(detector.detect(p, EnrichmentSnapshot(scrape_status="server_error", http_status=500))) == 0

        # Ambiguous timeout is NOT website_unreachable
        assert len(detector.detect(p, EnrichmentSnapshot(scrape_status="timeout", http_status=None))) == 0

        # DNS failure IS website_unreachable
        res_dns = detector.detect(p, EnrichmentSnapshot(scrape_status="dns_failure", http_status=None))
        assert len(res_dns) == 1
        assert res_dns[0].type == "website_unreachable"

    def test_website_slow_thresholds(self):
        detector = WebsiteSlowDetector()
        p = Prospect(organization_id="org-1", name="Slow Inc", website_url="https://slow.com")

        snap_fast = EnrichmentSnapshot(website_reachable=True, response_time_ms=800)
        assert len(detector.detect(p, snap_fast)) == 0

        snap_mod = EnrichmentSnapshot(website_reachable=True, response_time_ms=2000)
        res_mod = detector.detect(p, snap_mod)
        assert len(res_mod) == 1
        assert res_mod[0].confidence == 0.6

        snap_slow = EnrichmentSnapshot(website_reachable=True, response_time_ms=4500)
        res_slow = detector.detect(p, snap_slow)
        assert len(res_slow) == 1
        assert res_slow[0].confidence == 0.9

    def test_no_booking_category_relevance(self):
        detector = NoBookingDetector()
        p_dentist = Prospect(organization_id="org-1", name="Dental Clinic", website_url="https://dentist.com", industry="dentist")
        p_factory = Prospect(organization_id="org-1", name="Metal Factory", website_url="https://factory.com", industry="manufacturing")

        snap = EnrichmentSnapshot(website_reachable=True, scrape_status="success", has_booking=False)

        assert len(detector.detect(p_dentist, snap)) == 1
        assert len(detector.detect(p_factory, snap)) == 0

    def test_wordpress_does_not_emit_legacy_cms(self):
        snap = EnrichmentSnapshot(website_reachable=True, cms="WordPress", technologies=["WordPress"])
        detectors = [
            NoWebsiteDetector(),
            WebsiteUnreachableDetector(),
            WebsiteSlowDetector(),
            NoSSLDetector(),
            NoChatbotDetector(),
            NoBookingDetector(),
            NoAnalyticsDetector(),
        ]
        signals = []
        p = Prospect(organization_id="org-1", name="WP Site", website_url="https://wp.com")
        for d in detectors:
            signals.extend(d.detect(p, snap))

        sig_types = [s.type for s in signals]
        assert "legacy_cms" not in sig_types


class TestOpportunityScorerScenarios:
    def test_score_scenarios_a_b_c_d(self):
        scorer = RuleBasedOpportunityScorer()
        p = Prospect(organization_id="org-1", name="Clinic A", website_url="https://a.com", industry="dentist", country="US")
        services = [
            Service(organization_id="org-1", name="Web Development", category="web_development"),
            Service(organization_id="org-1", name="AI Chatbot", category="automation"),
        ]
        icp = IdealCustomerProfile(organization_id="org-1", name="Dentist ICP", industries=["dentist"], countries=["US"])

        # A: No signals, no ICP match -> Score = 0
        p_no_match = Prospect(organization_id="org-1", name="Factory", website_url="https://f.com", industry="manufacturing", country="CA")
        score_a, _, _ = scorer.score("org-1", p_no_match, [], services)
        assert score_a == 0

        # B: Strong ICP match, no opportunity signals -> Score = 20 (15 industry + 5 country)
        score_b, _, _ = scorer.score("org-1", p, [], services, icp)
        assert score_b == 20

        # C: Strong ICP match + verified opportunity signals -> Score >= 45
        signals_c = [
            Signal(organization_id="org-1", prospect_id=p.id, type="website_slow", confidence=0.9),
            Signal(organization_id="org-1", prospect_id=p.id, type="no_chatbot", confidence=0.9),
        ]
        score_c, _, recs_c = scorer.score("org-1", p, signals_c, services, icp)
        assert score_c >= 45
        assert len(recs_c) > 0

        # D: Crawler ambiguous timeout only (no signals) -> Score = 20 (ICP only, NO artificial +20 timeout boost!)
        score_d, _, _ = scorer.score("org-1", p, [], services, icp)
        assert score_d == 20


class TestEnrichmentPipelineAndOrchestrator:
    def test_signal_evidence_persistence_roundtrip(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)

        org = org_repo.save(Organization(name="Org Ev"))
        p = prospect_repo.save_prospect(org.id, Prospect(name="Ev Test"))

        sig = Signal(
            organization_id=org.id,
            prospect_id=p.id,
            type="website_slow",
            value="3500ms",
            confidence=0.9,
            source="bopclients_detector",
            evidence={"response_time_ms": 3500.0, "threshold_ms": 1500},
        )
        prospect_repo.add_signal(org.id, sig)

        loaded = prospect_repo.list_signals(org.id, p.id)
        assert len(loaded) == 1
        assert loaded[0].evidence is not None
        assert loaded[0].evidence["response_time_ms"] == 3500.0
        assert loaded[0].source == "bopclients_detector"

    def test_stale_signal_reconciliation(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        camp_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        rr_repo = ResearchRunRepository(memory_db)
        res_repo = EnrichmentResultRepository(memory_db)
        service_repo = ServiceRepository(memory_db)
        icp_repo = ICPRepository(memory_db)

        org = org_repo.save(Organization(name="Reconcile Agency"))
        p = prospect_repo.save_prospect(org.id, Prospect(name="Clinic Reconcile", website_url="https://reconcile.com", industry="dentist"))

        # Pre-existing stale signal: no_chatbot
        prospect_repo.add_signal(org.id, Signal(organization_id=org.id, prospect_id=p.id, type="no_chatbot", value="Old no chatbot"))

        # Run 2: Chatbot IS detected on homepage
        records_run2 = [{
            "status": "success",
            "scrape_status": "success",
            "status_code": 200,
            "emails": ["info@reconcile.com"],
            "technologies": ["Intercom"],
            "ssl_valid": True,
            "response_time_ms": 500.0,
            "raw_html": "<html><body><script src='intercom.js'></script></body></html>",
        }]
        gateway = MockEnrichmentGateway(records_run2)
        provider = ForgeEnrichmentProvider(gateway)
        detectors = [NoWebsiteDetector(), WebsiteUnreachableDetector(), WebsiteSlowDetector(), NoSSLDetector(), NoChatbotDetector()]
        scorer = RuleBasedOpportunityScorer()

        orchestrator = EnrichmentOrchestrator(provider, detectors, scorer, prospect_repo, rr_repo, res_repo, service_repo, icp_repo)

        analysis = orchestrator.analyze_prospect(org.id, p.id)

        # Stale signal no_chatbot MUST be removed!
        active_sigs = prospect_repo.list_signals(org.id, p.id)
        sig_types = [s.type for s in active_sigs]
        assert "no_chatbot" not in sig_types

    def test_last_known_good_snapshot_preservation(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        res_repo = EnrichmentResultRepository(memory_db)

        org = org_repo.save(Organization(name="Org Pres"))
        p = prospect_repo.save_prospect(org.id, Prospect(name="Target Pres", website_url="https://target.com"))

        # Run 1: Success with technologies
        r1 = EnrichmentResult(
            organization_id=org.id,
            prospect_id=p.id,
            status="success",
            website_url="https://target.com",
            data={"emails": ["a@b.com"], "technologies": ["Shopify"], "cms": "Shopify"},
        )
        res_repo.save(org.id, r1)

        # Run 2: Timeout with empty technologies
        r2 = EnrichmentResult(
            organization_id=org.id,
            prospect_id=p.id,
            status="timeout",
            website_url="https://target.com",
            data={"emails": [], "technologies": [], "cms": None},
        )
        res_repo.save(org.id, r2)

        latest = res_repo.get_latest(org.id, p.id)
        assert latest is not None
        assert latest.status == "timeout"
        # Verify last-known-good technologies preserved!
        assert latest.data["technologies"] == ["Shopify"]
        assert latest.data["cms"] == "Shopify"

    def test_tenant_isolation_on_enrichment(self, memory_db):
        org_repo = OrganizationRepository(memory_db)
        camp_repo = CampaignRepository(memory_db)
        prospect_repo = ProspectRepository(memory_db)
        rr_repo = ResearchRunRepository(memory_db)
        res_repo = EnrichmentResultRepository(memory_db)
        service_repo = ServiceRepository(memory_db)

        org1 = org_repo.save(Organization(name="Org One", slug="org-one"))
        org2 = org_repo.save(Organization(name="Org Two", slug="org-two"))

        p1 = prospect_repo.save_prospect(org1.id, Prospect(name="Prospect Org 1"))

        orchestrator = EnrichmentOrchestrator(
            ForgeEnrichmentProvider(MockEnrichmentGateway()),
            [NoWebsiteDetector()],
            RuleBasedOpportunityScorer(),
            prospect_repo, rr_repo, res_repo, service_repo
        )
        service = EnrichmentService(orchestrator, camp_repo, prospect_repo)

        with pytest.raises(TenantAccessError, match="not found for organization"):
            service.analyze_prospect(org2.id, p1.id)
