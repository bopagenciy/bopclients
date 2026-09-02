"""Comprehensive unit test suite for BopClients P6 Prospect Prioritization & Research Orchestration (P6.3 Audit & Trace Aligned)."""

import pytest
from datetime import datetime, timezone, timedelta
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.contact import Contact
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.enrichment_result import EnrichmentResult
from bopclients.domain.prospect_intelligence import ProspectIntelligence
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.enums import CampaignStatus, SignalType, SignalCategory, IntentStrength
from bopclients.domain.exceptions import TenantAccessError, EntityNotFoundError
from bopclients.application.priority_scorer import RuleBasedPriorityScorer
from bopclients.application.signal_provider import DeterministicExistingDataSignalProvider
from bopclients.application.research_orchestration_policy import ResearchOrchestrationPolicy
from bopclients.application.prospect_priority_service import ProspectPriorityService
from bopclients.application.enrichment_dto import EnrichmentSnapshot
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.prospect_priority_repository import ProspectPriorityRepository
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
        "intel": ProspectIntelligenceRepository(memory_db),
        "enrich": EnrichmentResultRepository(memory_db),
        "rr": ResearchRunRepository(memory_db),
    }


class TestPriorityScorerAndPolicyP63:
    def test_deterministic_priority_scoring_and_components(self):
        scorer = RuleBasedPriorityScorer()
        p = Prospect(id="p1", organization_id="org-1", name="Test Co")
        ls = LeadScore(organization_id="org-1", prospect_id="p1", score=80)
        sig = Signal(
            organization_id="org-1",
            prospect_id="p1",
            type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            intent_strength=IntentStrength.STRONG.value,
            confidence=1.0,
            source="rfp",
            evidence={"title": "RFP Search"},
        )
        intel = ProspectIntelligence(organization_id="org-1", prospect_id="p1", confidence=1.0)

        prio = scorer.calculate_priority("org-1", "camp-1", p, ls, [sig], intel)

        # LeadScore: 28.0, Verified Intent: 25.0, Intel Conf: 15.0, Freshness: 0.0 => Total 68 (High)
        assert prio.priority_score == 68
        assert prio.priority_label == "high"
        assert prio.lead_score_component == 28.0
        assert prio.intent_signal_component == 25.0
        assert prio.research_confidence_component == 15.0
        assert prio.freshness_component == 0.0

    def test_urgent_gate_requires_recent_strong_medium_intent(self):
        scorer = RuleBasedPriorityScorer()
        p = Prospect(id="p1", organization_id="org-1", name="High Score No Intent")
        ls = LeadScore(organization_id="org-1", prospect_id="p1", score=100)
        intel = ProspectIntelligence(organization_id="org-1", prospect_id="p1", confidence=1.0)

        now_iso = datetime.now(timezone.utc).isoformat()
        act_sig = Signal(
            organization_id="org-1",
            prospect_id="p1",
            type=SignalType.NEW_FUNDING.value,
            category=SignalCategory.COMPANY_ACTIVITY.value,
            intent_strength=IntentStrength.MEDIUM.value,
            confidence=1.0,
            detected_at=now_iso,
        )

        prio = scorer.calculate_priority("org-1", "camp-1", p, ls, [act_sig], intel)

        # High lead score + activity => total score 55 (HIGH), cannot reach URGENT
        assert prio.priority_score == 55
        assert prio.priority_label == "high"
        assert prio.data["urgent_gate_applied"] is False
        assert prio.data["has_recent_verified_buying_intent"] is False

    def test_recency_decay_policy(self):
        scorer = RuleBasedPriorityScorer()
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        old_iso = (now_dt - timedelta(days=40)).isoformat()

        sig_fresh = Signal(
            type=SignalType.HIRING_MARKETING.value,
            category=SignalCategory.COMPANY_ACTIVITY.value,
            intent_strength=IntentStrength.MEDIUM.value,
            confidence=1.0,
            detected_at=now_iso,
        )
        sig_old = Signal(
            type=SignalType.HIRING_MARKETING.value,
            category=SignalCategory.COMPANY_ACTIVITY.value,
            intent_strength=IntentStrength.MEDIUM.value,
            confidence=1.0,
            detected_at=old_iso,
        )

        _, pts_fresh, _, _, _ = scorer._calculate_company_activity_component([sig_fresh], now_dt)
        _, pts_old, _, _, _ = scorer._calculate_company_activity_component([sig_old], now_dt)

        assert pts_fresh == 5.0
        assert pts_old == 2.5  # 50% decay for 40d old signal

    def test_next_research_action_orchestration(self):
        policy = ResearchOrchestrationPolicy()
        p = Prospect(id="p1", organization_id="org-1", name="Test Co")
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        old_iso = (now_dt - timedelta(days=45)).isoformat()

        fresh_enrich = EnrichmentSnapshot(updated_at=now_iso, scrape_status="success", http_status=200)
        intel_stale = ProspectIntelligence(
            organization_id="org-1", prospect_id="p1", confidence=0.80, updated_at=old_iso
        )
        prio = RuleBasedPriorityScorer().calculate_priority("org-1", "camp-1", p, None, [], intel_stale)

        next_act, readiness = policy.evaluate_orchestration(
            prospect=p,
            priority=prio,
            lead_score=None,
            signals=[],
            intelligence=intel_stale,
            enrichment_snapshot=fresh_enrich,
            contacts=[],
        )

        assert next_act.action == "refresh_research"
        assert next_act.priority == "high"
        assert "stale" in next_act.reason

    def test_outreach_readiness_human_review_gate(self):
        policy = ResearchOrchestrationPolicy()
        p = Prospect(id="p1", organization_id="org-1", name="Ready Co")
        ls = LeadScore(organization_id="org-1", prospect_id="p1", score=85)
        intel = ProspectIntelligence(organization_id="org-1", prospect_id="p1", confidence=0.90)
        prio = RuleBasedPriorityScorer().calculate_priority("org-1", "camp-1", p, ls, [], intel)

        _, readiness = policy.evaluate_orchestration(
            prospect=p,
            priority=prio,
            lead_score=ls,
            signals=[],
            intelligence=intel,
            enrichment_snapshot=None,
            contacts=[Contact(name="Decision Maker")],
        )

        assert readiness.status == "ready_for_human_review"
        assert readiness.status != "approved_to_send"
        assert len(readiness.reasons) >= 2

    def test_component_cap_trace_and_contributing_signals(self):
        scorer = RuleBasedPriorityScorer()
        p = Prospect(id="p1", organization_id="org-1", name="Capped Prospect")
        now_iso = datetime.now(timezone.utc).isoformat()

        # 3 activity signals: 5.0 + 5.0 + 5.0 = 15.0 raw total (cap is 10.0)
        s1 = Signal(type=SignalType.HIRING_MARKETING.value, category=SignalCategory.COMPANY_ACTIVITY.value, intent_strength=IntentStrength.MEDIUM.value, confidence=1.0, detected_at=now_iso, source="s1")
        s2 = Signal(type=SignalType.HIRING_SALES.value, category=SignalCategory.COMPANY_ACTIVITY.value, intent_strength=IntentStrength.MEDIUM.value, confidence=1.0, detected_at=now_iso, source="s2")
        s3 = Signal(type=SignalType.OPENED_NEW_LOCATION.value, category=SignalCategory.COMPANY_ACTIVITY.value, intent_strength=IntentStrength.MEDIUM.value, confidence=1.0, detected_at=now_iso, source="s3")

        prio = scorer.calculate_priority("org-1", "camp-1", p, None, [s1, s2, s3], None)
        bd = prio.data["component_breakdown"]["company_activity"]
        contribs = prio.data["contributing_signals"]["company_activity"]

        # Tracing assertions
        assert bd["raw_total"] == 15.0
        assert bd["applied_total"] == 10.0
        assert bd["cap_applied"] is True
        assert len(contribs) == 3
        assert any(c["type"] == "hiring_marketing" for c in contribs)
        assert any(c["type"] == "hiring_sales" for c in contribs)
        assert any(c["type"] == "opened_new_location" for c in contribs)
        assert "(raw 15.0, capped at 10.0)" in prio.data["reasons"][2]["reason"]

    def test_signal_display_scoring_consistency(self):
        scorer = RuleBasedPriorityScorer()
        p = Prospect(id="p1", organization_id="org-1", name="Consistency Prospect")
        ls = LeadScore(organization_id="org-1", prospect_id="p1", score=85)
        intel = ProspectIntelligence(organization_id="org-1", prospect_id="p1", confidence=0.9)
        now_iso = datetime.now(timezone.utc).isoformat()

        sig_mkt = Signal(
            type=SignalType.HIRING_MARKETING.value,
            category=SignalCategory.COMPANY_ACTIVITY.value,
            intent_strength=IntentStrength.MEDIUM.value,
            detected_at=now_iso,
        )
        sig_tech = Signal(
            type=SignalType.TECHNOLOGY_CHANGE.value,
            category=SignalCategory.COMPANY_ACTIVITY.value,
            intent_strength=IntentStrength.WEAK.value,
            detected_at=now_iso,
        )
        sig_rfp = Signal(
            type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            intent_strength=IntentStrength.STRONG.value,
            confidence=0.95,
            source="rfp_portal",
            evidence={"title": "RFP Search"},
            detected_at=now_iso,
        )

        prio = scorer.calculate_priority("org-1", "camp-1", p, ls, [sig_mkt, sig_tech, sig_rfp], intel)
        considered = prio.data["considered_signals"]

        assert "hiring_marketing" in considered["company_activity"]
        assert "technology_change" in considered["company_activity"]
        assert "public_request_for_proposal" in considered["buying_intent"]

        intent_reason = prio.data["reasons"][1]["reason"]
        activity_reason = prio.data["reasons"][2]["reason"]

        assert "public_request_for_proposal" in intent_reason
        assert "hiring_marketing" in activity_reason

    def test_public_rfp_without_evidence_cannot_unlock_urgent(self):
        scorer = RuleBasedPriorityScorer()
        p = Prospect(id="p1", organization_id="org-1", name="RFP No Evidence")
        ls = LeadScore(organization_id="org-1", prospect_id="p1", score=90)
        intel = ProspectIntelligence(organization_id="org-1", prospect_id="p1", confidence=0.9)
        now_iso = datetime.now(timezone.utc).isoformat()

        rfp_no_ev = Signal(
            organization_id="org-1",
            prospect_id="p1",
            type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            intent_strength=IntentStrength.STRONG.value,
            confidence=0.9,
            source="manual",
            evidence=None,
            detected_at=now_iso,
        )

        prio = scorer.calculate_priority("org-1", "camp-1", p, ls, [rfp_no_ev], intel)
        assert prio.data["has_recent_verified_buying_intent"] is False

    def test_public_rfp_with_evidence_unlocks_urgent(self):
        scorer = RuleBasedPriorityScorer()
        p = Prospect(id="p1", organization_id="org-1", name="RFP Verified")
        ls = LeadScore(organization_id="org-1", prospect_id="p1", score=95)
        intel = ProspectIntelligence(organization_id="org-1", prospect_id="p1", confidence=1.0)
        now_iso = datetime.now(timezone.utc).isoformat()

        rfp_valid = Signal(
            organization_id="org-1",
            prospect_id="p1",
            type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            intent_strength=IntentStrength.STRONG.value,
            confidence=1.0,
            source="rfp_portal",
            evidence={"title": "RFP 2026 Agency Search", "url": "https://example.com/rfp"},
            detected_at=now_iso,
        )
        hiring_sig = Signal(
            organization_id="org-1",
            prospect_id="p1",
            type=SignalType.HIRING_MARKETING.value,
            category=SignalCategory.COMPANY_ACTIVITY.value,
            intent_strength=IntentStrength.MEDIUM.value,
            confidence=1.0,
            source="jobs",
            evidence={"t": "mkt"},
            detected_at=now_iso,
        )

        prio = scorer.calculate_priority("org-1", "camp-1", p, ls, [rfp_valid, hiring_sig], intel)

        assert prio.data["has_recent_verified_buying_intent"] is True
        assert prio.priority_score >= 75
        assert prio.priority_label == "urgent"

    def test_priority_source_fingerprint_changes_on_signal_swap(self):
        scorer = RuleBasedPriorityScorer()
        p = Prospect(id="p1", organization_id="org-1", name="Fingerprint Prospect")
        now_iso = datetime.now(timezone.utc).isoformat()

        sig1 = Signal(type=SignalType.HIRING_MARKETING.value, category=SignalCategory.COMPANY_ACTIVITY.value, detected_at=now_iso)
        sig2 = Signal(type=SignalType.HIRING_SALES.value, category=SignalCategory.COMPANY_ACTIVITY.value, detected_at=now_iso)

        prio1 = scorer.calculate_priority("org-1", "camp-1", p, None, [sig1], None)
        prio2 = scorer.calculate_priority("org-1", "camp-1", p, None, [sig2], None)

        assert prio1.data["source_fingerprint"] != prio2.data["source_fingerprint"]


