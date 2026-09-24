"""Phase P30.5G.5H.3C: Discovery Preview Funnel Diagnostics and EPS/IPS Boundary Audit.

Strict offline verification suite covering:
1. EPS / IPS boundary regex analysis (standalone vs substring).
2. Ephemeral aggregate funnel metrics and mathematical accounting invariants.
3. Scenario matrix (zero results, all rejected, missing fields, directories retained, mixed results).
4. Backward compatibility of DiscoveryPreviewResponse with and without diagnostics.
5. Zero network socket calls, zero database writes.
"""

import pytest
import re
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock

from bopclients.domain.candidate_qualification import (
    CandidateQualificationStatus,
    EntityArchetype,
    GeographicEvidenceStatus,
)
from bopclients.application.search_dto import DiscoveryTask, SearchPlan
from bopclients.application.discovery.candidate_classifier import (
    OrganizationCandidateClassifier,
    CandidateClassificationRequest,
    CandidateClassificationStatus,
)
from bopclients.application.discovery.candidate_qualifier import (
    OrganizationCandidateQualifier,
)
from bopclients.infrastructure.providers.web_search_provider import (
    WebSearchDiscoveryProvider,
    IWebSearchTransport,
)
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.api.schemas.discovery import (
    DiscoveryPreviewResponse,
    DiscoveryPreviewDiagnostics,
    DiscoveryCandidateSummary,
)


