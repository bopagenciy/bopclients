"""Comprehensive unit test suite for BopClients P8 External Public Signal Providers & P8.2 Audit Closure."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.signal import Signal
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.enums import CampaignStatus, SignalType, SignalCategory, IntentStrength
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.signal_provider import OfficialWebsiteSignalProvider
from bopclients.application.providers.procurement_provider import GovernmentProcurementProvider, ProspectSourceMatch, MatchResult
from bopclients.application.providers.news_provider import PublicNewsSignalProvider
from bopclients.application.provider_registry import PublicSignalProviderRegistry, ProviderApplicabilityPolicy
from bopclients.application.signal_activation_policy import SignalActivationPolicy, SourceReliability
from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.prospect_priority_service import ProspectPriorityService
from bopclients.application.signal_monitor_dto import ProviderValidationLevel
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


class TestPublicSignalProviderRegistry:
    def test_registry_registration_and_lookup(self):
        reg = PublicSignalProviderRegistry()
        p_web = OfficialWebsiteSignalProvider()
        p_proc = GovernmentProcurementProvider(api_key="test_key")

        reg.register(p_web)
        reg.register(p_proc)

        assert len(reg.list_all()) == 2
        assert reg.get("official_website") == p_web
        assert reg.get("government_procurement") == p_proc

    def test_filter_providers_by_capability(self):
        reg = PublicSignalProviderRegistry()
        reg.register(OfficialWebsiteSignalProvider())
        reg.register(GovernmentProcurementProvider(api_key="key"))
        reg.register(PublicNewsSignalProvider(search_backend=object()))

        rfp_provs = reg.for_capability("supports_rfp")
        news_provs = reg.for_capability("supports_company_news")

        assert len(rfp_provs) == 2
        assert len(news_provs) == 1
        assert news_provs[0].provider_name == "public_news"

    def test_applicability_policy_commercial_vs_government_prospect(self):
        p_proc = GovernmentProcurementProvider(api_key="key")

        p_comm = Prospect(name="Miami Dental Clinic", website_url="https://miamidental.com", industry="healthcare")
        app_comm, reason_comm = ProviderApplicabilityPolicy.is_applicable(p_proc, p_comm, country="US")
        assert app_comm is False
        assert "only applicable to verified public sector/government entities" in reason_comm

        p_gov = Prospect(name="Department of Veterans Affairs", website_url="https://va.gov", industry="government")
        app_gov, _ = ProviderApplicabilityPolicy.is_applicable(p_proc, p_gov, country="US")
        assert app_gov is True


class TestGovernmentProcurementProvider:
    def test_unconfigured_procurement_provider_returns_skipped_status(self):
        prov = GovernmentProcurementProvider(api_key="")
        assert prov.capabilities.configured is False
        assert prov.capabilities.validation_level == ProviderValidationLevel.SKIPPED_NO_KEY.value

        p = Prospect(id="p1", organization_id="org-1", name="Apex")
        res = prov.discover_signals(p)
        assert len(res.observations) == 0
        assert any("not configured" in w for w in res.warnings)

    def test_sam_api_key_leak_protection_on_exceptions_and_metadata(self):
        secret_key = "super-secret-sam-key"
        prov = GovernmentProcurementProvider(api_key=secret_key)

        sanitized_str = prov._sanitize_secret(f"HTTP 403 Forbidden using key {secret_key}")
        assert secret_key not in sanitized_str
        assert "[REDACTED_API_KEY]" in sanitized_str

        class FailingClient:
            def search_solicitations(self, company_name):
                raise Exception(f"Failed connection with api_key={secret_key}")

        prov_failing = GovernmentProcurementProvider(api_key=secret_key, client=FailingClient())
        p = Prospect(id="p1", organization_id="org-1", name="Department of Veterans Affairs")

        res = prov_failing.discover_signals(p)
        assert len(res.errors) == 1
        assert secret_key not in res.errors[0]
        assert "[REDACTED_API_KEY]" in res.errors[0]

    def test_strict_issuer_match_governance(self):
        p = Prospect(name="Department of Veterans Affairs", website_url="https://va.gov")

        # 1. Exact match -> MATCHED
        m1 = ProspectSourceMatch.match_issuer(p, "Department of Veterans Affairs")
        assert m1.status == "MATCHED" and m1.match_confidence == 1.0

        # 2. Partial name overlap -> AMBIGUOUS (cannot activate strong intent alone)
        m2 = ProspectSourceMatch.match_issuer(p, "Department of Veterans Affairs Medical Center")
        assert m2.status == "AMBIGUOUS" and m2.match_confidence == 0.50

        # 3. Vendor/Awardee role -> REJECTED
        m3 = ProspectSourceMatch.match_issuer(p, "Department of Veterans Affairs", prospect_role="awardee")
        assert m3.status == "REJECTED" and m3.match_confidence == 0.0

    def test_active_solicitation_creates_strong_buying_intent(self):
        class MockClient:
            def search_solicitations(self, company_name):
                return [{
                    "solicitationNumber": "SOL-2026-100",
                    "title": "Request for Proposal - Cloud Infrastructure",
                    "organizationName": "Department of Veterans Affairs",
                    "source_url": "https://va.gov/sol-100",
                    "active": "true",
                    "responseDeadLine": "2026-12-31",
                    "prospect_role": "issuer",
                }]

        prov = GovernmentProcurementProvider(api_key="key", client=MockClient())
        p = Prospect(id="p1", organization_id="org-1", name="Department of Veterans Affairs", website_url="https://va.gov", industry="government")

        res = prov.discover_signals(p)
        assert len(res.observations) == 1
        obs = res.observations[0]

        assert obs.signal_type == SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value
        assert obs.category == SignalCategory.BUYING_INTENT.value
        assert obs.intent_strength == IntentStrength.STRONG.value
        assert obs.external_id == "SOL-2026-100"
        assert obs.evidence["currentness"] == "active"


class TestPublicNewsSignalProvider:
    def test_configured_semantics_without_search_backend(self):
        prov_no_backend = PublicNewsSignalProvider(search_backend=None)
        assert prov_no_backend.capabilities.configured is False
        assert prov_no_backend.capabilities.validation_level == ProviderValidationLevel.SKIPPED_NO_BACKEND.value

        prov_backend = PublicNewsSignalProvider(search_backend=object())
        assert prov_backend.capabilities.configured is True

    def test_news_query_generation_budget(self):
        prov = PublicNewsSignalProvider()
        queries = prov._generate_search_queries("Apex Medical")

        assert len(queries) <= prov.QUERY_BUDGET_PER_PROSPECT
        assert any("expansion" in q for q in queries)
        assert any("funding" in q for q in queries)

    def test_trusted_vs_unknown_news_source_reliability(self):
        prov = PublicNewsSignalProvider()

        s_type1, conf1 = prov._determine_source_trust("https://bizjournals.com/news/article1")
        s_type2, conf2 = prov._determine_source_trust("https://unknown-blog.xyz/post")

        assert s_type1 == "reputable_news" and conf1 == 0.85
        assert s_type2 == "unknown_news" and conf2 == 0.60

    def test_article_prospect_content_matching_rejection(self):
        class MockNewsBackend:
            def search(self, query):
                return [{
                    "url": "https://bizjournals.com/unrelated-news",
                    "title": "Unrelated Company Expands",
                    "content": "Unrelated Tech Corp opened a new location in Miami.",
                }]

        prov = PublicNewsSignalProvider(search_backend=MockNewsBackend())
        p = Prospect(id="p1", organization_id="org-1", name="Apex Medical Center")

        res = prov.discover_signals(p)
        assert len(res.observations) == 0
        assert any("Prospect 'Apex Medical Center' not mentioned" in w for w in res.warnings)


class TestSemanticEventIdentityAndFundingP82:
    def test_funding_semantic_event_key_stability_with_unknown_and_known_amount(self):
        obs1 = PublicSignalObservation(
            prospect_id="p1",
            signal_type="new_funding",
            published_at="2026-08-10T12:00:00Z",
            evidence={"funding_round": "Series A", "matched_rule": "news_funding_event"},
        )

        obs2 = PublicSignalObservation(
            prospect_id="p1",
            signal_type="new_funding",
            published_at="2026-08-10T15:00:00Z",
            evidence={"funding_round": "Series A", "funding_amount": "$25 million", "matched_rule": "news_funding_event"},
        )

        assert obs1.compute_semantic_event_key() == obs2.compute_semantic_event_key()
        assert obs1.compute_semantic_event_key() == "new_funding:p1:series_a:2026-08"

        # Content fingerprints differ due to amount discovery
        assert obs1.compute_content_fingerprint() != obs2.compute_content_fingerprint()

    def test_funding_distinct_rounds_separated(self):
        obs_series_a = PublicSignalObservation(
            prospect_id="p1",
            signal_type="new_funding",
            published_at="2025-05-10T12:00:00Z",
            evidence={"funding_round": "Series A", "funding_amount": "$10 million"},
        )

        obs_series_b = PublicSignalObservation(
            prospect_id="p1",
            signal_type="new_funding",
            published_at="2026-08-10T12:00:00Z",
            evidence={"funding_round": "Series B", "funding_amount": "$25 million"},
        )

        assert obs_series_a.compute_semantic_event_key() != obs_series_b.compute_semantic_event_key()


class TestSemanticEventDedupeAndPriorityP8:
    def test_same_semantic_event_corroborated_different_events_separated(self):
        policy = SignalActivationPolicy()

        obs_orlando1 = PublicSignalObservation(
            id="obs-1",
            prospect_id="p1",
            provider="official_website",
            signal_type=SignalType.OPENED_NEW_LOCATION.value,
            category=SignalCategory.COMPANY_ACTIVITY.value,
            confidence=0.85,
            source_url="https://apex.com/news",
            evidence={"location_name": "Orlando"},
        )
        obs_orlando2 = PublicSignalObservation(
            id="obs-2",
            prospect_id="p1",
            provider="public_news",
            signal_type=SignalType.OPENED_NEW_LOCATION.value,
            category=SignalCategory.COMPANY_ACTIVITY.value,
            confidence=0.90,
            source_url="https://bizjournals.com/apex-orlando",
            evidence={"location_name": "Orlando"},
        )

        obs_miami = PublicSignalObservation(
            id="obs-3",
            prospect_id="p1",
            provider="public_news",
            signal_type=SignalType.OPENED_NEW_LOCATION.value,
            category=SignalCategory.COMPANY_ACTIVITY.value,
            confidence=0.90,
            source_url="https://bizjournals.com/apex-miami",
            evidence={"location_name": "Miami"},
        )

        assert obs_orlando1.compute_semantic_event_key() == obs_orlando2.compute_semantic_event_key()
        assert obs_orlando1.compute_semantic_event_key() != obs_miami.compute_semantic_event_key()

        ok, sig, _ = policy.evaluate_activation(obs_orlando2, supporting_observations=[obs_orlando1, obs_miami])
        assert ok is True
        assert sig.evidence["corroboration_count"] == 2

    def test_unconfigured_provider_emits_warning_without_failing_service(self, repos):
        org = repos["org"].save(Organization(name="Org P8", slug="org-p8"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Apex", website_url="https://apex.com"))

        p_unconfigured = GovernmentProcurementProvider(api_key="")
        p_website = OfficialWebsiteSignalProvider()

        registry = PublicSignalProviderRegistry()
        registry.register(p_unconfigured)
        registry.register(p_website)

        service = PublicSignalMonitorService(
            observation_repo=repos["obs"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            research_run_repo=repos["rr"],
            registry=registry,
        )

        res = service.monitor_prospect(org.id, p.id)
        assert any("PROVIDER_NOT_CONFIGURED" in w for w in res.warnings)
        assert "government_procurement" in res.provider_results
        assert res.provider_results["government_procurement"]["status"] == ProviderValidationLevel.SKIPPED_NO_KEY.value

    def test_priority_score_69_sets_urgent_intent_requirement_met_without_urgent_label(self, repos):
        org = repos["org"].save(Organization(name="Org P8 Audit", slug="org-p8-audit"))
        camp = repos["camp"].save(org.id, Campaign(name="Camp Audit"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Department of Veterans Affairs", website_url="https://va.gov", industry="government"))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p.id))

        repos["prospect"].save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p.id, score=45))

        prio_service = ProspectPriorityService(
            priority_repo=repos["prio"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            intel_repo=repos["intel"],
            enrichment_repo=repos["enrich"],
            research_run_repo=repos["rr"],
        )

        obs_rfp = PublicSignalObservation(
            id="obs-rfp",
            organization_id=org.id,
            prospect_id=p.id,
            provider="government_procurement",
            signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            intent_strength=IntentStrength.STRONG.value,
            confidence=0.95,
            source_url="https://va.gov/rfp",
            evidence={"snippet": "RFP IT System", "currentness": "active", "due_date": "2026-12-31"},
        )

        repos["obs"].save(org.id, obs_rfp)
        policy = SignalActivationPolicy()
        _, sig_obj, _ = policy.evaluate_activation(obs_rfp)
        repos["prospect"].add_signal(org.id, sig_obj)

        prio = prio_service.prioritize_prospect(org.id, camp.id, p.id)

        assert prio.priority_score == 54
        assert prio.priority_label.upper() == "HIGH"
        assert prio.data.get("has_recent_verified_buying_intent") is True
        assert prio.data.get("urgent_gate_applied") is False

    def test_tenant_boundary_isolation_on_multi_provider_monitoring(self, repos):
        org_a = repos["org"].save(Organization(name="Org A", slug="org-a"))
        org_b = repos["org"].save(Organization(name="Org B", slug="org-b"))

        p_a = repos["prospect"].save_prospect(org_a.id, Prospect(name="Prospect A"))
        service = PublicSignalMonitorService(
            observation_repo=repos["obs"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            research_run_repo=repos["rr"],
        )

        with pytest.raises(TenantAccessError):
            service.monitor_prospect(org_b.id, p_a.id)
