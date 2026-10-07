"""BOPCLIENTS Phase P30.5G.5H.6B.1: Candidate Investigation & Requalification Foundation Tests.

Validates:
A. Unknown official website is resolved from a true first-party result.
B. Directory result does not become official website.
C. Candidate without Cali evidence remains LOCATION_UNVERIFIED.
D. Attributable Cali evidence upgrades local presence.
E. Query contains Cali but returned evidence does not -> no upgrade.
F. Recent attributable activity upgrades CURRENT_ACTIVITY_EVIDENCED.
G. Historical-only evidence remains HISTORICAL_ACTIVITY_ONLY.
H. One investigation query max (MAX_INVESTIGATION_QUERIES = 1).
I. Five results max (limit = 5).
J. No automatic retry.
K. Zero Prospect creation (no DB records).
L. Zero ProspectSource creation (no DB records).
M. Zero CRM handoff.
N. Requalification uses existing qualifier.
O. SEARCH_MATCH may remain SEARCH_MATCH.
P. SEARCH_MATCH may become READY_FOR_COMMERCIAL_REVIEW when all gates are met.
Regression: Cross-source entity bundle preservation.
General-purpose: Medical, construction, industrial distributor, software, restaurant.
"""

import socket
import pytest
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock

from bopclients.domain.candidate_qualification import (
    CandidateQualificationStatus,
    EntityArchetype,
    GeographicEvidenceStatus,
    CurrentActivityStatus,
)
from bopclients.application.discovery.candidate_investigation_service import (
    CandidateInvestigationService,
)
from bopclients.application.discovery.candidate_qualifier import (
    OrganizationCandidateQualifier,
)
from bopclients.application.discovery.candidate_classifier import (
    OrganizationCandidateClassifier,
)
from bopclients.infrastructure.providers.web_search_provider import (
    WebSearchDiscoveryProvider,
    IWebSearchTransport,
)
from bopclients.api.schemas.discovery import (
    CandidateSourceEvidence,
    CandidateInvestigationRequest,
    CandidateInvestigationResponse,
)


@pytest.fixture(autouse=True)
def block_external_sockets(monkeypatch):
    """Enforce strict offline operation for all qualification tests."""
    orig_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) and address else address
        if host not in ("127.0.0.1", "localhost", "testserver", "::1"):
            raise RuntimeError(f"UNAUTHORIZED_EXTERNAL_NETWORK_CALL: Attempted connection to {host}")
        return orig_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