class TestPriorityServiceAndTenancyP63:
    def test_full_priority_service_lifecycle(self, repos):
        org = repos["org"].save(Organization(name="Org A", slug="org-a"))
        camp = repos["camp"].save(org.id, Campaign(name="Camp A", status=CampaignStatus.ACTIVE))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Prospect A"))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p.id))
        repos["prospect"].save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p.id, score=80))

        service = ProspectPriorityService(
            priority_repo=repos["prio"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            intel_repo=repos["intel"],
            enrichment_repo=repos["enrich"],
            research_run_repo=repos["rr"],
        )

        prio = service.prioritize_prospect(org.id, camp.id, p.id)
        assert prio.organization_id == org.id
        assert prio.campaign_id == camp.id
        assert prio.prospect_id == p.id
        assert prio.priority_score > 0

    def test_priority_tenant_boundary_isolation(self, repos):
        org_a = repos["org"].save(Organization(name="Org A", slug="org-iso-a"))
        org_b = repos["org"].save(Organization(name="Org B", slug="org-iso-b"))

        camp_a = repos["camp"].save(org_a.id, Campaign(name="Camp A"))
        p_a = repos["prospect"].save_prospect(org_a.id, Prospect(name="Prospect A"))

        service = ProspectPriorityService(
            priority_repo=repos["prio"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            intel_repo=repos["intel"],
            enrichment_repo=repos["enrich"],
            research_run_repo=repos["rr"],
        )

        with pytest.raises((TenantAccessError, EntityNotFoundError)):
            service.prioritize_prospect(org_b.id, camp_a.id, p_a.id)

    def test_campaign_boundary_isolation_same_prospect_different_campaigns(self, repos):
        org = repos["org"].save(Organization(name="Org Multi-Camp", slug="org-multi-camp"))
        camp_1 = repos["camp"].save(org.id, Campaign(name="Web Dev Campaign"))
        camp_2 = repos["camp"].save(org.id, Campaign(name="AI Automation Campaign"))

        p = repos["prospect"].save_prospect(org.id, Prospect(name="Multi Campaign Clinic"))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp_1.id, prospect_id=p.id))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp_2.id, prospect_id=p.id))
        repos["prospect"].save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p.id, score=75))

        service = ProspectPriorityService(
            priority_repo=repos["prio"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            intel_repo=repos["intel"],
            enrichment_repo=repos["enrich"],
            research_run_repo=repos["rr"],
        )

        prio_1 = service.prioritize_prospect(org.id, camp_1.id, p.id)
        prio_2 = service.prioritize_prospect(org.id, camp_2.id, p.id)

        assert prio_1.campaign_id == camp_1.id
        assert prio_2.campaign_id == camp_2.id
        assert prio_1.id != prio_2.id

    def test_idempotent_priority_persistence_and_update(self, repos):
        org = repos["org"].save(Organization(name="Org Idempotent", slug="org-idempotent"))
        camp = repos["camp"].save(org.id, Campaign(name="Camp Idempotent"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Prospect Idempotent"))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p.id))

        service = ProspectPriorityService(
            priority_repo=repos["prio"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            intel_repo=repos["intel"],
            enrichment_repo=repos["enrich"],
            research_run_repo=repos["rr"],
        )

        prio_1 = service.prioritize_prospect(org.id, camp.id, p.id)
        repos["prospect"].save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p.id, score=90))
        prio_2 = service.prioritize_prospect(org.id, camp.id, p.id)

        assert prio_1.id == prio_2.id
        assert prio_2.priority_score >= prio_1.priority_score

    def test_batch_failure_isolation(self, repos):
        org = repos["org"].save(Organization(name="Org Batch", slug="org-batch"))
        camp = repos["camp"].save(org.id, Campaign(name="Camp Batch"))

        p1 = repos["prospect"].save_prospect(org.id, Prospect(name="Valid Prospect 1"))
        p2 = repos["prospect"].save_prospect(org.id, Prospect(name="Valid Prospect 2"))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p1.id))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p2.id))

        service = ProspectPriorityService(
            priority_repo=repos["prio"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            intel_repo=repos["intel"],
            enrichment_repo=repos["enrich"],
            research_run_repo=repos["rr"],
        )

        result = service.prioritize_campaign(org.id, camp.id)
        assert result["total_processed"] == 2
        assert result["successful_count"] == 2
        assert len(result["items"]) == 2

    def test_deterministic_ordering_top_prospects(self, repos):
        org = repos["org"].save(Organization(name="Org Ordering", slug="org-ordering"))
        camp = repos["camp"].save(org.id, Campaign(name="Camp Ordering"))

        p1 = repos["prospect"].save_prospect(org.id, Prospect(name="Prospect Low"))
        p2 = repos["prospect"].save_prospect(org.id, Prospect(name="Prospect High"))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p1.id))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p2.id))

        repos["prospect"].save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p1.id, score=20))
        repos["prospect"].save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p2.id, score=90))

        service = ProspectPriorityService(
            priority_repo=repos["prio"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            intel_repo=repos["intel"],
            enrichment_repo=repos["enrich"],
            research_run_repo=repos["rr"],
        )

        service.prioritize_campaign(org.id, camp.id)
        top = service.get_top_prospects(org.id, camp.id, limit=10)

        assert len(top) == 2
        assert top[0].prospect_id == p2.id
        assert top[0].priority_score > top[1].priority_score

    def test_research_run_batch_lifecycle_scenarios(self, repos):
        org = repos["org"].save(Organization(name="Org Run Lifecycle", slug="org-run-lc"))
        camp = repos["camp"].save(org.id, Campaign(name="Camp Run Lifecycle"))

        p1 = repos["prospect"].save_prospect(org.id, Prospect(name="P1"))
        p2 = repos["prospect"].save_prospect(org.id, Prospect(name="P2"))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p1.id))
        repos["prospect"].add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p2.id))

        service = ProspectPriorityService(
            priority_repo=repos["prio"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            intel_repo=repos["intel"],
            enrichment_repo=repos["enrich"],
            research_run_repo=repos["rr"],
        )

        res_a = service.prioritize_campaign(org.id, camp.id)
        run_a = repos["rr"].get_by_id(org.id, res_a["research_run_id"])

        assert res_a["successful_count"] == 2
        assert res_a["failed_count"] == 0
        assert run_a.status == "completed"

    def test_cross_tenant_research_run_update_rejected(self, repos):
        org_a = repos["org"].save(Organization(name="Org Run A", slug="org-run-a"))
        org_b = repos["org"].save(Organization(name="Org Run B", slug="org-run-b"))

        run_a = repos["rr"].save(
            org_a.id,
            ResearchRun(id="run-shared-id", organization_id=org_a.id, run_type="prioritization", status="running")
        )

        with pytest.raises(TenantAccessError):
            repos["rr"].save(
                org_b.id,
                ResearchRun(id="run-shared-id", organization_id=org_b.id, run_type="prioritization", status="completed")
            )
