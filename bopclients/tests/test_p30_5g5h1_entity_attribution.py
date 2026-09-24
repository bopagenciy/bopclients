"""Focused offline unit and integration tests for P30.5G.5H.1 Entity Evidence Attribution Integrity Fix.

Verifies:
1. Synthetic Fixtures A through M covering cross-sector directory detection, entity isolation,
   hyphenated single-entity preservation, publisher separation, and truthful qualification:
   A. Medical affiliated-societies directory with several cities.
   B. Construction membership directory listing contractors.
   C. Industrial distributor directory listing suppliers.
   D. Software partner directory.
   E. Restaurant listing page.
   F. Genuine independent company with a hyphenated title.
   G. Genuine publisher organization with an official website.
   H. Individual society page with attributable Cali evidence.
   I. Multi-entity snippet where Cali belongs to another entity.
   J. Directory publisher domain must not become listed organization official website.
   K. Unknown current activity must not become positive current-activity evidence.
   L. Unresolved composite entity must not become commercially ready.
   M. Valid independently evidenced candidate remains commercially reviewable when ICP requirements are satisfied.
2. Section 12 Live Pilot Regression Fixture:
   Sanitized synthetic fixture reproducing the failure pattern from an institutional listing.
3. Socket guard enforcing zero external network calls (no live Tavily, no Overture, no Gemini).
"""

import socket
import pytest

