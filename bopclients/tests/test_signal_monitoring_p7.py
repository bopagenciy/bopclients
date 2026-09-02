"""Comprehensive unit test suite for BopClients P7 Public Signal Monitoring & Observations (P7.3 Audit Aligned)."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.enums import CampaignStatus, SignalType, SignalCategory, IntentStrength
from bopclients.domain.exceptions import TenantAccessError, EntityNotFoundError
from bopclients.application.signal_provider import OfficialWebsiteSignalProvider
from bopclients.application.signal_activation_policy import SignalActivationPolicy, SourceReliability
from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.prospect_priority_service import ProspectPriorityService
from bopclients.infrastructure.security.network_validator import NetworkSafetyValidator
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.prospect_priority_repository import ProspectPriorityRepository
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.prospect_intelligence_repository import ProspectIntelligenceRepository
from bopclients.infrastructure.repositories.enrichment_result_repository import EnrichmentResultRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


@pytest.fixture
def memory_db():
    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)
    return db


@pytest.fixture
def repos(memory_db):
    return {
        "db": memory_db,
        "org": OrganizationRepository(memory_db),
        "camp": CampaignRepository(memory_db),
        "prospect": ProspectRepository(memory_db),
        "prio": ProspectPriorityRepository(memory_db),
        "obs": SignalObservationRepository(memory_db),
        "intel": ProspectIntelligenceRepository(memory_db),
        "enrich": EnrichmentResultRepository(memory_db),
        "rr": ResearchRunRepository(memory_db),
    }


@pytest.fixture(autouse=True)
def mock_dns_resolution():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 80))]):
        yield


class MockHtmlScraper:
    def __init__(self, pages: dict):
        self.pages = pages

    def fetch_page(self, url: str):
        if url in self.pages:
            res = self.pages[url]
            if isinstance(res, dict):
                return res
            return {"status": 200, "content": res, "headers": {"content-type": "text/html"}}
        return {"status": 404, "content": "", "headers": {}}


class TestPublicSignalProviderAndSafetyP7:
    def test_provider_capability_contract(self):
        prov = OfficialWebsiteSignalProvider()
        caps = prov.capabilities

        assert caps.supports_rfp is True
        assert caps.supports_jobs is True
        assert caps.supports_company_news is False
        assert caps.supports_press_releases is False
        assert caps.supports_website_change is False
        assert caps.requires_api_key is False
        assert caps.network_access is True

        assert len(prov.RFP_PATTERNS) > 0
        assert len(prov.HIRING_MKT_PATTERNS) > 0

    def test_ssrf_protection_localhost_rejected(self):
        ok1, err1 = NetworkSafetyValidator.validate_url("http://localhost/admin", resolve_dns=False)
        ok2, err2 = NetworkSafetyValidator.validate_url("http://127.0.0.1/status", resolve_dns=False)
        ok3, err3 = NetworkSafetyValidator.validate_url("http://[::1]/debug", resolve_dns=False)

        assert ok1 is False and "SSRF" in err1
        assert ok2 is False and "SSRF" in err2
        assert ok3 is False and "SSRF" in err3

    def test_ssrf_protection_private_ip_ranges_rejected(self):
        ok1, _ = NetworkSafetyValidator.validate_url("http://10.0.0.1/api", resolve_dns=False)
        ok2, _ = NetworkSafetyValidator.validate_url("http://192.168.1.1/config", resolve_dns=False)
        ok3, _ = NetworkSafetyValidator.validate_url("http://169.254.169.254/latest/meta-data", resolve_dns=False)

        assert ok1 is False
        assert ok2 is False
        assert ok3 is False

    @patch("socket.getaddrinfo")
    def test_dns_ssrf_protection_resolving_private_ip_blocked(self, mock_gai):
        mock_gai.return_value = [(2, 1, 6, "", ("127.0.0.1", 80))]
        ok, err = NetworkSafetyValidator.validate_url("http://attacker.example/admin", resolve_dns=True)
        assert ok is False
        assert "DNS resolved" in err and "loopback" in err

    @patch("socket.getaddrinfo")
    def test_dns_failure_policy_rejected(self, mock_gai):
        import socket
        mock_gai.side_effect = socket.gaierror("Name or service not known")
        ok, err = NetworkSafetyValidator.validate_url("http://nonexistent.domain.invalid/api", resolve_dns=True)
        assert ok is False
        assert "DNS resolution failed" in err

    def test_unsupported_protocol_scheme_rejected(self):
        ok1, err1 = NetworkSafetyValidator.validate_url("file:///etc/passwd", resolve_dns=False)
        ok2, err2 = NetworkSafetyValidator.validate_url("ftp://server.com/file", resolve_dns=False)

        assert ok1 is False and "Unsupported" in err1
        assert ok2 is False and "Unsupported" in err2

    def test_official_site_rfp_detection_and_due_date(self):
        html = """
        <html><body>
        <h1>Procurement Opportunities</h1>
        <p>Request for Proposal: Healthcare Digital Marketing Services</p>
        <p>Proposals due October 15, 2026</p>
        </body></html>
        """
        scraper = MockHtmlScraper({"https://clinic.com": html})
        prov = OfficialWebsiteSignalProvider(scraper=scraper)
        p = Prospect(id="p1", organization_id="org-1", website_url="https://clinic.com")

        res = prov.discover_signals(p)
        assert len(res.observations) == 1
        obs = res.observations[0]

        assert obs.signal_type == SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value
        assert obs.category == SignalCategory.BUYING_INTENT.value
        assert obs.intent_strength == IntentStrength.STRONG.value
        assert obs.evidence["due_date"] == "October 15, 2026"
        assert obs.evidence["currentness"] == "active"

    def test_external_link_rfp_rejected_for_buying_intent(self):
        policy = SignalActivationPolicy()
        obs_external = PublicSignalObservation(
            organization_id="org-1",
            prospect_id="p1",
            provider="official_website",
            signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            intent_strength=IntentStrength.STRONG.value,
            source_url="https://random-third-party.example/rfp",
            evidence={"snippet": "Request for Proposal", "currentness": "active"},
        )
        ok, sig, reason = policy.evaluate_activation(
            obs_external, prospect_website_url="https://company.example"
        )
        assert ok is False
        assert "outside official prospect host boundary" in reason

    def test_rfp_false_positive_educational_blog_rejected(self):
        html = """
        <html><body>
        <h1>Blog: What is an RFP?</h1>
        <p>A Request for Proposal (RFP) is a document that an organization posts to elicit bids.</p>
        <p>Here is a guide to writing an RFP template for your agency.</p>
        </body></html>
        """
        scraper = MockHtmlScraper({"https://blogsite.com": html})
        prov = OfficialWebsiteSignalProvider(scraper=scraper)
        p = Prospect(id="p1", organization_id="org-1", website_url="https://blogsite.com")

        res = prov.discover_signals(p)
        rfp_obs = [o for o in res.observations if o.signal_type == SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value]
        assert len(rfp_obs) == 0

    def test_rfp_archived_closed_currentness(self):
        html = """
        <html><body>
        <h1>Archived Solicitations</h1>
        <p>Archived Request for Proposal: 2025 Marketing Vendor Search.</p>
        <p>Submissions are closed. Awarded contract in March 2025.</p>
        </body></html>
        """
        scraper = MockHtmlScraper({"https://pastrfp.com": html})
        prov = OfficialWebsiteSignalProvider(scraper=scraper)
        p = Prospect(id="p1", organization_id="org-1", website_url="https://pastrfp.com")

        res = prov.discover_signals(p)
        rfp_obs = [o for o in res.observations if o.signal_type == SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value]
        assert len(rfp_obs) == 1
        assert rfp_obs[0].evidence["currentness"] == "closed"

    def test_vendor_search_evidence_detection(self):
        html = """
        <html><body>
        <h1>Supplier Opportunities</h1>
        <p>Apex Medical Center is currently seeking vendors for software consulting.</p>
        </body></html>
        """
        scraper = MockHtmlScraper({"https://apex.com": html})
        prov = OfficialWebsiteSignalProvider(scraper=scraper)
        p = Prospect(id="p1", organization_id="org-1", website_url="https://apex.com")

        res = prov.discover_signals(p)
        obs = [o for o in res.observations if o.signal_type == SignalType.VENDOR_SEARCH.value][0]
        assert obs.category == SignalCategory.BUYING_INTENT.value
        assert obs.intent_strength == IntentStrength.STRONG.value
        assert obs.evidence["currentness"] == "active"

    def test_hiring_marketing_job_role_detection(self):
        html = """
        <html><body>
        <h1>Careers</h1>
        <p>We're hiring a Digital Marketing Manager to lead our growth team.</p>
        </body></html>
        """
        scraper = MockHtmlScraper({"https://techco.com": html})
        prov = OfficialWebsiteSignalProvider(scraper=scraper)
        p = Prospect(id="p1", organization_id="org-1", website_url="https://techco.com")

        res = prov.discover_signals(p)
        mkt_obs = [o for o in res.observations if o.signal_type == SignalType.HIRING_MARKETING.value]
        assert len(mkt_obs) == 1
        assert mkt_obs[0].category == SignalCategory.COMPANY_ACTIVITY.value

    def test_location_expansion_signal_detection(self):
        html = """
        <html><body>
        <h1>News</h1>
        <p>We opened our new Orlando location in August 2026.</p>
        </body></html>
        """
        scraper = MockHtmlScraper({"https://clinic-expand.com": html})
        prov = OfficialWebsiteSignalProvider(scraper=scraper)
        p = Prospect(id="p1", organization_id="org-1", website_url="https://clinic-expand.com")

        res = prov.discover_signals(p)
        loc_obs = [o for o in res.observations if o.signal_type == SignalType.OPENED_NEW_LOCATION.value]
        assert len(loc_obs) == 1
        assert loc_obs[0].evidence["location_name"] == "Orlando"


class TestSignalActivationPolicyAndDedupeP7:
    def test_fingerprint_stability_with_cosmetic_snippet_changes(self, repos):
        org = repos["org"].save(Organization(name="Org 1", slug="org-1"))
        p = repos["prospect"].save_prospect(org.id, Prospect(id="p1", organization_id=org.id, name="Apex"))

        obs_repo = repos["obs"]
        obs1 = PublicSignalObservation(
            organization_id=org.id,
            prospect_id=p.id,
            provider="official_website",
            signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            source_url="https://apex.com/rfp",
            evidence={"snippet": "Request for Proposal - Digital Marketing", "rfp_title": "Digital Marketing RFP", "matched_rule": "explicit_rfp_solicitation"},
        )
        saved1 = obs_repo.save(org.id, obs1)

        obs2 = PublicSignalObservation(
            organization_id=org.id,
            prospect_id=p.id,
            provider="official_website",
            signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            source_url="https://apex.com/rfp",
            evidence={"snippet": "NEW: Request for Proposal - Digital Marketing Services", "rfp_title": "Digital Marketing RFP", "matched_rule": "explicit_rfp_solicitation"},
        )
        saved2 = obs_repo.save(org.id, obs2)

        assert saved1.fingerprint == saved2.fingerprint
        assert saved2.id == saved1.id
        assert len(obs_repo.list_for_prospect(org.id, p.id)) == 1

    def test_multiple_rfps_same_page_produce_distinct_fingerprints(self):
        obs_a = PublicSignalObservation(
            organization_id="org-1",
            prospect_id="p1",
            signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            source_url="https://apex.com/procurement",
            evidence={"rfp_title": "Marketing Services RFP", "matched_rule": "explicit_rfp_solicitation"},
        )
        obs_b = PublicSignalObservation(
            organization_id="org-1",
            prospect_id="p1",
            signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            source_url="https://apex.com/procurement",
            evidence={"rfp_title": "Cybersecurity Audit RFP", "matched_rule": "explicit_rfp_solicitation"},
        )
        assert obs_a.fingerprint != obs_b.fingerprint

    def test_closed_or_unknown_rfp_rejected_for_buying_intent_activation(self):
        policy = SignalActivationPolicy()
        obs_closed = PublicSignalObservation(
            organization_id="org-1",
            prospect_id="p1",
            signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            intent_strength=IntentStrength.STRONG.value,
            source_url="https://apex.com/rfp",
            evidence={"snippet": "RFP closed January 2025", "currentness": "closed"},
        )
        ok, sig, reason = policy.evaluate_activation(obs_closed)
        assert ok is False
        assert "requires 'active'" in reason

    def test_past_due_date_rfp_rejected_for_buying_intent_activation(self):
        policy = SignalActivationPolicy()
        now_dt = datetime.now(timezone.utc)
        past_date = (now_dt - timedelta(days=5)).isoformat()

        obs_past = PublicSignalObservation(
            organization_id="org-1",
            prospect_id="p1",
            signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            intent_strength=IntentStrength.STRONG.value,
            source_url="https://apex.com/rfp",
            evidence={"snippet": "RFP marketing", "currentness": "active", "due_date": past_date},
        )
        ok, sig, reason = policy.evaluate_activation(obs_past, now_dt=now_dt)
        assert ok is False
        assert "in the past" in reason

    def test_active_future_due_date_rfp_activates_buying_intent(self):
        policy = SignalActivationPolicy()
        now_dt = datetime.now(timezone.utc)
        future_date = (now_dt + timedelta(days=20)).isoformat()

        obs_future = PublicSignalObservation(
            organization_id="org-1",
            prospect_id="p1",
            signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            intent_strength=IntentStrength.STRONG.value,
            source_url="https://apex.com/rfp",
            evidence={"snippet": "RFP marketing", "currentness": "active", "due_date": future_date, "matched_rule": "rule_1"},
        )
        ok, sig, reason = policy.evaluate_activation(obs_future, now_dt=now_dt)
        assert ok is True
        assert sig is not None
        assert sig.category == SignalCategory.BUYING_INTENT.value

    def test_source_reliability_provenance_scoring(self):
        assert SourceReliability.get_weight("official_company_site") == 1.0
        assert SourceReliability.get_weight("reputable_news") == 0.85
        assert SourceReliability.get_weight("search_snippet_only") == 0.50

    def test_currentness_transition_active_to_closed_deactivates_signal(self, repos):
        org = repos["org"].save(Organization(name="Org Trans", slug="org-trans"))
        camp = repos["camp"].save(org.id, Campaign(name="Camp Trans", status=CampaignStatus.ACTIVE))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Apex", website_url="https://apex.com"))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p.id))

        prio_service = ProspectPriorityService(
            priority_repo=repos["prio"],
            prospect_repo=repos["prospect"],
            campaign_repo=camp.id,
            intel_repo=repos["intel"],
            enrichment_repo=repos["enrich"],
            research_run_repo=repos["rr"],
        )

        html_active = """<html><body><h1>Procurement</h1><p>Request for Proposal - Digital Marketing Agency. Proposals due November 30, 2026.</p></body></html>"""
        prov_active = OfficialWebsiteSignalProvider(scraper=MockHtmlScraper({"https://apex.com": html_active}))
        service_active = PublicSignalMonitorService(
            observation_repo=repos["obs"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            research_run_repo=repos["rr"],
            priority_service=prio_service,
            providers=[prov_active],
        )
        res1 = service_active.monitor_prospect(org.id, p.id, recompute_priority=True)
        assert res1.signals_activated == 1
        assert len(repos["prospect"].list_signals(org.id, p.id)) == 1

        html_closed = """<html><body><h1>Procurement</h1><p>Archived Request for Proposal: Digital Marketing. Submissions are closed.</p></body></html>"""
        prov_closed = OfficialWebsiteSignalProvider(scraper=MockHtmlScraper({"https://apex.com": html_closed}))
        service_closed = PublicSignalMonitorService(
            observation_repo=repos["obs"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            research_run_repo=repos["rr"],
            priority_service=prio_service,
            providers=[prov_closed],
        )
        res2 = service_closed.monitor_prospect(org.id, p.id, recompute_priority=True)
        assert res2.signals_expired == 1
        assert len(repos["prospect"].list_signals(org.id, p.id)) == 0
        assert len(repos["obs"].list_for_prospect(org.id, p.id)) >= 1


class TestPublicSignalMonitorServiceAndTenancyP7:
    def test_full_signal_monitor_lifecycle(self, repos):
        org = repos["org"].save(Organization(name="Org Monitor", slug="org-mon"))
        camp = repos["camp"].save(org.id, Campaign(name="Camp Mon"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Apex", website_url="https://apex.com"))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p.id))

        html = """
        <html><body>
        <h1>Procurement</h1>
        <p>Request for Proposal - Digital Marketing Agency</p>
        <p>Proposals due November 30, 2026. Currently seeking vendors immediately.</p>
        </body></html>
        """
        provider = OfficialWebsiteSignalProvider(scraper=MockHtmlScraper({"https://apex.com": html}))
        service = PublicSignalMonitorService(
            observation_repo=repos["obs"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            research_run_repo=repos["rr"],
            providers=[provider],
        )

        res = service.monitor_prospect(org.id, p.id)
        assert res.observations_found == 2
        assert res.signals_activated >= 1

    def test_tenant_isolation_on_observations(self, repos):
        org_a = repos["org"].save(Organization(name="Org A", slug="org-obs-a"))
        org_b = repos["org"].save(Organization(name="Org B", slug="org-obs-b"))
        p_a = repos["prospect"].save_prospect(org_a.id, Prospect(name="Prospect A"))

        obs_repo = repos["obs"]
        obs = PublicSignalObservation(
            organization_id=org_a.id,
            prospect_id=p_a.id,
            signal_type=SignalType.HIRING_MARKETING.value,
            source_url="https://a.com",
        )
        obs_repo.save(org_a.id, obs)

        with pytest.raises(TenantAccessError):
            obs_repo.list_for_prospect(org_b.id, p_a.id)

    def test_batch_failure_isolation_and_research_run_lifecycle(self, repos):
        org = repos["org"].save(Organization(name="Org Batch Mon", slug="org-batch-mon"))
        camp = repos["camp"].save(org.id, Campaign(name="Camp Batch Mon"))

        p1 = repos["prospect"].save_prospect(org.id, Prospect(name="P1", website_url="https://p1.com"))
        p2 = repos["prospect"].save_prospect(org.id, Prospect(name="P2", website_url="https://p2.com"))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p1.id))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p2.id))

        provider = OfficialWebsiteSignalProvider(scraper=MockHtmlScraper({"https://p1.com": "<html><body>careers hiring marketing manager</body></html>"}))
        service = PublicSignalMonitorService(
            observation_repo=repos["obs"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            research_run_repo=repos["rr"],
            providers=[provider],
        )

        res = service.monitor_campaign(org.id, camp.id)
        assert res["status"] == "completed"
        assert res["successful_count"] == 2

        run = repos["rr"].get_by_id(org.id, res["research_run_id"])
        assert run.run_type == "signal_monitoring"
        assert run.status == "completed"

    def test_recommend_signal_monitor_plan(self, repos):
        org = repos["org"].save(Organization(name="Org Plan", slug="org-plan"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Apex", website_url="https://apex.com"))

        service = PublicSignalMonitorService(
            observation_repo=repos["obs"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            research_run_repo=repos["rr"],
        )

        plan = service.recommend_monitor_plan(org.id, p.id)
        assert plan.recommended_interval_days == 14
        assert len(plan.provider_names) >= 1
