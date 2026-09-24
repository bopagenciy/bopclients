"""Comprehensive offline unit and integration tests for P30.5G.5F Structured Candidate Qualification Foundation.

Verifies:
1. Synthetic Fixtures A through J covering medical and non-medical B2B profiles:
   A. Medical training program misidentified as a society.
   B. National medical federation without verified Cali presence.
   C. Historical student society (GeoCities archive).
   D. Current professional medical association with verified required geographic evidence.
   E. Construction training page vs active construction company.
   F. Industrial catalog page vs independent distributor.
   G. University software club vs active B2B SaaS company.
   H. Recipe page vs actual local restaurant.
   I. Directory result mentioning an organization but lacking official website evidence.
   J. Relevant national entity allowed by a nationwide ICP.
2. WebSearchDiscoveryProvider integration populating candidate qualification fields.
3. DiscoveryOrchestrator.preview_plan() zero-persistence mapping with qualification contracts.
4. FastApi POST /api/v1/discovery/preview contract verification with backward compatibility.
5. Strict socket guard: zero external requests (no Tavily, no Overture, no Gemini).
"""

import socket
import pytest
from unittest.mock import patch
from starlette.testclient import TestClient

from bopclients.domain.candidate_qualification import (
    CandidateQualificationStatus,
    EntityArchetype,
    GeographicEvidenceStatus,
    CurrentActivityStatus,
    CandidateQualificationResult,
)
from bopclients.application.discovery.candidate_qualifier import (
    OrganizationCandidateQualifier,
)
from bopclients.application.discovery.candidate_classifier import (
    CandidateClassificationRequest,
    CandidateClassificationStatus,
    ClassificationDecision,
    OrganizationCandidateClassifier,
)
from bopclients.application.search_dto import DiscoveryTask, SearchPlan
from bopclients.infrastructure.providers.web_search_provider import (
    WebSearchDiscoveryProvider,
    OfflineFixtureWebSearchTransport,
    GeographicScope,
)
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.application.prospect_service import ProspectService
from bopclients.api.app import create_bopclients_api_app
from bopclients.runtime.container import build_runtime_container
from bopclients.runtime.settings import RuntimeSettings
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.campaign import Campaign
from bopclients.domain.enums import CampaignStatus, MemberRole
from bopclients.domain.icp import IdealCustomerProfile, TargetMarket
from bopclients.infrastructure.db.connection import create_database_connection


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
# 1. Ten Synthetic Fixture Tests (A through J)
# =====================================================================