from bopclients.domain.candidate_qualification import (
    CandidateQualificationStatus,
    EntityArchetype,
    GeographicEvidenceStatus,
    CurrentActivityStatus,
)
from bopclients.application.discovery.candidate_qualifier import (
    OrganizationCandidateQualifier,
)
from bopclients.application.discovery.candidate_classifier import (
    CandidateClassificationStatus,
    ClassificationDecision,
    OrganizationCandidateClassifier,
)
from bopclients.application.search_dto import DiscoveryTask
from bopclients.infrastructure.providers.web_search_provider import (
    WebSearchDiscoveryProvider,
    OfflineFixtureWebSearchTransport,
    GeographicScope,
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


@pytest.fixture
def qualifier():
    return OrganizationCandidateQualifier()


@pytest.fixture
def classifier():
    return OrganizationCandidateClassifier()


# =====================================================================
# Tests A through M
# =====================================================================

def test_a_medical_affiliated_societies_directory(qualifier):
    """A. Medical affiliated-societies directory with several cities."""
    task = DiscoveryTask(id="t_a", city="Cali", country="CO", category="medical_association")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    raw_title = "Sociedades Afiliadas - Colegio Médico Nacional"
    url = "https://colegiomediconacional.org.co/sociedades-afiliadas/"
    snippet = "Listado de sociedades afiliadas en Bogotá, Medellín, Cali y Barranquilla. Consulte los miembros."
    name = "Sociedades Afiliadas - Colegio Médico Nacional"

    res = qualifier.qualify(
        candidate_name=name,
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert res.entity_archetype == EntityArchetype.DIRECTORY_LISTING
    assert res.source_host == "colegiomediconacional.org.co"
    assert res.source_url == url
    assert res.organization_website == "UNKNOWN"
    assert res.geographic_evidence_status == GeographicEvidenceStatus.LOCATION_UNVERIFIED
    assert res.is_commercial_review_ready is False
    assert res.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "DIRECTORY_LISTING_NOT_ORGANIZATION" in res.missing_evidence
    assert "UNRESOLVED_COMPOSITE_DIRECTORY_ENTITY" in res.missing_evidence
    assert "OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN" in res.missing_evidence
    assert "LOCATION_UNVERIFIED_FOR_TARGET_CITY" in res.missing_evidence


def test_b_construction_membership_directory(qualifier):
    """B. Construction membership directory listing contractors."""
    task = DiscoveryTask(id="t_b", city="Cali", country="CO", category="construction")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    raw_title = "Directorio de Empresas y Contratistas Afiliados"
    url = "https://camaraconstruccion.org.co/directorio-empresas"
    snippet = "Guía de empresas de ingeniería y contratistas afiliados en Cali y el Valle. Consulte las empresas."
    name = "Directorio de Empresas y Contratistas Afiliados"

    res = qualifier.qualify(
        candidate_name=name,
        target_intent="construction",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert res.entity_archetype == EntityArchetype.DIRECTORY_LISTING
    assert res.organization_website == "UNKNOWN"
    assert res.geographic_evidence_status == GeographicEvidenceStatus.LOCATION_UNVERIFIED
    assert res.is_commercial_review_ready is False
    assert res.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "DIRECTORY_LISTING_NOT_ORGANIZATION" in res.missing_evidence
    assert "UNRESOLVED_COMPOSITE_DIRECTORY_ENTITY" in res.missing_evidence


def test_c_industrial_distributor_directory(qualifier):
    """C. Industrial distributor directory listing suppliers."""
    task = DiscoveryTask(id="t_c", city="Cali", country="CO", category="industrial_distributor")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    raw_title = "Nuestros Distribuidores Autorizados - Red Industrial"
    url = "https://fabricantemaquinaria.com/distribuidores"
    snippet = "Conozca a nuestros distribuidores autorizados en Colombia. Puntos de venta y proveedores en Cali."
    name = "Nuestros Distribuidores Autorizados - Red Industrial"

    res = qualifier.qualify(
        candidate_name=name,
        target_intent="industrial_distributor",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert res.entity_archetype == EntityArchetype.DIRECTORY_LISTING
    assert res.organization_website == "UNKNOWN"
    assert res.geographic_evidence_status == GeographicEvidenceStatus.LOCATION_UNVERIFIED
    assert res.is_commercial_review_ready is False
    assert res.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "DIRECTORY_LISTING_NOT_ORGANIZATION" in res.missing_evidence


def test_d_software_partner_directory(qualifier):
    """D. Software partner directory."""
    task = DiscoveryTask(id="t_d", city="Cali", country="CO", category="b2b_software")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    raw_title = "Global Partner Directory - Certified Solutions"
    url = "https://enterprisesoftware.com/partners/partner-directory"
    snippet = "Search our partner directory to find authorized implementation partners and SaaS vendors in Cali."
    name = "Global Partner Directory - Certified Solutions"

    res = qualifier.qualify(
        candidate_name=name,
        target_intent="b2b_software",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert res.entity_archetype == EntityArchetype.DIRECTORY_LISTING
    assert res.organization_website == "UNKNOWN"
    assert res.geographic_evidence_status == GeographicEvidenceStatus.LOCATION_UNVERIFIED
    assert res.is_commercial_review_ready is False
    assert res.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "DIRECTORY_LISTING_NOT_ORGANIZATION" in res.missing_evidence


def test_e_restaurant_listing_page(qualifier):
    """E. Restaurant listing page."""
    task = DiscoveryTask(id="t_e", city="Cali", country="CO", category="restaurant")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    raw_title = "Guía de Restaurantes y Trattorias en Cali"
    url = "https://guiagastronomica.com.co/listado-restaurantes"
    snippet = "Listado de restaurantes, trattorias y pizzerías recomendadas en Granada, Cali. Perfil en directorio."
    name = "Guía de Restaurantes y Trattorias en Cali"

    res = qualifier.qualify(
        candidate_name=name,
        target_intent="restaurant",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert res.entity_archetype == EntityArchetype.DIRECTORY_LISTING
    assert res.organization_website == "UNKNOWN"
    assert res.geographic_evidence_status == GeographicEvidenceStatus.LOCATION_UNVERIFIED
    assert res.is_commercial_review_ready is False
    assert res.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "DIRECTORY_LISTING_NOT_ORGANIZATION" in res.missing_evidence


def test_f_genuine_independent_company_hyphenated_title(qualifier):
    """F. Genuine independent company with a hyphenated title."""
    task = DiscoveryTask(id="t_f", city="Cali", country="CO", category="construction")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    raw_title = "Constructora del Valle S.A.S. - Ingeniería y Edificaciones"
    url = "https://constructoradelvalle.com.co"
    snippet = "Constructora del Valle S.A.S. ofrece proyectos de ingeniería civil y edificación en Cali. Vigente 2026."
    name = "Constructora del Valle S.A.S. - Ingeniería y Edificaciones"

    res = qualifier.qualify(
        candidate_name=name,
        target_intent="construction",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert res.entity_archetype == EntityArchetype.COMMERCIAL_ENTERPRISE
    assert res.organization_website == "https://constructoradelvalle.com.co"
    assert res.geographic_evidence_status == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE
    assert res.current_activity_status == CurrentActivityStatus.CURRENT_ACTIVITY_EVIDENCED
    assert res.is_commercial_review_ready is True
    assert res.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW
    assert "READY_FOR_COMMERCIAL_REVIEW" in res.qualification_reasons


def test_g_genuine_publisher_organization_official_website(qualifier):
    """G. Genuine publisher organization with an official website."""
    task = DiscoveryTask(id="t_g", country="CO", category="medical_association")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    raw_title = "Academia Nacional de Medicina de Colombia"
    url = "https://anmedcolombia.org.co"
    snippet = "Portal oficial de la Academia Nacional de Medicina de Colombia en Bogotá. Fundada en 1873. Vigente 2026."
    name = "Academia Nacional de Medicina de Colombia"

    res = qualifier.qualify(
        candidate_name=name,
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert res.entity_archetype in (
        EntityArchetype.PROFESSIONAL_ASSOCIATION,
        EntityArchetype.FEDERATION,
        EntityArchetype.INDEPENDENT_ORGANIZATION,
    )
    assert res.source_host == "anmedcolombia.org.co"
    assert res.organization_website == "https://anmedcolombia.org.co"
    assert res.geographic_evidence_status == GeographicEvidenceStatus.NATIONAL_SCOPE
    assert res.is_commercial_review_ready is True
    assert res.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW


def test_h_individual_society_with_attributable_cali_evidence(qualifier):
    """H. Individual society page with attributable Cali evidence."""
    task = DiscoveryTask(id="t_h", city="Cali", country="CO", category="medical_association")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    raw_title = "Sociedad de Pediatría del Valle"
    url = "https://pediatriavalle.org.co"
    snippet = "Sociedad científica de pediatría con sede en Cali, Valle del Cauca. Actividades y congreso 2026."
    name = "Sociedad de Pediatría del Valle"

    res = qualifier.qualify(
        candidate_name=name,
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert res.entity_archetype == EntityArchetype.PROFESSIONAL_ASSOCIATION
    assert res.organization_website == "https://pediatriavalle.org.co"
    assert res.geographic_evidence_status == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE
    assert res.is_commercial_review_ready is True
    assert res.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW


def test_i_multi_entity_snippet_where_cali_belongs_to_another_entity(qualifier):
    """I. Multi-entity snippet where Cali belongs to another entity."""
    task = DiscoveryTask(id="t_i", city="Cali", country="CO", category="medical_association")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    raw_title = "Sociedades Afiliadas - Federación Médica Colombiana"
    url = "https://federacionmedica.org.co/sociedades-afiliadas"
    snippet = "Relación de sociedades: Sociedad de Bogotá, Sociedad de Medellín, Asociación de Cali. Consulte miembros."
    name = "Sociedades Afiliadas - Federación Médica Colombiana"

    res = qualifier.qualify(
        candidate_name=name,
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    # Cali in snippet must not contaminate directory candidate as verified local
    assert res.entity_archetype == EntityArchetype.DIRECTORY_LISTING
    assert res.geographic_evidence_status == GeographicEvidenceStatus.LOCATION_UNVERIFIED
    assert res.organization_website == "UNKNOWN"
    assert res.is_commercial_review_ready is False
    assert res.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "LOCATION_UNVERIFIED_FOR_TARGET_CITY" in res.missing_evidence


def test_j_directory_publisher_domain_not_listed_org_website(qualifier):
    """J. Directory publisher domain must not become listed organization official website."""
    task = DiscoveryTask(id="t_j", city="Cali", country="CO", category="medical_association")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    raw_title = "Sociedades Miembro - Academia Nacional"
    url = "https://academianacional.org.co/sociedades-afiliadas/asociacion-interna"
    snippet = "Asociación Colombiana de Medicina Interna listada como entidad afiliada en Cali."
    name = "Asociación Colombiana de Medicina Interna"

    res = qualifier.qualify(
        candidate_name=name,
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    # The publisher domain academianacional.org.co is not the official website of the listed association
    assert res.source_host == "academianacional.org.co"
    assert res.organization_website == "UNKNOWN"
    assert res.organization_website != "https://academianacional.org.co"


def test_k_unknown_current_activity_not_positive_evidence(qualifier):
    """K. Unknown current activity must not become positive current-activity evidence."""
    task = DiscoveryTask(id="t_k", city="Cali", country="CO", category="medical_association")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    raw_title = "Sociedad Médica de Cali"
    url = "https://sociedadmedicacali.org"
    # No freshness markers (no 2024-2026, no agenda, no contacto directo)
    snippet = "Sociedad médica y gremial de profesionales de la salud en la ciudad de Cali."
    name = "Sociedad Médica de Cali"

    res = qualifier.qualify(
        candidate_name=name,
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert res.current_activity_status == CurrentActivityStatus.CURRENT_STATUS_UNKNOWN
    assert "CURRENT_ACTIVITY_EVIDENCED" not in res.qualification_reasons


def test_l_unresolved_composite_entity_not_commercially_ready(qualifier):
    """L. Unresolved composite entity must not become commercially ready."""
    task = DiscoveryTask(id="t_l", city="Cali", country="CO", category="medical_association")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    res = qualifier.qualify(
        candidate_name="Entidades y Sociedades Afiliadas",
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title="Entidades y Sociedades Afiliadas al Colegio",
        url="https://colegio.org/afiliados",
        snippet="Listado de entidades médicas afiliadas con presencia en Cali y Bogotá.",
        task=task,
    )

    assert res.is_commercial_review_ready is False
    assert res.qualification_status != CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW
    assert res.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "UNRESOLVED_COMPOSITE_DIRECTORY_ENTITY" in res.missing_evidence


def test_m_valid_independently_evidenced_candidate_remains_reviewable(qualifier):
    """M. Valid independently evidenced candidate remains commercially reviewable when ICP requirements are satisfied."""
    task = DiscoveryTask(id="t_m", city="Cali", country="CO", category="medical_association")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )
    res = qualifier.qualify(
        candidate_name="Sociedad Colombiana de Pediatría Regional Valle",
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title="Sociedad Colombiana de Pediatría Regional Valle - Sitio Oficial",
        url="https://scpvalle.org",
        snippet="Sitio oficial de la Sociedad Colombiana de Pediatría Regional Valle en Cali. Eventos médicos y congreso 2026.",
        task=task,
    )

    assert res.entity_archetype == EntityArchetype.PROFESSIONAL_ASSOCIATION
    assert res.organization_website == "https://scpvalle.org"
    assert res.geographic_evidence_status == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE
    assert res.current_activity_status == CurrentActivityStatus.CURRENT_ACTIVITY_EVIDENCED
    assert res.is_commercial_review_ready is True
    assert res.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW
    assert "READY_FOR_COMMERCIAL_REVIEW" in res.qualification_reasons


# =====================================================================
# Section 12: Live Pilot Regression Fixture
# =====================================================================

def test_section_12_live_pilot_regression_fixture(qualifier):
    """Section 12: Live pilot regression fixture reproducing observed failure pattern.

    Pattern:
    A national medical institution publishes a list of affiliated regional medical societies.
    One listed society has an address in Cali.
    The directory page title mentions the publisher.
    """
    task = DiscoveryTask(
        id="live_pilot_task",
        city="Cali",
        country="CO",
        category="medical_association",
    )
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )

    raw_title = "Sociedades Afiliadas - Academia Nacional de Medicina de Colombia"
    url = "https://anmedcolombia.org.co/sociedades-afiliadas/"
    snippet = "Relación de Sociedades Afiliadas a la Academia. Capítulo Valle del Cauca - Sede Cali, Calle 5 # 38-40."
    candidate_name = "Sociedades Afiliadas - Academia Nacional de Medicina de Colombia"

    res = qualifier.qualify(
        candidate_name=candidate_name,
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    # 1. The directory page is NOT classified as a distinct locally verified society
    assert res.entity_archetype == EntityArchetype.DIRECTORY_LISTING
    assert res.entity_archetype != EntityArchetype.INDEPENDENT_ORGANIZATION

    # 2. The publisher's domain is NOT assigned to an unresolved listed society
    assert res.source_host == "anmedcolombia.org.co"
    assert res.organization_website == "UNKNOWN"
    assert res.organization_website != "https://anmedcolombia.org.co"

    # 3. Cali is NOT attributed to the publisher merely because it appears in the listing
    assert res.geographic_evidence_status == GeographicEvidenceStatus.LOCATION_UNVERIFIED
    assert res.geographic_evidence_status != GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE

    # 4. READY_FOR_COMMERCIAL_REVIEW is NOT assigned to the composite directory candidate
    assert res.is_commercial_review_ready is False
    assert res.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert res.qualification_status != CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW
    assert "UNRESOLVED_COMPOSITE_DIRECTORY_ENTITY" in res.missing_evidence
    assert "OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN" in res.missing_evidence
    assert "LOCATION_UNVERIFIED_FOR_TARGET_CITY" in res.missing_evidence


def test_web_search_provider_live_pilot_regression(qualifier):
    """Verify WebSearchDiscoveryProvider isolates directory candidates in discover()."""
    synthetic_response = {
        "web": {
            "results": [
                {
                    "title": "Sociedades Afiliadas - Academia Nacional de Medicina de Colombia",
                    "url": "https://anmedcolombia.org.co/sociedades-afiliadas/",
                    "description": "Relación de Sociedades Afiliadas a la Academia. Capítulo Valle del Cauca - Sede Cali.",
                },
                {
                    "title": "Sociedad Colombiana de Pediatría Regional Valle - Inicio",
                    "url": "https://scpvalle.org",
                    "description": "Sitio oficial de la Sociedad Colombiana de Pediatría Regional Valle en Cali. Vigente 2026.",
                },
            ]
        }
    }

    mock_transport = OfflineFixtureWebSearchTransport(fixtures={"test_q": synthetic_response})
    provider = WebSearchDiscoveryProvider(
        transport=mock_transport,
        enabled=True,
        authorized_tenants={"t1"},
        qualifier=qualifier,
    )

    task = DiscoveryTask(
        id="task_pilot",
        query="test_q",
        city="Cali",
        region="Valle del Cauca",
        country="CO",
        category="medical_association",
        metadata={"organization_id": "t1"},
    )

    businesses = provider.discover(task)
    assert len(businesses) == 2

    dir_biz = businesses[0]
    real_biz = businesses[1]

    # Directory candidate must NOT have Cali or Valle del Cauca attributed
    assert dir_biz.city is None
    assert dir_biz.state is None
    assert dir_biz.raw_data["geographic_scope"] == GeographicScope.LOCATION_UNVERIFIED.value
    assert dir_biz.raw_data["geographic_evidence_status"] == GeographicEvidenceStatus.LOCATION_UNVERIFIED.value
    assert dir_biz.raw_data["organization_website"] == "UNKNOWN"
    assert dir_biz.raw_data["is_commercial_review_ready"] is False
    assert dir_biz.raw_data["qualification_status"] == CandidateQualificationStatus.SEARCH_MATCH.value

    # Real single-entity candidate retains its verified Cali presence
    assert real_biz.city == "Cali"
    assert real_biz.state == "Valle del Cauca"
    assert real_biz.raw_data["geographic_scope"] == GeographicScope.REGIONAL_COVERAGE_EVIDENCED.value
    assert real_biz.raw_data["geographic_evidence_status"] == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE.value
    assert real_biz.raw_data["organization_website"] == "https://scpvalle.org"
    assert real_biz.raw_data["is_commercial_review_ready"] is True
    assert real_biz.raw_data["qualification_status"] == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW.value