class MockWebSearchTransport(IWebSearchTransport):
    """Deterministic mock transport returning canned web results."""

    def __init__(self, canned_results: Optional[List[Dict[str, Any]]] = None, raise_error: bool = False):
        self.canned_results = canned_results if canned_results is not None else []
        self.raise_error = raise_error
        self.calls: List[Dict[str, Any]] = []

    def search(
        self,
        query: str,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        count: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        self.calls.append({"query": query, "country": country, "count": count})
        if self.raise_error:
            raise RuntimeError("Simulated provider connection failure")
        return {
            "query": {"original": query, "more_results_available": False},
            "web": {"results": list(self.canned_results)},
        }


# =====================================================================
# Section 1: EPS / IPS Boundary Audit Tests
# =====================================================================

class TestEpsIpsBoundaryAudit:
    """Verify that 'eps' and 'ips' match strictly on word boundaries and not as arbitrary substrings."""

    def test_eps_ips_not_matched_as_substrings_in_legitimate_words(self):
        """Audit: legitimate Spanish and medical words containing 'eps' or 'ips' do NOT trigger negative exclusion."""
        classifier = OrganizationCandidateClassifier()

        legitimate_eps_ips_words = [
            # Words containing 'eps':
            ("Sociedad Colombiana de Cirujanos con Fórceps", "fórceps"),
            ("Asociación Médica para el Estudio de la Sepsis", "sepsis"),
            ("Colegio Médico de Rehabilitación de Bíceps y Tríceps", "bíceps"),
            ("Sociedad de Médicos de la Diócesis Episcopal", "episcopal"),
            ("Asociación Científica Epsilon de Investigadores Médicos", "epsilon"),
            # Words containing 'ips':
            ("Sociedad Colombiana de Biopsia y Citopatología", "biopsia"),
            ("Asociación Médica de Neurobiología y Sinapsis", "sinapsis"),
            ("Sociedad Médica de Patología y Autopsia Forense", "autopsia"),
            ("Colegio Médico de Neurología y Epilepsia", "epilepsia"),
            ("Asociación de Médicos del Valle en tiempos del Apocalipsis", "apocalipsis"),
        ]

        for org_name, test_word in legitimate_eps_ips_words:
            req = CandidateClassificationRequest(
                name=org_name,
                target_intent="medical_association",
                negative_keywords=["hospital", "clinica", "clínica", "consultorio", "eps", "ips"],
                raw_metadata={
                    "title": org_name,
                    "description": f"Organización científica especializada en {test_word} en Cali.",
                    "url": "https://sociedad-ejemplo.org",
                },
            )

            decision = classifier.classify(req)
            # Must NOT be excluded by negative keyword 'eps' or 'ips'
            assert decision.reason != "EXCLUDED_BY_NEGATIVE_KEYWORD (eps)", (
                f"False positive 'eps' keyword match on word '{test_word}' in '{org_name}'"
            )
            assert decision.reason != "EXCLUDED_BY_NEGATIVE_KEYWORD (ips)", (
                f"False positive 'ips' keyword match on word '{test_word}' in '{org_name}'"
            )

    def test_standalone_eps_ips_correctly_triggers_exclusion(self):
        """Audit: standalone 'EPS' or 'IPS' triggers negative keyword exclusion as expected."""
        classifier = OrganizationCandidateClassifier()

        # Standalone EPS in snippet
        req_eps = CandidateClassificationRequest(
            name="Sociedad Colombiana de Pediatría",
            target_intent="medical_association",
            negative_keywords=["hospital", "clinica", "clínica", "consultorio", "eps", "ips"],
            raw_metadata={
                "title": "Sociedad Colombiana de Pediatría",
                "description": "Red de atención vinculada directamente a EPS en Colombia.",
                "url": "https://scp.org",
            },
        )
        decision_eps = classifier.classify(req_eps)
        assert decision_eps.is_valid is False
        assert decision_eps.reason == "EXCLUDED_BY_NEGATIVE_KEYWORD (eps)"

        # Standalone IPS in snippet
        req_ips = CandidateClassificationRequest(
            name="Sociedad Colombiana de Cardiología",
            target_intent="medical_association",
            negative_keywords=["hospital", "clinica", "clínica", "consultorio", "eps", "ips"],
            raw_metadata={
                "title": "Sociedad Colombiana de Cardiología",
                "description": "Directorio de sedes de IPS cardiológicas autorizadas.",
                "url": "https://scc.org",
            },
        )
        decision_ips = classifier.classify(req_ips)
        assert decision_ips.is_valid is False
        assert decision_ips.reason == "EXCLUDED_BY_NEGATIVE_KEYWORD (ips)"


# =====================================================================
# Section 2: Preview Funnel Diagnostics and Accounting Invariants
# =====================================================================

class TestPreviewFunnelDiagnostics:
    """Verify ephemeral aggregate funnel diagnostics across scenarios."""

    @pytest.fixture
    def task(self):
        return DiscoveryTask(
            id="t_diag_1",
            provider="web_search",
            query="asociaciones medicas cientificas cali",
            city="Cali",
            region="Valle del Cauca",
            country="CO",
            limit=5,
            category="medical_association",
            negative_keywords=["hospital", "clinica", "clínica", "consultorio", "eps", "ips"],
            metadata={"organization_id": "test_org"},
        )

    def test_a_provider_returns_zero_results(self, task):
        """Scenario A: Provider returns empty results array."""
        transport = MockWebSearchTransport(canned_results=[])
        provider = WebSearchDiscoveryProvider(
            transport=transport,
            enabled=True,
            authorized_tenants={"test_org"},
        )

        discovered = provider.discover(task)
        assert len(discovered) == 0

        diag = task.metadata.get("diagnostics")
        assert diag is not None
        assert diag["provider_results_received"] == 0
        assert diag["results_missing_required_fields"] == 0
        assert diag["results_rejected_by_classifier"] == 0
        assert diag["results_accepted_by_classifier"] == 0
        assert diag["directory_candidates_retained"] == 0
        assert diag["candidates_returned_to_preview"] == 0
        assert diag["rejection_reasons"] == {}

    def test_b_all_provider_results_rejected_by_classifier(self, task):
        """Scenario B: 5 results returned, all rejected by classifier with categorized reasons."""
        canned = [
            # 1. Facility prefix
            {
                "title": "Clínica Imbanaco - Especialistas Médicos",
                "url": "https://imbanaco.com",
                "description": "Atención médica de alta complejidad en Cali.",
            },
            # 2. Negative keyword EPS
            {
                "title": "Sociedad de Cirugía de Cali",
                "url": "https://cirugia-cali.org",
                "description": "Atención especializada para usuarios de EPS Sanitas y Sura.",
            },
            # 3. Not an association (missing organization marker)
            {
                "title": "Médicos Especialistas en Cali | Portal de Salud",
                "url": "https://portalmedicoscali.com",
                "description": "Directorio independiente de doctores en Cali.",
            },
            # 4. Unverified medical specialization
            {
                "title": "Asociación de Profesionales de Colombia",
                "url": "https://profesionales.org.co",
                "description": "Asociación gremial sin especialidad médica.",
            },
            # 5. Negative keyword consultorio
            {
                "title": "Sociedad Médica de Dermatología",
                "url": "https://dermomedicos.org",
                "description": "Directorio para solicitar cita en consultorio particular.",
            },
        ]

        transport = MockWebSearchTransport(canned_results=canned)
        provider = WebSearchDiscoveryProvider(
            transport=transport,
            enabled=True,
            authorized_tenants={"test_org"},
        )

        discovered = provider.discover(task)
        assert len(discovered) == 0

        diag = task.metadata.get("diagnostics")
        assert diag is not None
        assert diag["provider_results_received"] == 5
        assert diag["results_missing_required_fields"] == 0
        assert diag["results_rejected_by_classifier"] == 5
        assert diag["results_accepted_by_classifier"] == 0
        assert diag["directory_candidates_retained"] == 0
        assert diag["candidates_returned_to_preview"] == 0

        # Mathematical consistency
        reasons = diag["rejection_reasons"]
        assert sum(reasons.values()) == diag["results_rejected_by_classifier"]
        assert reasons.get("EXCLUDED_FACILITY") == 1
        assert reasons.get("NEGATIVE_KEYWORD_MATCH") == 2
        assert reasons.get("MISSING_ORGANIZATION_MARKER") == 1
        assert reasons.get("MISSING_SECTOR_MATCH") == 1

    def test_c_missing_required_fields_tracked_separately(self, task):
        """Scenario C: Items missing title or URL are accounted in results_missing_required_fields, not classifier."""
        canned = [
            {"title": "", "url": "https://empty-title.org", "description": "Snippet"},
            {"title": "Valid Society", "url": "", "description": "Snippet"},
            {
                "title": "Sociedad Colombiana de Pediatría Regional Valle",
                "url": "https://scpvalle.org",
                "description": "Sitio oficial de pediatras en Cali.",
            },
        ]

        transport = MockWebSearchTransport(canned_results=canned)
        provider = WebSearchDiscoveryProvider(
            transport=transport,
            enabled=True,
            authorized_tenants={"test_org"},
        )

        discovered = provider.discover(task)
        assert len(discovered) == 1

        diag = task.metadata.get("diagnostics")
        assert diag is not None
        assert diag["provider_results_received"] == 3
        assert diag["results_missing_required_fields"] == 2
        assert diag["results_rejected_by_classifier"] == 0
        assert diag["results_accepted_by_classifier"] == 1
        assert diag["candidates_returned_to_preview"] == 1

        # Accounting invariant
        assert (
            diag["provider_results_received"]
            == diag["results_missing_required_fields"]
            + diag["results_rejected_by_classifier"]
            + diag["results_accepted_by_classifier"]
        )

    def test_d_directory_retained_as_search_match_tracked(self, task):
        """Scenario D: Valid directory is accepted by classifier and tracked in directory_candidates_retained."""
        canned = [
            {
                "title": "Sociedades Afiliadas - Academia Nacional de Medicina de Colombia",
                "url": "https://anmedcolombia.org.co/sociedades-afiliadas/",
                "description": "Relación de Sociedades Afiliadas a la Academia. Capítulo Valle - Cali.",
            }
        ]

        transport = MockWebSearchTransport(canned_results=canned)
        provider = WebSearchDiscoveryProvider(
            transport=transport,
            enabled=True,
            authorized_tenants={"test_org"},
        )

        discovered = provider.discover(task)
        assert len(discovered) == 1

        biz = discovered[0]
        assert biz.raw_data["qualification_status"] == CandidateQualificationStatus.SEARCH_MATCH.value
        assert biz.raw_data["entity_archetype"] == EntityArchetype.DIRECTORY_LISTING.value

        diag = task.metadata.get("diagnostics")
        assert diag is not None
        assert diag["provider_results_received"] == 1
        assert diag["results_accepted_by_classifier"] == 1
        assert diag["directory_candidates_retained"] == 1
        assert diag["candidates_returned_to_preview"] == 1

    def test_e_valid_independent_organization_retained(self, task):
        """Scenario E: Valid independent organization is accepted and retained."""
        canned = [
            {
                "title": "Sociedad Colombiana de Pediatría Regional Valle - Inicio",
                "url": "https://scpvalle.org",
                "description": "Sitio oficial de la Sociedad Colombiana de Pediatría Regional Valle en Cali. Vigente 2026.",
            }
        ]

        transport = MockWebSearchTransport(canned_results=canned)
        provider = WebSearchDiscoveryProvider(
            transport=transport,
            enabled=True,
            authorized_tenants={"test_org"},
        )

        discovered = provider.discover(task)
        assert len(discovered) == 1

        biz = discovered[0]
        assert biz.raw_data["qualification_status"] == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW.value
        assert biz.raw_data["entity_archetype"] == EntityArchetype.PROFESSIONAL_ASSOCIATION.value

        diag = task.metadata.get("diagnostics")
        assert diag["results_accepted_by_classifier"] == 1
        assert diag["directory_candidates_retained"] == 0
        assert diag["candidates_returned_to_preview"] == 1

    def test_f_mixed_results_orchestrator_integration(self, task):
        """Scenario F: Orchestrator passes diagnostics to SearchExecutionResult and maintains accounting."""
        canned = [
            # Accepted directory
            {
                "title": "Sociedades Afiliadas - Academia Nacional de Medicina de Colombia",
                "url": "https://anmedcolombia.org.co/sociedades-afiliadas/",
                "description": "Relación de Sociedades Afiliadas.",
            },
            # Accepted real society
            {
                "title": "Sociedad Colombiana de Pediatría Regional Valle",
                "url": "https://scpvalle.org",
                "description": "Sitio oficial en Cali.",
            },
            # Rejected negative keyword
            {
                "title": "Sociedad Médica de Cali",
                "url": "https://medicos-cali.com",
                "description": "Convenios con EPS.",
            },
            # Rejected facility
            {
                "title": "Hospital Universitario de Cali",
                "url": "https://hospital.org",
                "description": "Centro hospitalario.",
            },
            # Missing fields
            {
                "title": "",
                "url": "",
                "description": "Bad item",
            },
        ]

        transport = MockWebSearchTransport(canned_results=canned)
        web_provider = WebSearchDiscoveryProvider(
            transport=transport,
            enabled=True,
            authorized_tenants={"test_org"},
        )

        orchestrator = DiscoveryOrchestrator(
            providers=[web_provider],
            prospect_service=MagicMock(),
            research_run_repo=MagicMock(),
            campaign_repo=MagicMock(),
        )

        plan = SearchPlan(
            id="plan_diag",
            organization_id="test_org",
            tasks=[task],
        )

        result = orchestrator.preview_plan(plan)
        assert len(result.candidates) == 2
        assert result.diagnostics is not None

        d = result.diagnostics
        assert d["provider_results_received"] == 5
        assert d["results_missing_required_fields"] == 1
        assert d["results_rejected_by_classifier"] == 2
        assert d["results_accepted_by_classifier"] == 2
        assert d["directory_candidates_retained"] == 1
        assert d["candidates_returned_to_preview"] == 2

        # Accounting invariants
        assert (
            d["provider_results_received"]
            == d["results_missing_required_fields"]
            + d["results_rejected_by_classifier"]
            + d["results_accepted_by_classifier"]
        )
        assert sum(d["rejection_reasons"].values()) == d["results_rejected_by_classifier"]

    def test_g_provider_failure_does_not_crash_diagnostics(self, task):
        """Scenario G: Provider failure logs task error gracefully."""
        transport = MockWebSearchTransport(raise_error=True)
        web_provider = WebSearchDiscoveryProvider(
            transport=transport,
            enabled=True,
            authorized_tenants={"test_org"},
        )

        orchestrator = DiscoveryOrchestrator(
            providers=[web_provider],
            prospect_service=MagicMock(),
            research_run_repo=MagicMock(),
            campaign_repo=MagicMock(),
        )

        plan = SearchPlan(
            id="plan_fail",
            organization_id="test_org",
            tasks=[task],
        )

        result = orchestrator.preview_plan(plan)
        assert result.tasks_failed == 1
        assert result.tasks_succeeded == 0
        assert len(result.candidates) == 0
        assert len(result.errors) > 0

    def test_h_discovery_preview_response_schema_compatibility(self):
        """Scenario H: DiscoveryPreviewResponse schema backward compatibility with and without diagnostics."""
        # 1. Without diagnostics (older client or non-web provider)
        resp_no_diag = DiscoveryPreviewResponse(
            status="completed",
            organization_id="org_1",
            provider="web_search",
            tasks_executed=1,
            candidates_count=0,
            candidates=[],
        )
        assert resp_no_diag.diagnostics is None
        data = resp_no_diag.model_dump()
        assert data["diagnostics"] is None
        assert data["status"] == "completed"

        # 2. With diagnostics
        diag_model = DiscoveryPreviewDiagnostics(
            provider_results_received=5,
            results_missing_required_fields=0,
            results_rejected_by_classifier=5,
            results_accepted_by_classifier=0,
            directory_candidates_retained=0,
            candidates_returned_to_preview=0,
            rejection_reasons={"EXCLUDED_FACILITY": 3, "NEGATIVE_KEYWORD_MATCH": 2},
        )
        resp_with_diag = DiscoveryPreviewResponse(
            status="completed",
            organization_id="org_1",
            provider="web_search",
            tasks_executed=1,
            candidates_count=0,
            candidates=[],
            diagnostics=diag_model,
        )
        assert resp_with_diag.diagnostics is not None
        assert resp_with_diag.diagnostics.provider_results_received == 5
        assert resp_with_diag.diagnostics.rejection_reasons["EXCLUDED_FACILITY"] == 3

    def test_i_tenant_authorization_remains_unchanged(self, task):
        """Scenario I: Unauthorized tenant is rejected with TenantAccessError."""
        transport = MockWebSearchTransport(canned_results=[])
        provider = WebSearchDiscoveryProvider(
            transport=transport,
            enabled=True,
            authorized_tenants={"other_org"},  # test_org is not authorized
        )

        from bopclients.domain.exceptions import TenantAccessError
        with pytest.raises(TenantAccessError) as exc_info:
            provider.discover(task)
        assert "is not authorized for web search discovery" in str(exc_info.value)

    def test_l_diagnostic_counts_mathematical_consistency(self, task):
        """Scenario L: Invariants hold strictly across various synthetic payloads."""
        canned = [
            {"title": "", "url": ""},  # missing fields
            {"title": "Clínica 1", "url": "https://clinica1.com", "description": "Clínica privada"},  # rejected: facility
            {"title": "Sociedad Médica", "url": "https://sociedad.com", "description": "Convenio EPS"},  # rejected: negative keyword
            {"title": "Sociedad Colombiana de Pediatría", "url": "https://scp.org", "description": "Pediatría en Cali"},  # accepted
        ]

        transport = MockWebSearchTransport(canned_results=canned)
        provider = WebSearchDiscoveryProvider(
            transport=transport,
            enabled=True,
            authorized_tenants={"test_org"},
        )

        provider.discover(task)
        diag = task.metadata["diagnostics"]

        # Invariant 1: Total = Missing + Rejected + Accepted
        assert (
            diag["provider_results_received"]
            == diag["results_missing_required_fields"]
            + diag["results_rejected_by_classifier"]
            + diag["results_accepted_by_classifier"]
        )
        # Invariant 2: Total rejections = Sum of reasons
        assert sum(diag["rejection_reasons"].values()) == diag["results_rejected_by_classifier"]
        # Invariant 3: Directory retained <= Accepted
        assert diag["directory_candidates_retained"] <= diag["results_accepted_by_classifier"]