def test_fixture_a_medical_training_program(qualifier, classifier):
    """Fixture A: Medical training program misidentified as a society."""
    raw_title = "Programas Científicos Activos - Diplomado en Auditoría Médica"
    url = "https://expedientesmedicos.com.co/programascientificosactivos/diplomado-auditoria"
    snippet = "Oferta académica y cursos de capacitación médica continua y diplomados clínicos en Cali."
    name = "Diplomado en Auditoría Médica y Gestión Clínica"
    task = DiscoveryTask(id="t1", city="Cali", country="CO", category="medical_association")

    # Base classification decision (simulating accepted or lexical hit)
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )

    result = qualifier.qualify(
        candidate_name=name,
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert result.entity_archetype == EntityArchetype.INTERNAL_PROGRAM
    assert result.organization_website == "UNKNOWN"
    assert result.is_commercial_review_ready is False
    assert result.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "INTERNAL_PROGRAM_NOT_ORGANIZATION" in result.missing_evidence


def test_fixture_b_national_federation_without_cali_presence(qualifier):
    """Fixture B: National medical federation without verified Cali presence."""
    raw_title = "Federación Médica Colombiana - Sede Central Bogotá"
    url = "https://federacionmedicacolombiana.org"
    snippet = "Confederación de colegios médicos y sociedades científicas de Colombia. Sede principal Bogotá D.C."
    name = "Federación Médica Colombiana"
    task = DiscoveryTask(id="t2", city="Cali", country="CO", category="medical_association", metadata={"allow_national": False})

    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )

    result = qualifier.qualify(
        candidate_name=name,
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert result.entity_archetype == EntityArchetype.FEDERATION
    assert result.source_host == "federacionmedicacolombiana.org"
    assert result.organization_website == "https://federacionmedicacolombiana.org"
    # Geographic scope is national, but Cali presence is unverified (or mismatch with Bogotá)
    assert result.geographic_evidence_status in (
        GeographicEvidenceStatus.NATIONAL_SCOPE,
        GeographicEvidenceStatus.GEOGRAPHIC_MISMATCH,
    )
    assert result.is_commercial_review_ready is False
    assert result.qualification_status == CandidateQualificationStatus.SEARCH_MATCH


def test_fixture_c_historical_student_society(qualifier):
    """Fixture C: Historical student society on GeoCities archive."""
    raw_title = "ACEMLI - Asociación Científica de Estudiantes de Medicina (Sitio Archivado)"
    url = "https://www.oocities.org/acemli_valle/index.html"
    snippet = "Página archivada en GeoCities de la asociación científica de estudiantes de medicina de Cali (1995)."
    name = "Asociación Científica de Estudiantes de Medicina del Valle"
    task = DiscoveryTask(id="t3", city="Cali", country="CO", category="medical_association")

    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )

    result = qualifier.qualify(
        candidate_name=name,
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert result.entity_archetype in (
        EntityArchetype.HISTORICAL_REFERENCE,
        EntityArchetype.STUDENT_ORGANIZATION,
    )
    assert result.organization_website == "UNKNOWN"
    assert result.current_activity_status == CurrentActivityStatus.HISTORICAL_ACTIVITY_ONLY
    assert result.is_commercial_review_ready is False
    assert result.qualification_status == CandidateQualificationStatus.SEARCH_MATCH


def test_fixture_d_current_professional_medical_association_verified(qualifier):
    """Fixture D: Current professional medical association with verified Cali evidence."""
    raw_title = "Sociedad Colombiana de Pediatría Regional Valle del Cauca"
    url = "https://scpvalle.org"
    snippet = "Asociación gremial médica y científica que reúne a los médicos pediatras del Valle del Cauca y Cali. Vigente 2026."
    name = "Sociedad Colombiana de Pediatría Regional Valle"
    task = DiscoveryTask(id="t4", city="Cali", country="CO", category="medical_association")

    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )

    result = qualifier.qualify(
        candidate_name=name,
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title=raw_title,
        url=url,
        snippet=snippet,
        task=task,
    )

    assert result.entity_archetype == EntityArchetype.PROFESSIONAL_ASSOCIATION
    assert result.geographic_evidence_status == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE
    assert result.current_activity_status == CurrentActivityStatus.CURRENT_ACTIVITY_EVIDENCED
    assert result.organization_website == "https://scpvalle.org"
    assert result.is_commercial_review_ready is True
    assert result.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW
    assert "READY_FOR_COMMERCIAL_REVIEW" in result.qualification_reasons


def test_fixture_e_construction_training_vs_active_company(qualifier):
    """Fixture E: Construction training page versus active construction company."""
    task = DiscoveryTask(id="t5", city="Cali", country="CO", category="construction")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )

    # 1. Training page
    res_training = qualifier.qualify(
        candidate_name="Cursos y Capacitación en Obras Civiles",
        target_intent="construction",
        base_classification=base_decision,
        raw_title="Cursos de Capacitación Técnica en Construcción",
        url="https://cursoconstruccion.com/programas/curso-albanileria",
        snippet="Oferta académica y cursos de capacitación técnica en obras de construcción en Cali.",
        task=task,
    )
    assert res_training.entity_archetype == EntityArchetype.INTERNAL_PROGRAM
    assert res_training.organization_website == "UNKNOWN"
    assert res_training.is_commercial_review_ready is False
    assert res_training.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "EDUCATIONAL_PROGRAM_NOT_CONTRACTOR" in res_training.missing_evidence

    # 2. Genuine construction company
    res_company = qualifier.qualify(
        candidate_name="Constructora del Valle S.A.S.",
        target_intent="construction",
        base_classification=base_decision,
        raw_title="Constructora del Valle S.A.S. - Edificaciones y Obras Civiles",
        url="https://constructoradelvalle.com.co",
        snippet="Empresa constructora líder en edificaciones y obras de ingeniería civil en Cali. Vigente 2026.",
        task=task,
    )
    assert res_company.entity_archetype == EntityArchetype.COMMERCIAL_ENTERPRISE
    assert res_company.organization_website == "https://constructoradelvalle.com.co"
    assert res_company.geographic_evidence_status == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE
    assert res_company.current_activity_status == CurrentActivityStatus.CURRENT_ACTIVITY_EVIDENCED
    assert res_company.is_commercial_review_ready is True
    assert res_company.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW


def test_fixture_f_industrial_catalog_vs_distributor(qualifier):
    """Fixture F: Industrial catalog page versus independent distributor."""
    task = DiscoveryTask(id="t6", city="Cali", country="CO", category="industrial_distributor")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )

    # 1. Catalog page
    res_catalog = qualifier.qualify(
        candidate_name="Guía de Válvulas y Tuberías Industriales",
        target_intent="industrial_distributor",
        base_classification=base_decision,
        raw_title="Guía de Compra y Catálogo de Productos Industriales",
        url="https://catalogoindustrial.com/articulos/valvulas-catalogo",
        snippet="Artículo técnico sobre tipos de válvulas y tuberías industriales disponibles en Colombia.",
        task=task,
    )
    assert res_catalog.entity_archetype == EntityArchetype.ARTICLE_OR_PUBLICATION
    assert res_catalog.organization_website == "UNKNOWN"
    assert res_catalog.is_commercial_review_ready is False
    assert res_catalog.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "PRODUCT_CATALOG_NOT_DISTRIBUTOR" in res_catalog.missing_evidence

    # 2. Authentic industrial distributor
    res_distributor = qualifier.qualify(
        candidate_name="Distribuidora Industrial de Occidente S.A.S.",
        target_intent="industrial_distributor",
        base_classification=base_decision,
        raw_title="Distribuidora Industrial de Occidente S.A.S. - Suministros",
        url="https://distribuidoradeoccidente.com",
        snippet="Venta mayorista de válvulas y suministros industriales para empresas en Cali y Valle. Vigente 2026.",
        task=task,
    )
    assert res_distributor.entity_archetype == EntityArchetype.COMMERCIAL_ENTERPRISE
    assert res_distributor.organization_website == "https://distribuidoradeoccidente.com"
    assert res_distributor.geographic_evidence_status == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE
    assert res_distributor.is_commercial_review_ready is True
    assert res_distributor.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW


def test_fixture_g_software_club_vs_b2b_saas(qualifier):
    """Fixture G: University software club versus active B2B SaaS company."""
    task = DiscoveryTask(id="t7", city="Cali", country="CO", category="b2b_software")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )

    # 1. Student coding club
    res_club = qualifier.qualify(
        candidate_name="Club de Programación y Desarrollo Estudiantil",
        target_intent="b2b_software",
        base_classification=base_decision,
        raw_title="Club de Programación Estudiantil - Facultad de Ingeniería",
        url="https://universidad.edu.co/club-software",
        snippet="Semillero estudiantil y coding club de estudiantes de ingeniería en software en Cali.",
        task=task,
    )
    assert res_club.entity_archetype == EntityArchetype.STUDENT_ORGANIZATION
    assert res_club.is_commercial_review_ready is False
    assert res_club.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "ACADEMIC_CLUB_NOT_B2B_COMPANY" in res_club.missing_evidence

    # 2. Genuine B2B SaaS company
    res_saas = qualifier.qualify(
        candidate_name="CloudMetrics S.A.S.",
        target_intent="b2b_software",
        base_classification=base_decision,
        raw_title="CloudMetrics S.A.S. - Plataforma de Software B2B",
        url="https://cloudmetrics.co",
        snippet="Plataforma de software B2B SaaS para gestión empresarial y análisis de datos en Cali. Vigente 2026.",
        task=task,
    )
    assert res_saas.entity_archetype == EntityArchetype.COMMERCIAL_ENTERPRISE
    assert res_saas.organization_website == "https://cloudmetrics.co"
    assert res_saas.is_commercial_review_ready is True
    assert res_saas.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW


def test_fixture_h_recipe_page_vs_restaurant(qualifier):
    """Fixture H: Recipe page versus actual local restaurant."""
    task = DiscoveryTask(id="t8", city="Cali", country="CO", category="restaurant")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )

    # 1. Recipe page
    res_recipe = qualifier.qualify(
        candidate_name="Cómo preparar la auténtica pizza napolitana",
        target_intent="restaurant",
        base_classification=base_decision,
        raw_title="Receta de Pizza Napolitana Casera Paso a Paso",
        url="https://recetascocina.com/recetas/pizza-artesanal",
        snippet="Aprende cómo preparar una deliciosa pizza artesanal paso a paso con masa fermentada.",
        task=task,
    )
    assert res_recipe.entity_archetype == EntityArchetype.ARTICLE_OR_PUBLICATION
    assert res_recipe.organization_website == "UNKNOWN"
    assert res_recipe.is_commercial_review_ready is False
    assert res_recipe.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "RECIPE_NOT_DINING_ESTABLISHMENT" in res_recipe.missing_evidence

    # 2. Authentic local restaurant
    res_restaurant = qualifier.qualify(
        candidate_name="Trattoria Da Luigi",
        target_intent="restaurant",
        base_classification=base_decision,
        raw_title="Trattoria Da Luigi - Restaurante Italiano en Cali",
        url="https://trattoriadaluigi.com",
        snippet="Restaurante italiano tradicional en Granada, Cali. Especialidad en pizzas y pastas. Reservas 2026.",
        task=task,
    )
    assert res_restaurant.entity_archetype == EntityArchetype.COMMERCIAL_ENTERPRISE
    assert res_restaurant.organization_website == "https://trattoriadaluigi.com"
    assert res_restaurant.geographic_evidence_status == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE
    assert res_restaurant.is_commercial_review_ready is True
    assert res_restaurant.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW


def test_fixture_i_directory_result_lacks_official_website(qualifier):
    """Fixture I: Directory result mentioning an organization but lacking official website evidence."""
    task = DiscoveryTask(id="t9", city="Cali", country="CO", category="medical_association")
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )

    res_dir = qualifier.qualify(
        candidate_name="Asociación Médica de Cali en Páginas Amarillas",
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title="Directorio Telefónico y Perfil de Asociación Médica",
        url="https://www.paginasamarillas.com.co/empresas/asociacion-medica-cali",
        snippet="Listado de empresas y asociaciones médicas en Cali Valle. Teléfono y dirección en directorio.",
        task=task,
    )

    assert res_dir.entity_archetype == EntityArchetype.DIRECTORY_LISTING
    assert res_dir.source_host == "paginasamarillas.com.co"
    assert res_dir.organization_website == "UNKNOWN"
    assert res_dir.is_commercial_review_ready is False
    assert res_dir.qualification_status == CandidateQualificationStatus.SEARCH_MATCH
    assert "OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN" in res_dir.missing_evidence


def test_fixture_j_national_entity_allowed_by_nationwide_icp(qualifier):
    """Fixture J: Relevant national entity allowed by a nationwide ICP."""
    task = DiscoveryTask(
        id="t10",
        city=None,
        region=None,
        country="CO",
        category="medical_association",
        metadata={"allow_national": True},
    )
    base_decision = ClassificationDecision(
        status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
        is_valid=True,
    )

    result = qualifier.qualify(
        candidate_name="Sociedad Colombiana de Cardiología",
        target_intent="medical_association",
        base_classification=base_decision,
        raw_title="Sociedad Colombiana de Cardiología y Cirugía Cardiovascular",
        url="https://scc.org.co",
        snippet="Sociedad científica y gremial de cobertura nacional en Colombia. Vigente 2026.",
        task=task,
    )

    assert result.entity_archetype == EntityArchetype.PROFESSIONAL_ASSOCIATION
    assert result.geographic_evidence_status == GeographicEvidenceStatus.NATIONAL_SCOPE
    assert result.current_activity_status == CurrentActivityStatus.CURRENT_ACTIVITY_EVIDENCED
    assert result.organization_website == "https://scc.org.co"
    assert result.is_commercial_review_ready is True
    assert result.qualification_status == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW


# =====================================================================
# 2. WebSearchDiscoveryProvider Integration Tests
# =====================================================================