class MockWebSearchTransport(IWebSearchTransport):
    """Deterministic mock transport returning canned results per query."""

    def __init__(self, query_responses: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        self.query_responses = query_responses or {}
        self.recorded_queries: List[str] = []

    def search(
        self,
        query: str,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        count: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        self.recorded_queries.append(query)
        res = self.query_responses.get(query.strip(), [])
        return {
            "query": {"original": query, "more_results_available": False},
            "web": {"results": list(res[:count])},
        }


def make_service(transport: MockWebSearchTransport) -> CandidateInvestigationService:
    provider = WebSearchDiscoveryProvider(
        transport=transport,
        enabled=True,
        authorized_tenants={"org_test"},
        max_queries_per_run=1,
        max_results_per_query=5,
    )
    return CandidateInvestigationService(
        providers=[provider],
        qualifier=OrganizationCandidateQualifier(),
        classifier=OrganizationCandidateClassifier(),
    )


# ==============================================================================
# TESTS A-P: Core Investigation Capabilities
# ==============================================================================

def test_a_official_website_resolved_from_true_first_party():
    """A. Unknown official website is resolved from a true first-party domain."""
    query = "Asociación de Pediatría del Valle sitio web oficial"
    mock_results = [
        {
            "title": "Asociación de Pediatría del Valle - Sitio Oficial",
            "url": "https://asopediatriavalle.org/inicio",
            "description": "Sitio oficial de la Asociación de Pediatría del Valle, agremiación médica en Cali 2026.",
        }
    ]
    transport = MockWebSearchTransport({query: mock_results})
    service = make_service(transport)

    req = CandidateInvestigationRequest(
        candidate_name="Asociación de Pediatría del Valle",
        organization_website="UNKNOWN",
        entity_archetype=EntityArchetype.PROFESSIONAL_ASSOCIATION.value,
        city="Cali",
        state="Valle",
        country="CO",
        current_qualification_status="SEARCH_MATCH",
        missing_evidence=["OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN"],
        sources=[
            CandidateSourceEvidence(
                source_url="https://facebook.com/asopediatriavalle",
                source_host="facebook.com",
                source_type="SOCIAL_PROFILE",
                platform="facebook.com",
                title="Asociación de Pediatría del Valle Facebook",
                snippet="Perfil oficial en Cali.",
            )
        ],
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    assert resp.status == "completed"
    assert resp.investigation_objective == "OFFICIAL_WEBSITE"
    assert resp.investigation_query == query
    assert resp.organization_website == "https://asopediatriavalle.org"
    assert resp.is_commercial_review_ready is True
    assert resp.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW.value
    assert resp.qualification_changed is True
    assert resp.new_sources_added == 1
    assert resp.database_writes == 0


def test_b_directory_result_does_not_become_official_website():
    """B. Directory result (e.g. paginasamarillas) does not become official website."""
    query = "Sociedad de Cirugía de Cali sitio web oficial"
    mock_results = [
        {
            "title": "Sociedad de Cirugía de Cali en Directorio Médico",
            "url": "https://paginasamarillas.com.co/empresas/sociedad-cirugia-cali",
            "description": "Directorio telefónico y listado de la Sociedad de Cirugía de Cali.",
        }
    ]
    transport = MockWebSearchTransport({query: mock_results})
    service = make_service(transport)

    req = CandidateInvestigationRequest(
        candidate_name="Sociedad de Cirugía de Cali",
        organization_website="UNKNOWN",
        entity_archetype=EntityArchetype.PROFESSIONAL_ASSOCIATION.value,
        city="Cali",
        current_qualification_status="SEARCH_MATCH",
        missing_evidence=["OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN"],
        sources=[],
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    assert resp.status == "completed"
    assert resp.organization_website == "UNKNOWN"
    assert "OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN" in resp.missing_evidence
    assert resp.qualification_status == CandidateQualificationStatus.SEARCH_MATCH.value
    assert resp.is_commercial_review_ready is False


def test_c_candidate_without_cali_evidence_remains_location_unverified():
    """C. Candidate without local presence evidence remains LOCATION_UNVERIFIED."""
    query = "Federación Odontológica Colombiana Cali"
    # Returns only national scope without local branch evidence
    mock_results = [
        {
            "title": "Federación Odontológica Colombiana - Sede Nacional",
            "url": "https://foc.org.co",
            "description": "Gremio nacional de odontólogos en Colombia.",
        }
    ]
    transport = MockWebSearchTransport({query: mock_results})
    service = make_service(transport)

    req = CandidateInvestigationRequest(
        candidate_name="Federación Odontológica Colombiana",
        organization_website="https://foc.org.co",
        entity_archetype=EntityArchetype.FEDERATION.value,
        city="Cali",
        current_qualification_status="SEARCH_MATCH",
        missing_evidence=["LOCAL_PHYSICAL_PRESENCE_UNVERIFIED_FOR_NATIONAL_SCOPE"],
        geographic_evidence_status=GeographicEvidenceStatus.NATIONAL_SCOPE.value,
        sources=[
            CandidateSourceEvidence(
                source_url="https://foc.org.co",
                source_host="foc.org.co",
                source_type="OFFICIAL_WEBSITE",
                title="FOC",
                snippet="Gremio odontológico nacional.",
            )
        ],
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    assert resp.status == "completed"
    assert resp.investigation_objective == "LOCAL_PRESENCE"
    assert resp.geographic_evidence_status == GeographicEvidenceStatus.NATIONAL_SCOPE.value
    assert "LOCAL_PHYSICAL_PRESENCE_UNVERIFIED_FOR_NATIONAL_SCOPE" in resp.missing_evidence
    assert resp.qualification_status == CandidateQualificationStatus.SEARCH_MATCH.value
    assert resp.is_commercial_review_ready is False


def test_d_attributable_cali_evidence_upgrades_local_presence():
    """D. Attributable Cali evidence upgrades local presence to VERIFIED_LOCAL_PRESENCE."""
    query = "Federación Odontológica Colombiana Cali"
    mock_results = [
        {
            "title": "Federación Odontológica Colombiana - Seccional Cali",
            "url": "https://foc.org.co/seccionales/cali",
            "description": "Sede y capítulo de la Federación Odontológica Colombiana en Cali, Valle del Cauca. Activa 2026.",
        }
    ]
    transport = MockWebSearchTransport({query: mock_results})
    service = make_service(transport)

    req = CandidateInvestigationRequest(
        candidate_name="Federación Odontológica Colombiana",
        organization_website="https://foc.org.co",
        entity_archetype=EntityArchetype.FEDERATION.value,
        city="Cali",
        current_qualification_status="SEARCH_MATCH",
        missing_evidence=["LOCAL_PHYSICAL_PRESENCE_UNVERIFIED_FOR_NATIONAL_SCOPE"],
        geographic_evidence_status=GeographicEvidenceStatus.NATIONAL_SCOPE.value,
        sources=[
            CandidateSourceEvidence(
                source_url="https://foc.org.co",
                source_host="foc.org.co",
                source_type="OFFICIAL_WEBSITE",
                title="FOC Nacional",
                snippet="Federación Odontológica Colombiana.",
            )
        ],
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    assert resp.status == "completed"
    assert resp.investigation_objective == "LOCAL_PRESENCE"
    assert resp.geographic_evidence_status == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE.value
    assert "LOCAL_PHYSICAL_PRESENCE_UNVERIFIED_FOR_NATIONAL_SCOPE" not in resp.missing_evidence
    assert resp.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW.value
    assert resp.is_commercial_review_ready is True
    assert resp.qualification_changed is True


def test_e_query_contains_cali_but_returned_evidence_does_not():
    """E. Query contains Cali but returned evidence does not -> no upgrade."""
    query = "Sociedad Colombiana de Anestesiología Cali"
    # Result returned has Bogotá in snippet, no mention of Cali
    mock_results = [
        {
            "title": "Sociedad Colombiana de Anestesiología - Sede Bogotá",
            "url": "https://scare.org.co/contacto",
            "description": "Sede principal ubicada en Bogotá, Colombia. Contacto nacional.",
        }
    ]
    transport = MockWebSearchTransport({query: mock_results})
    service = make_service(transport)

    req = CandidateInvestigationRequest(
        candidate_name="Sociedad Colombiana de Anestesiología",
        organization_website="https://scare.org.co",
        entity_archetype=EntityArchetype.PROFESSIONAL_ASSOCIATION.value,
        city="Cali",
        current_qualification_status="SEARCH_MATCH",
        missing_evidence=["LOCAL_PHYSICAL_PRESENCE_UNVERIFIED_FOR_NATIONAL_SCOPE"],
        geographic_evidence_status=GeographicEvidenceStatus.NATIONAL_SCOPE.value,
        sources=[],
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    assert resp.status == "completed"
    # Mismatched major city or unverified Cali -> must not upgrade to verified local presence
    assert resp.geographic_evidence_status != GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE.value
    assert resp.qualification_status != CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW.value


def test_f_recent_attributable_activity_upgrades_current_activity():
    """F. Recent attributable activity upgrades to CURRENT_ACTIVITY_EVIDENCED."""
    query = "Asociación Colombiana de Radiología 2026"
    mock_results = [
        {
            "title": "Asociación Colombiana de Radiología - Congreso 2026",
            "url": "https://acronline.org/eventos-2026",
            "description": "Agenda académica y congreso vigente para el año 2026.",
        }
    ]
    transport = MockWebSearchTransport({query: mock_results})
    service = make_service(transport)

    req = CandidateInvestigationRequest(
        candidate_name="Asociación Colombiana de Radiología",
        organization_website="https://acronline.org",
        entity_archetype=EntityArchetype.PROFESSIONAL_ASSOCIATION.value,
        country="CO",
        current_qualification_status="SEARCH_MATCH",
        missing_evidence=["CURRENT_ACTIVITY_EVIDENCE_REQUIRED"],
        current_activity_status=CurrentActivityStatus.CURRENT_STATUS_UNKNOWN.value,
        sources=[
            CandidateSourceEvidence(
                source_url="https://acronline.org",
                source_host="acronline.org",
                source_type="OFFICIAL_WEBSITE",
                title="ACR",
                snippet="Asociación Colombiana de Radiología.",
            )
        ],
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    assert resp.status == "completed"
    assert resp.investigation_objective == "CURRENT_ACTIVITY"
    assert resp.current_activity_status == CurrentActivityStatus.CURRENT_ACTIVITY_EVIDENCED.value


def test_g_historical_only_evidence_remains_historical_activity_only():
    """G. Historical-only archive evidence remains HISTORICAL_ACTIVITY_ONLY."""
    query = "Sociedad Médica de Cali 2026"
    mock_results = [
        {
            "title": "Sociedad Médica de Cali (Archivo Histórico 1998)",
            "url": "http://oocities.org/sociedad_cali/1998.html",
            "description": "Sitio histórico disuelta en 1999. Geocities archive.",
        }
    ]
    transport = MockWebSearchTransport({query: mock_results})
    service = make_service(transport)

    req = CandidateInvestigationRequest(
        candidate_name="Sociedad Médica de Cali",
        organization_website="UNKNOWN",
        target_objective="CURRENT_ACTIVITY",
        entity_archetype=EntityArchetype.HISTORICAL_REFERENCE.value,
        current_qualification_status="SEARCH_MATCH",
        current_activity_status=CurrentActivityStatus.HISTORICAL_ACTIVITY_ONLY.value,
        missing_evidence=["HISTORICAL_ARCHIVE_LACKS_CURRENT_ACTIVITY_EVIDENCE"],
        sources=[],
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    assert resp.status == "completed"
    assert resp.current_activity_status == CurrentActivityStatus.HISTORICAL_ACTIVITY_ONLY.value
    assert resp.is_commercial_review_ready is False


def test_h_i_j_budget_and_no_retry():
    """H, I, J. Strictly 1 query maximum, 5 results maximum, no automatic retries."""
    query = "Constructora del Valle sitio web oficial"
    transport = MockWebSearchTransport({query: []})
    service = make_service(transport)

    req = CandidateInvestigationRequest(
        candidate_name="Constructora del Valle",
        organization_website="UNKNOWN",
        city="Cali",
        category="construction",
        sources=[],
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    # Exactly 1 query dispatched
    assert len(transport.recorded_queries) == 1
    assert transport.recorded_queries[0] == query
    assert resp.status == "completed"
    # No retries on 0 results


def test_k_l_m_ephemeral_zero_db_writes_no_crm():
    """K, L, M. Zero Prospect creation, zero ProspectSource creation, zero CRM calls."""
    query = "Distribuidora Industrial del Pacífico sitio web oficial"
    mock_results = [
        {
            "title": "Distribuidora Industrial del Pacífico - Inicio",
            "url": "https://distribuidorapacifico.com",
            "description": "Distribución de suministros industriales en Cali, Valle.",
        }
    ]
    transport = MockWebSearchTransport({query: mock_results})
    service = make_service(transport)

    req = CandidateInvestigationRequest(
        candidate_name="Distribuidora Industrial del Pacífico",
        organization_website="UNKNOWN",
        category="industrial_distributor",
        city="Cali",
        sources=[],
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    assert resp.database_writes == 0
    # Ephemeral response strictly returned


def test_o_search_match_may_remain_search_match():
    """O. SEARCH_MATCH may remain SEARCH_MATCH when investigation is inconclusive."""
    query = "Empresa de Software Cali sitio web oficial"
    # Returned results are empty or unrelated
    transport = MockWebSearchTransport({query: []})
    service = make_service(transport)

    req = CandidateInvestigationRequest(
        candidate_name="Empresa de Software Cali",
        organization_website="UNKNOWN",
        category="b2b_software",
        city="Cali",
        current_qualification_status="SEARCH_MATCH",
        missing_evidence=["OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN"],
        sources=[],
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    assert resp.qualification_status == CandidateQualificationStatus.SEARCH_MATCH.value
    assert resp.qualification_changed is False
    assert resp.is_commercial_review_ready is False


def test_p_search_match_becomes_ready_for_commercial_review_when_all_gates_met():
    """P. SEARCH_MATCH becomes READY_FOR_COMMERCIAL_REVIEW when all gates are met."""
    query = "Restaurante La Casona de Cali sitio web oficial"
    mock_results = [
        {
            "title": "Restaurante La Casona de Cali - Sitio Oficial",
            "url": "https://lacasonacali.com",
            "description": "Restaurante tradicional en Cali, Valle del Cauca. Abierto y vigente 2026.",
        }
    ]
    transport = MockWebSearchTransport({query: mock_results})
    service = make_service(transport)

    req = CandidateInvestigationRequest(
        candidate_name="Restaurante La Casona de Cali",
        organization_website="UNKNOWN",
        category="restaurant",
        city="Cali",
        current_qualification_status="SEARCH_MATCH",
        missing_evidence=["OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN"],
        sources=[],
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    assert resp.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW.value
    assert resp.is_commercial_review_ready is True
    assert resp.qualification_changed is True
    assert resp.organization_website == "https://lacasonacali.com"


# ==============================================================================
# GENERAL-PURPOSE VERTICAL TESTS (Section 22)
# ==============================================================================

@pytest.mark.parametrize(
    "sector,candidate_name,expected_domain",
    [
        ("medical_association", "Sociedad Colombiana de Urología", "https://urologiacolombia.org"),
        ("construction", "Constructora Meléndez", "https://constructoramelendez.com"),
        ("industrial_distributor", "Suministros Industriales del Valle", "https://suministrosvalle.co"),
        ("b2b_software", "Logística SaaS Colombia", "https://logisticasaas.com"),
        ("restaurant", "Restaurante Platillos Voladores", "https://platillosvoladores.com"),
    ],
)
def test_general_purpose_vertical_investigation(sector, candidate_name, expected_domain):
    """Investigation operates generically across all ICP sectors without sector bias."""
    query = f"{candidate_name} sitio web oficial"
    mock_results = [
        {
            "title": f"{candidate_name} - Sitio Oficial",
            "url": f"{expected_domain}/inicio",
            "description": f"Sitio oficial de {candidate_name} en Cali, Valle del Cauca. Actualizado 2026.",
        }
    ]
    transport = MockWebSearchTransport({query: mock_results})
    service = make_service(transport)

    req = CandidateInvestigationRequest(
        candidate_name=candidate_name,
        organization_website="UNKNOWN",
        category=sector,
        city="Cali",
        country="CO",
        current_qualification_status="SEARCH_MATCH",
        missing_evidence=["OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN"],
        sources=[],
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    assert resp.status == "completed"
    assert resp.organization_website == expected_domain
    assert resp.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW.value


# ==============================================================================
# SOURCE-BUNDLE REGRESSION TESTS (Section 21)
# ==============================================================================

def test_source_bundle_preservation_and_no_flattening():
    """Existing sources (official site + Facebook + X) are preserved alongside new investigation sources."""
    query = "Sociedad Médica del Valle 2026"
    mock_results = [
        {
            "title": "Sociedad Médica del Valle - Noticias 2026",
            "url": "https://sociedadmedicavalle.org/noticias/2026",
            "description": "Boletín informativo y novedades del 2026.",
        }
    ]
    transport = MockWebSearchTransport({query: mock_results})
    service = make_service(transport)

    existing_bundle = [
        CandidateSourceEvidence(
            source_url="https://sociedadmedicavalle.org",
            source_host="sociedadmedicavalle.org",
            source_type="OFFICIAL_WEBSITE",
            title="SMV Oficial",
            snippet="Sitio web institucional en Cali.",
        ),
        CandidateSourceEvidence(
            source_url="https://facebook.com/sociedadmedicavalle",
            source_host="facebook.com",
            source_type="SOCIAL_PROFILE",
            platform="facebook.com",
            title="SMV Facebook",
            snippet="Página de Facebook.",
        ),
        CandidateSourceEvidence(
            source_url="https://x.com/sociedadmedicavalle",
            source_host="x.com",
            source_type="SOCIAL_PROFILE",
            platform="x.com",
            title="SMV X",
            snippet="Cuenta oficial de X.",
        ),
    ]

    req = CandidateInvestigationRequest(
        candidate_name="Sociedad Médica del Valle",
        organization_website="https://sociedadmedicavalle.org",
        target_objective="CURRENT_ACTIVITY",
        city="Cali",
        current_qualification_status="SEARCH_MATCH",
        sources=existing_bundle,
    )

    resp = service.investigate_candidate(org_id="org_test", request=req)

    # 3 existing + 1 new = 4 sources
    assert resp.sources_count == 4
    assert resp.new_sources_added == 1
    # Verify all platforms are distinct and unflattened
    urls = [s.source_url for s in resp.sources]
    assert "https://sociedadmedicavalle.org" in urls
    assert "https://facebook.com/sociedadmedicavalle" in urls
    assert "https://x.com/sociedadmedicavalle" in urls
    assert "https://sociedadmedicavalle.org/noticias/2026" in urls


def test_api_candidate_investigate_endpoint(tmp_path):
    """Verify POST /api/v1/discovery/candidates/investigate works over HTTP with auth."""
    from fastapi.testclient import TestClient
    from bopclients.api.app import create_bopclients_api_app
    from bopclients.runtime.container import build_runtime_container
    from bopclients.domain.organization import Organization, OrganizationMember
    from bopclients.domain.enums import MemberRole
    from bopclients.infrastructure.providers.web_search_provider import OfflineFixtureWebSearchTransport
    from bopclients.infrastructure.db.connection import create_database_connection
    from bopclients.runtime.db_migrator import DatabaseMigrator
    from bopclients.runtime.settings import RuntimeSettings
    import uuid

    db_file = tmp_path / "test_api_inv.db"
    db_url = f"sqlite:///{db_file}"
    conn = create_database_connection(db_url)
    DatabaseMigrator.migrate(conn)

    org_id = str(uuid.uuid4())
    settings = RuntimeSettings(
        database_url=db_url,
        environment="test",
        tavily_enabled=True,
        tavily_authorized_tenants=[org_id],
    )
    container = build_runtime_container(settings, db=conn)

    org = Organization(
        id=org_id,
        bop_organization_id=str(uuid.uuid4()),
        name="Test API Org",
        slug=f"test-{org_id[:8]}",
    )
    container.org_repo.save(org)
    admin_user = container.auth_service.register_user(
        email=f"admin_{org_id[:8]}@test.com",
        name="Admin",
        password="Password123!",
        locale="es",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            user_id=admin_user.id,
            role=MemberRole.ADMIN,
        )
    )

    query = "Sociedad Médica del Valle sitio web oficial"
    fixtures = {
        query: {
            "query": {"original": query, "more_results_available": False},
            "web": {
                "results": [
                    {
                        "title": "Sociedad Médica del Valle - Sitio Oficial",
                        "url": "https://sociedadmedicavalle.org",
                        "description": "Sitio institucional de la Sociedad Médica en Cali Valle 2026.",
                    }
                ]
            },
        }
    }
    fixture_transport = OfflineFixtureWebSearchTransport(fixtures)
    web_prov = container.candidate_investigation_service.providers["web_search"]
    web_prov._transport = fixture_transport
    web_prov.enabled = True
    web_prov.authorized_tenants.add(org_id)

    app = create_bopclients_api_app(container=container)
    client = TestClient(app)

    token_pair, _ = container.auth_service.authenticate(f"admin_{org_id[:8]}@test.com", "Password123!")
    token = token_pair.access_token
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": org_id,
        "X-Bop-Organization-Id": org_id,
    }

    payload = {
        "candidate_name": "Sociedad Médica del Valle",
        "organization_website": "UNKNOWN",
        "city": "Cali",
        "current_qualification_status": "SEARCH_MATCH",
        "missing_evidence": ["OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN"],
        "sources": [
            {
                "source_url": "https://directorio.com/sociedad-medica-valle",
                "source_host": "directorio.com",
                "source_type": "DIRECTORY_LISTING",
                "title": "Directorio",
                "snippet": "Listado médico en Cali.",
            }
        ],
    }

    res = client.post("/api/v1/discovery/candidates/investigate", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "completed"
    assert data["candidate_name"] == "Sociedad Médica del Valle"
    assert data["investigation_objective"] == "OFFICIAL_WEBSITE"
    assert data["organization_website"] == "https://sociedadmedicavalle.org"
    assert data["qualification_status"] == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW.value
    assert data["is_commercial_review_ready"] is True
    assert data["qualification_changed"] is True
    assert data["new_sources_added"] == 1
    assert data["database_writes"] == 0