def test_web_search_provider_populates_qualification_fields():
    """Verify that WebSearchDiscoveryProvider runs qualifier and populates raw_data."""
    fixtures = {
        "sociedad pediatria cali": {
            "query": {"original": "sociedad pediatria cali", "more_results_available": False},
            "web": {
                "results": [
                    {
                        "title": "Sociedad Colombiana de Pediatría - Regional Valle del Cauca",
                        "url": "https://scpvalle.org",
                        "description": "Asociación gremial médica y científica en Cali y Valle del Cauca. Vigente 2026.",
                    },
                    {
                        "title": "Diplomado en Auditoría Médica",
                        "url": "https://expedientesmedicos.com.co/programascientificosactivos",
                        "description": "Programas científicos activos y cursos médicos continuos.",
                    },
                ]
            },
        }
    }
    transport = OfflineFixtureWebSearchTransport(fixtures)
    provider = WebSearchDiscoveryProvider(
        transport=transport,
        enabled=True,
        authorized_tenants={"tenant-a"},
    )

    task = DiscoveryTask(
        id="task-qual-01",
        query="sociedad pediatria cali",
        city="Cali",
        country="CO",
        category="medical_association",
        metadata={"organization_id": "tenant-a"},
    )

    discovered = provider.discover(task)
    assert len(discovered) == 1  # Only genuine association passes base classification

    biz = discovered[0]
    assert "Sociedad Colombiana de Pediatría" in biz.name
    assert biz.raw_data["qualification_status"] == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW.value
    assert biz.raw_data["entity_archetype"] == EntityArchetype.PROFESSIONAL_ASSOCIATION.value
    assert biz.raw_data["geographic_evidence_status"] == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE.value
    assert biz.raw_data["current_activity_status"] == CurrentActivityStatus.CURRENT_ACTIVITY_EVIDENCED.value
    assert biz.raw_data["source_url"] == "https://scpvalle.org"
    assert biz.raw_data["source_host"] == "scpvalle.org"
    assert biz.raw_data["organization_website"] == "https://scpvalle.org"
    assert biz.raw_data["is_commercial_review_ready"] is True
    assert "READY_FOR_COMMERCIAL_REVIEW" in biz.raw_data["qualification_reasons"]


# =====================================================================
# 3. DiscoveryOrchestrator preview_plan() Candidate Mapping Tests
# =====================================================================

def test_discovery_orchestrator_preview_plan_maps_qualification():
    """Verify that preview_plan transfers qualification fields to candidates."""
    fixtures = {
        "sociedad cardiologia cali": {
            "query": {"original": "sociedad cardiologia cali", "more_results_available": False},
            "web": {
                "results": [
                    {
                        "title": "Sociedad Colombiana de Cardiología - Capítulo Valle",
                        "url": "https://sccvalle.org",
                        "description": "Sociedad científica para médicos cardiólogos con sede en Cali. Vigente 2026.",
                    },
                ]
            },
        }
    }
    transport = OfflineFixtureWebSearchTransport(fixtures)
    provider = WebSearchDiscoveryProvider(
        transport=transport,
        enabled=True,
        authorized_tenants={"tenant-orch"},
    )
    orchestrator = DiscoveryOrchestrator(
        providers=[provider],
        prospect_service=None,
        research_run_repo=None,
    )

    task = DiscoveryTask(
        id="task-prev-01",
        provider="web_search",
        query="sociedad cardiologia cali",
        city="Cali",
        country="CO",
        category="medical_association",
        limit=5,
        metadata={"organization_id": "tenant-orch"},
    )
    plan = SearchPlan(
        id="plan-prev-01",
        organization_id="tenant-orch",
        tasks=[task],
    )

    exec_result = orchestrator.preview_plan(plan)
    assert len(exec_result.candidates) == 1
    cand = exec_result.candidates[0]

    assert "Sociedad Colombiana de Cardiología" in cand["name"]
    assert cand["qualification_status"] == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW.value
    assert cand["entity_archetype"] == EntityArchetype.PROFESSIONAL_ASSOCIATION.value
    assert cand["geographic_evidence_status"] == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE.value
    assert cand["current_activity_status"] == CurrentActivityStatus.CURRENT_ACTIVITY_EVIDENCED.value
    assert cand["source_url"] == "https://sccvalle.org"
    assert cand["source_host"] == "sccvalle.org"
    assert cand["organization_website"] == "https://sccvalle.org"
    assert cand["is_commercial_review_ready"] is True
    # Verify zero persistence
    assert exec_result.prospects_created == 0
    assert exec_result.total_imported_prospects == 0
    assert exec_result.research_run_id == ""


# =====================================================================
# 4. API POST /api/v1/discovery/preview Integration & Backward Compat
# =====================================================================

@pytest.fixture
def api_test_client(tmp_path):
    """Set up isolated API TestClient with authorized tenant and mock provider."""
    import uuid
    db_file = tmp_path / "test_api_qual.db"
    db_url = f"sqlite:///{db_file}"
    conn = create_database_connection(db_url)

    from bopclients.runtime.db_migrator import DatabaseMigrator
    DatabaseMigrator.migrate(conn)

    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    settings = RuntimeSettings(
        database_url=db_url,
        environment="test",
        tavily_enabled=True,
        tavily_authorized_tenants=[org_id],
    )
    container = build_runtime_container(settings, db=conn)

    # Seed Organization and Admin User
    org = Organization(
        id=org_id,
        bop_organization_id=str(uuid.uuid4()),
        name="Test API Qual Org",
        slug="test-api-qual-org",
    )
    container.org_repo.save(org)

    admin_user = container.auth_service.register_user(
        email="admin@testqual.org",
        name="Admin Qual",
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

    # Register fixtures into web provider
    fixtures = {
        "sociedad medicina cali": {
            "query": {"original": "sociedad medicina cali", "more_results_available": False},
            "web": {
                "results": [
                    {
                        "title": "Sociedad Médica de Cali",
                        "url": "https://sociedadmedicacali.org",
                        "description": "Asociación médica y científica en Cali. Agenda y contacto vigente 2026.",
                    }
                ]
            },
        }
    }
    fixture_transport = OfflineFixtureWebSearchTransport(fixtures)
    web_prov = container.discovery_orchestrator.providers["web_search"]
    web_prov._transport = fixture_transport
    web_prov.enabled = True
    web_prov.authorized_tenants.add(org_id)

    app = create_bopclients_api_app(container=container)
    client = TestClient(app)

    token = container.auth_service.authenticate("admin@testqual.org", "Password123!").access_token
    return {
        "client": client,
        "org_id": org_id,
        "user_id": admin_user.id,
        "headers": {
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": org_id,
            "X-Bop-Organization-Id": org_id,
        },
    }


def test_api_preview_returns_qualification_metadata(api_test_client):
    """Verify that POST /api/v1/discovery/preview exposes all qualification fields."""
    c = api_test_client["client"]
    headers = api_test_client["headers"]

    payload = {
        "provider": "web_search",
        "raw_query": "sociedad medicina cali",
    }

    resp = c.post("/api/v1/discovery/preview", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "completed"
    assert data["candidates_count"] == 1
    assert data["prospects_inserted"] == 0
    assert data["database_writes"] == 0

    candidate = data["candidates"][0]
    # Existing fields preserved
    assert candidate["name"] == "Sociedad Médica de Cali"
    assert candidate["website_url"] == "https://sociedadmedicacali.org"
    assert candidate["classification_status"] == CandidateClassificationStatus.ACCEPTED_CANDIDATE.value
    # Additive qualification fields present
    assert candidate["qualification_status"] == CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW.value
    assert candidate["entity_archetype"] == EntityArchetype.PROFESSIONAL_ASSOCIATION.value
    assert candidate["geographic_evidence_status"] == GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE.value
    assert candidate["current_activity_status"] == CurrentActivityStatus.CURRENT_ACTIVITY_EVIDENCED.value
    assert candidate["source_url"] == "https://sociedadmedicacali.org"
    assert candidate["source_host"] == "sociedadmedicacali.org"
    assert candidate["organization_website"] == "https://sociedadmedicacali.org"
    assert candidate["is_commercial_review_ready"] is True
    assert "READY_FOR_COMMERCIAL_REVIEW" in candidate["qualification_reasons"]
