"""Targeted tests for Phase P30.5C.1: Overture Provider Mapping & Safe Discovery Execution.

Covers all 20 required verification cases:
1. Verified canonical mapping.
2. Unsupported category rejected.
3. Medical association accepted.
4. Scientific society accepted.
5. Professional association accepted.
6. Generic organization rejected when medical specialization is required but unverified.
7. Clinic excluded.
8. Hospital excluded.
9. Medical office excluded.
10. Pharmacy excluded.
11. Clinical terminology in a genuine association name does not automatically exclude it.
12. Association terminology in a clinic name does not automatically include it.
13. Negative keywords reach the execution filter.
14. Haversine 24.5-mile inclusion.
15. Haversine 26-mile exclusion.
16. Missing coordinates fail closed for radius-constrained tasks.
17. Filtering occurs before import.
18. Original source provenance preserved.
19. Tenant boundaries preserved.
20. Zero external network calls.
"""

import math
import pytest
from unittest.mock import MagicMock

from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.enums import CampaignStatus
from bopclients.domain.exceptions import DiscoveryProviderError
from bopclients.domain.search_intent import SearchIntent
from bopclients.application.search_dto import DiscoveryTask, SearchPlan
from bopclients.application.search_planner import DefaultSearchPlanner
from bopclients.application.interfaces.forge_gateways import (
    IForgeDiscoveryGateway,
    DiscoveryQuery,
    DiscoveredBusiness,
)
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.application.prospect_service import ProspectService
from bopclients.infrastructure.location.static_location_resolver import StaticLocationResolver
from bopclients.infrastructure.providers.overture_provider import (
    OvertureDiscoveryProvider,
    OvertureCandidateValidator,
    haversine_distance_miles,
    CANONICAL_CATEGORY_MAPPINGS,
)
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend

CALI_LAT = 3.4516
CALI_LON = -76.5320
RADIUS_MILES = 25.0
DEG_PER_MILE = 1.0 / (3958.8 * math.pi / 180.0)


class MockDiscoveryGateway(IForgeDiscoveryGateway):
    """Deterministic in-memory gateway returning synthetic test candidates."""

    def __init__(self, candidates=None):
        self.candidates = candidates or []
        self.last_query = None

    def discover_businesses(self, query: DiscoveryQuery):
        self.last_query = query
        return list(self.candidates)


@pytest.fixture
def memory_db():
    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)
    return db


@pytest.fixture
def test_env(memory_db):
    org_repo = OrganizationRepository(memory_db)
    camp_repo = CampaignRepository(memory_db)
    prospect_repo = ProspectRepository(memory_db)
    rr_repo = ResearchRunRepository(memory_db)

    org = org_repo.save(Organization(name="Bop Agencia", slug="bop-agencia"))
    camp = camp_repo.save(
        org.id,
        Campaign(name="Prospección de Asociaciones", status=CampaignStatus.ACTIVE),
    )

    return {
        "db": memory_db,
        "org": org,
        "camp": camp,
        "prospect_repo": prospect_repo,
        "rr_repo": rr_repo,
        "camp_repo": camp_repo,
    }


class TestP305COvertureExecution:
    def test_01_verified_canonical_mapping(self):
        """1. Verified canonical mapping for association categories."""
        gateway = MockDiscoveryGateway()
        provider = OvertureDiscoveryProvider(gateway)

        assert provider.is_category_supported("medical_association") is True
        assert provider.is_category_supported("scientific_society") is True
        assert provider.is_category_supported("professional_association") is True
        assert provider.is_category_supported("non_profit") is True

        assert (
            provider.map_category_to_query_industry("medical_association")
            == "association_or_organization"
        )
        assert (
            provider.map_category_to_query_industry("scientific_society")
            == "association_or_organization"
        )
        assert (
            provider.map_category_to_query_industry("professional_association")
            == "professional_association"
        )
        assert (
            provider.map_category_to_query_industry("non_profit")
            == "non_governmental_organization"
        )

        # Also verify Spanish aliases
        assert (
            provider.map_category_to_query_industry("asociaciones médicas")
            == "association_or_organization"
        )
        assert (
            provider.map_category_to_query_industry("sociedades científicas")
            == "association_or_organization"
        )
        assert (
            provider.map_category_to_query_industry("colegios profesionales")
            == "professional_association"
        )

    def test_02_unsupported_category_rejected(self):
        """2. Unsupported category rejected with clear DiscoveryProviderError."""
        gateway = MockDiscoveryGateway()
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="unsupported_quantum_mining_enterprise",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
        )

        assert provider.supports(task) is False
        with pytest.raises(DiscoveryProviderError) as exc_info:
            provider.discover(task)
        assert "Unsupported category" in str(exc_info.value)
        assert "unsupported_quantum_mining_enterprise" in str(exc_info.value)

    def test_03_medical_association_accepted(self):
        """3. Medical association in Cali within radius is accepted."""
        candidate = DiscoveredBusiness(
            overture_id="ov-med-001",
            name="Asociación Médica del Valle",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            city="Cali",
            state="Valle",
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "hospital", "medical_office", "pharmacy"],
        )

        results = provider.discover(task)
        assert len(results) == 1
        assert results[0].overture_id == "ov-med-001"
        assert results[0].name == "Asociación Médica del Valle"

    def test_04_scientific_society_accepted(self):
        """4. Scientific society in Cali within radius is accepted."""
        candidate = DiscoveredBusiness(
            overture_id="ov-sci-001",
            name="Sociedad Colombiana de Pediatría - Regional Valle",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            city="Cali",
            state="Valle",
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="scientific_society",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "hospital", "medical_office", "pharmacy"],
        )

        results = provider.discover(task)
        assert len(results) == 1
        assert results[0].overture_id == "ov-sci-001"

    def test_05_professional_association_accepted(self):
        """5. Professional health association in Cali within radius is accepted."""
        candidate = DiscoveredBusiness(
            overture_id="ov-prof-001",
            name="Colegio Médico de Cali y Valle del Cauca",
            category="professional_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            city="Cali",
            state="Valle",
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="professional_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "hospital", "medical_office", "pharmacy"],
        )

        results = provider.discover(task)
        assert len(results) == 1
        assert results[0].overture_id == "ov-prof-001"

    def test_06_generic_organization_rejected_without_medical_specialization(self):
        """6. Generic organization rejected when medical specialization is required but unverified."""
        candidate = DiscoveredBusiness(
            overture_id="ov-gen-001",
            name="Club de Leones de Cali Monarca",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            city="Cali",
            state="Valle",
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "hospital", "medical_office", "pharmacy"],
        )

        results = provider.discover(task)
        assert len(results) == 0

    def test_07_clinic_excluded(self):
        """7. Clinic excluded even if within radius."""
        candidates = [
            DiscoveredBusiness(
                overture_id="ov-cln-001",
                name="Clínica Farallones de Cali",
                category="clinic",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
            DiscoveredBusiness(
                overture_id="ov-cln-002",
                name="Clínica de Occidente",
                category="association_or_organization",  # Misclassified source category
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
        ]
        gateway = MockDiscoveryGateway(candidates)
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "clínica", "hospital"],
        )

        results = provider.discover(task)
        assert len(results) == 0

    def test_08_hospital_excluded(self):
        """8. Hospital excluded even if within radius."""
        candidate = DiscoveredBusiness(
            overture_id="ov-hsp-001",
            name="Hospital Universitario del Valle Evaristo García",
            category="hospital",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "hospital"],
        )

        results = provider.discover(task)
        assert len(results) == 0

    def test_09_medical_office_excluded(self):
        """9. Medical office / Consultorio excluded even if within radius."""
        candidates = [
            DiscoveredBusiness(
                overture_id="ov-off-001",
                name="Consultorio Médico San Lucas",
                category="medical_office",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
            DiscoveredBusiness(
                overture_id="ov-off-002",
                name="Consultorio Médico Pediátrico",
                category="association_or_organization",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
        ]
        gateway = MockDiscoveryGateway(candidates)
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "hospital", "medical_office", "consultorio"],
        )

        results = provider.discover(task)
        assert len(results) == 0

    def test_10_pharmacy_excluded(self):
        """10. Pharmacy excluded even if within radius."""
        candidate = DiscoveredBusiness(
            overture_id="ov-phr-001",
            name="Droguería y Farmacia La Rebaja Principal",
            category="pharmacy",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "hospital", "pharmacy", "farmacia"],
        )

        results = provider.discover(task)
        assert len(results) == 0

    def test_11_clinical_terminology_in_genuine_association_not_excluded(self):
        """11. Clinical terminology in a genuine association name does not automatically exclude it."""
        candidate = DiscoveredBusiness(
            overture_id="ov-assoc-clin-001",
            name="Sociedad de Investigación Clínica del Valle",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            city="Cali",
            state="Valle",
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "clínica", "hospital", "pharmacy"],
        )

        results = provider.discover(task)
        assert len(results) == 1
        assert results[0].overture_id == "ov-assoc-clin-001"
        assert results[0].name == "Sociedad de Investigación Clínica del Valle"

    def test_12_association_terminology_in_clinic_not_included(self):
        """12. Association terminology in a clinic name does not automatically include it."""
        candidate_clinic_cat = DiscoveredBusiness(
            overture_id="ov-cln-assoc-001",
            name="Clínica de la Asociación Médica",
            category="clinic",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )
        candidate_assoc_cat = DiscoveredBusiness(
            overture_id="ov-cln-assoc-002",
            name="Clínica de la Asociación Médica",
            category="association_or_organization",  # Misclassified
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )
        gateway = MockDiscoveryGateway([candidate_clinic_cat, candidate_assoc_cat])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "clínica", "hospital"],
        )

        results = provider.discover(task)
        assert len(results) == 0

    def test_13_negative_keywords_reach_execution_filter(self):
        """13. Negative keywords reach the execution filter from SearchIntent through SearchPlan."""
        intent = SearchIntent(
            organization_id="org-123",
            campaign_id="camp-123",
            raw_query="asociaciones medicas en cali",
            target_entity_type="medical_association",
            industries=["medical_association"],
            countries=["CO"],
            cities=["Cali"],
            radius_miles=25.0,
            negative_keywords=["clinic", "hospital", "medical_office", "pharmacy"],
        )
        planner = DefaultSearchPlanner(location_resolver=StaticLocationResolver())
        plan = planner.plan(intent)

        assert len(plan.tasks) == 1
        task = plan.tasks[0]
        assert task.negative_keywords == ["clinic", "hospital", "medical_office", "pharmacy"]

        # Verify gateway query and provider receive them
        gateway = MockDiscoveryGateway()
        provider = OvertureDiscoveryProvider(gateway)
        provider.discover(task)

        assert gateway.last_query is not None
        assert gateway.last_query.negative_keywords == [
            "clinic",
            "hospital",
            "medical_office",
            "pharmacy",
        ]

    def test_14_haversine_24_5_mile_inclusion(self):
        """14. Synthetic candidate at 24.5 miles is included."""
        lat_24_5 = CALI_LAT + (24.5 * DEG_PER_MILE)
        actual_dist = haversine_distance_miles(CALI_LAT, CALI_LON, lat_24_5, CALI_LON)
        assert abs(actual_dist - 24.5) < 0.05

        candidate = DiscoveredBusiness(
            overture_id="ov-dist-24-5",
            name="Asociación Médica Suburbana",
            category="association_or_organization",
            latitude=lat_24_5,
            longitude=CALI_LON,
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
        )

        results = provider.discover(task)
        assert len(results) == 1
        assert results[0].overture_id == "ov-dist-24-5"

    def test_15_haversine_26_mile_exclusion(self):
        """15. Synthetic candidate at 26.0 miles is excluded."""
        lat_26_0 = CALI_LAT + (26.0 * DEG_PER_MILE)
        actual_dist = haversine_distance_miles(CALI_LAT, CALI_LON, lat_26_0, CALI_LON)
        assert abs(actual_dist - 26.0) < 0.05

        candidate = DiscoveredBusiness(
            overture_id="ov-dist-26-0",
            name="Asociación Médica Fuera de Rango",
            category="association_or_organization",
            latitude=lat_26_0,
            longitude=CALI_LON,
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
        )

        results = provider.discover(task)
        assert len(results) == 0

    def test_16_missing_coordinates_fail_closed_for_radius_tasks(self):
        """16. Missing coordinates fail closed for spatially constrained tasks."""
        candidate = DiscoveredBusiness(
            overture_id="ov-no-coords",
            name="Asociación Médica Sin Coordenadas",
            category="association_or_organization",
            latitude=None,
            longitude=None,
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
        )

        results = provider.discover(task)
        assert len(results) == 0

    def test_17_filtering_occurs_before_import(self, test_env):
        """17. Filtering occurs before ProspectService.add_prospect()."""
        org = test_env["org"]
        camp = test_env["camp"]

        lat_24_5 = CALI_LAT + (24.5 * DEG_PER_MILE)
        lat_26_0 = CALI_LAT + (26.0 * DEG_PER_MILE)

        candidates = [
            DiscoveredBusiness(
                overture_id="ov-valid-01",
                name="Asociación de Médicos Especialistas de Cali",
                category="association_or_organization",
                latitude=lat_24_5,
                longitude=CALI_LON,
            ),
            DiscoveredBusiness(
                overture_id="ov-clinic-01",
                name="Clínica Farallones",
                category="clinic",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
            DiscoveredBusiness(
                overture_id="ov-out-01",
                name="Sociedad Médica Distante",
                category="association_or_organization",
                latitude=lat_26_0,
                longitude=CALI_LON,
            ),
            DiscoveredBusiness(
                overture_id="ov-gen-01",
                name="Club de Leones Cali",
                category="association_or_organization",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
            DiscoveredBusiness(
                overture_id="ov-no-coords",
                name="Asociación Médica Desconocida",
                category="association_or_organization",
                latitude=None,
                longitude=None,
            ),
        ]

        gateway = MockDiscoveryGateway(candidates)
        provider = OvertureDiscoveryProvider(gateway)

        mock_prospect_service = MagicMock()
        mock_prospect_service.prospect_repo.find_existing_prospect.return_value = None

        mock_prospect = MagicMock()
        mock_prospect.id = "p-imported-01"
        mock_prospect_service.add_prospect.return_value = mock_prospect

        orchestrator = DiscoveryOrchestrator(
            providers=[provider],
            prospect_service=mock_prospect_service,
            research_run_repo=test_env["rr_repo"],
            campaign_repo=test_env["camp_repo"],
        )

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "hospital"],
        )
        plan = SearchPlan(
            organization_id=org.id,
            campaign_id=camp.id,
            tasks=[task],
        )

        result = orchestrator.execute_plan(plan)

        # EXACTLY 1 candidate must have reached add_prospect
        assert mock_prospect_service.add_prospect.call_count == 1
        called_cmd = mock_prospect_service.add_prospect.call_args[0][0]
        assert called_cmd.forge_record_id == "ov-valid-01"
        assert called_cmd.name == "Asociación de Médicos Especialistas de Cali"
        assert result.total_imported_prospects == 1

    def test_18_original_source_provenance_preserved(self, test_env):
        """18. Original source provenance (overture ID and type) preserved upon prospect import."""
        org = test_env["org"]
        camp = test_env["camp"]
        prospect_repo = test_env["prospect_repo"]
        db = test_env["db"]

        candidate = DiscoveredBusiness(
            overture_id="ov-provenance-789",
            name="Sociedad Colombiana de Cirugía - Capítulo Valle",
            category="association_or_organization",
            website_url="https://cirugiavalle.org",
            phone="+57 2 555 1234",
            address="Calle 5 # 38-20",
            city="Cali",
            state="Valle",
            zip_code="760001",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )

        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)
        prospect_service = ProspectService(prospect_repo, gateway)

        orchestrator = DiscoveryOrchestrator(
            providers=[provider],
            prospect_service=prospect_service,
            research_run_repo=test_env["rr_repo"],
            campaign_repo=test_env["camp_repo"],
        )

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "hospital"],
        )
        plan = SearchPlan(
            organization_id=org.id,
            campaign_id=camp.id,
            tasks=[task],
        )

        result = orchestrator.execute_plan(plan)
        assert result.total_imported_prospects == 1

        imported = result.imported_prospects[0]
        assert imported.name == "Sociedad Colombiana de Cirugía - Capítulo Valle"
        assert imported.forge_record_id == "ov-provenance-789"
        assert imported.source == "overture"

        # Check DB provenance
        sources = db.fetch_dicts(
            "SELECT * FROM prospect_sources WHERE prospect_id = ?",
            (imported.id,),
        )
        assert len(sources) >= 1
        assert sources[0]["source_type"] == "overture"
        assert sources[0]["external_id"] == "ov-provenance-789"

    def test_19_tenant_boundaries_preserved(self, test_env):
        """19. Tenant boundaries strictly preserved during execution."""
        org_a = test_env["org"]
        camp_a = test_env["camp"]
        db = test_env["db"]
        org_repo = OrganizationRepository(db)
        camp_repo = test_env["camp_repo"]

        org_b = org_repo.save(Organization(name="Tenant B", slug="tenant-b"))
        camp_b = camp_repo.save(
            org_b.id,
            Campaign(name="Tenant B Campaign", status=CampaignStatus.ACTIVE),
        )

        candidate = DiscoveredBusiness(
            overture_id="ov-tenant-isolation",
            name="Asociación Médica Aislada",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)
        prospect_service = ProspectService(test_env["prospect_repo"], gateway)

        orchestrator = DiscoveryOrchestrator(
            providers=[provider],
            prospect_service=prospect_service,
            research_run_repo=test_env["rr_repo"],
            campaign_repo=camp_repo,
        )

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
        )
        plan = SearchPlan(
            organization_id=org_a.id,
            campaign_id=camp_a.id,
            tasks=[task],
        )

        result = orchestrator.execute_plan(plan)
        assert result.total_imported_prospects == 1
        prospect_id = result.imported_prospects[0].id

        # Belongs to org_a
        p_a = test_env["prospect_repo"].get_prospect_by_id(org_a.id, prospect_id)
        assert p_a is not None
        assert p_a.organization_id == org_a.id

        # Does NOT belong to org_b
        p_b = test_env["prospect_repo"].get_prospect_by_id(org_b.id, prospect_id)
        assert p_b is None

    def test_20_zero_external_network_calls(self):
        """20. Zero external network calls (runs completely offline with synthetic fixtures)."""
        candidate = DiscoveredBusiness(
            overture_id="ov-offline-01",
            name="Asociación Médica Offline",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
        )

        results = provider.discover(task)
        assert len(results) == 1
        assert results[0].overture_id == "ov-offline-01"

    def test_21_broad_candidate_query_reaches_limit_before_local_classification(self):
        """21. Broad candidate query reaches LIMIT before local classification."""
        raw_candidates = [
            DiscoveredBusiness(
                overture_id="ov-trade-01",
                name="Asociación de Comerciantes de Cali",
                category="association_or_organization",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
            DiscoveredBusiness(
                overture_id="ov-trade-02",
                name="Club de Leones Cali San Fernando",
                category="association_or_organization",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
            DiscoveredBusiness(
                overture_id="ov-trade-03",
                name="Asociación de Ganaderos del Valle",
                category="association_or_organization",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
        ]
        gateway = MockDiscoveryGateway(raw_candidates)
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            limit=3,
        )

        results = provider.discover(task)
        assert len(results) == 0
        assert task.metadata.get("source_sample_truncated") is True
        assert task.metadata["diagnostics"]["raw_retrieved"] == 3
        assert task.metadata["diagnostics"]["sample_truncated"] is True
        assert task.metadata["diagnostics"]["rejected_classification"] == 3

    def test_22_result_truncation_not_represented_as_complete_coverage(self, test_env):
        """22. Result truncation is not represented as complete source coverage (emits SOURCE_SAMPLE_TRUNCATED warning)."""
        org = test_env["org"]
        camp = test_env["camp"]

        raw_candidates = [
            DiscoveredBusiness(
                overture_id="ov-trunc-01",
                name="Asociación de Abogados de Cali",
                category="association_or_organization",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
            DiscoveredBusiness(
                overture_id="ov-trunc-02",
                name="Asociación de Ingenieros del Valle",
                category="association_or_organization",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
        ]
        gateway = MockDiscoveryGateway(raw_candidates)
        provider = OvertureDiscoveryProvider(gateway)
        prospect_service = ProspectService(test_env["prospect_repo"], gateway)

        orchestrator = DiscoveryOrchestrator(
            providers=[provider],
            prospect_service=prospect_service,
            research_run_repo=test_env["rr_repo"],
            campaign_repo=test_env["camp_repo"],
        )

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            limit=2,
        )
        plan = SearchPlan(
            organization_id=org.id,
            campaign_id=camp.id,
            tasks=[task],
        )

        result = orchestrator.execute_plan(plan)
        assert result.total_imported_prospects == 0
        trunc_warnings = [
            w for w in result.warnings if w.code == "SOURCE_SAMPLE_TRUNCATED"
        ]
        assert len(trunc_warnings) == 1
        assert (
            "complete source coverage is not guaranteed"
            in trunc_warnings[0].message
        )
        assert trunc_warnings[0].details["limit"] == 2

    def test_23_duplicate_source_records_across_canonical_tasks_remain_deduplicated(
        self, test_env
    ):
        """23. Duplicate source records across canonical tasks remain deduplicated."""
        org = test_env["org"]
        camp = test_env["camp"]
        prospect_repo = test_env["prospect_repo"]
        db = test_env["db"]

        candidate = DiscoveredBusiness(
            overture_id="ov-pediatria-shared",
            name="Sociedad Colombiana de Pediatría Regional Valle",
            category="association_or_organization",
            website_url="https://pediatriavalle.org",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)
        prospect_service = ProspectService(prospect_repo, gateway)

        orchestrator = DiscoveryOrchestrator(
            providers=[provider],
            prospect_service=prospect_service,
            research_run_repo=test_env["rr_repo"],
            campaign_repo=test_env["camp_repo"],
        )

        task1 = DiscoveryTask(
            id="task-med-01",
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
        )
        task2 = DiscoveryTask(
            id="task-sci-02",
            provider="overture",
            category="scientific_society",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
        )
        plan = SearchPlan(
            organization_id=org.id,
            campaign_id=camp.id,
            tasks=[task1, task2],
        )

        result = orchestrator.execute_plan(plan)
        assert result.total_imported_prospects == 1
        rows = db.fetch_dicts(
            "SELECT * FROM prospects WHERE organization_id = ?", (org.id,)
        )
        assert len(rows) == 1
        assert rows[0]["forge_record_id"] == "ov-pediatria-shared"

    def test_24_primary_and_alternate_category_exclusion_semantics(self):
        """24. Primary and alternate category exclusion semantics."""
        candidate_alt_clinic = DiscoveredBusiness(
            overture_id="ov-alt-clinic",
            name="Asociación Médica San Rafael",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            raw_data={"categories": {"alternate": ["clinic"]}},
        )
        candidate_alt_hospital = DiscoveredBusiness(
            overture_id="ov-alt-hosp",
            name="Sociedad Médica Santa María",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            raw_data={"taxonomy": {"alternates": ["hospital"]}},
        )
        gateway = MockDiscoveryGateway([candidate_alt_clinic, candidate_alt_hospital])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "hospital"],
        )

        results = provider.discover(task)
        assert len(results) == 0
        assert task.metadata["diagnostics"]["rejected_contradictory"] == 2

    def test_25_clinical_terminology_in_genuine_society_name_acceptable(self):
        """25. Clinical terminology in genuine society name remains acceptable."""
        candidate = DiscoveredBusiness(
            overture_id="ov-soc-farm-clin",
            name="Sociedad Colombiana de Farmacología y Toxicología Clínica",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            city="Cali",
            state="Valle",
        )
        gateway = MockDiscoveryGateway([candidate])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="scientific_society",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "clínica", "hospital", "farmacia"],
        )

        results = provider.discover(task)
        assert len(results) == 1
        assert results[0].overture_id == "ov-soc-farm-clin"

    def test_26_contradictory_entity_evidence_fails_closed(self):
        """26. Contradictory entity evidence fails closed."""
        candidate_dual_name = DiscoveredBusiness(
            overture_id="ov-dual-name",
            name="Asociación y Clínica Médica del Pacífico",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )
        candidate_meta_flag = DiscoveredBusiness(
            overture_id="ov-meta-flag",
            name="Sociedad Médica Occidente",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            raw_data={"is_facility": True},
        )
        gateway = MockDiscoveryGateway([candidate_dual_name, candidate_meta_flag])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
        )

        results = provider.discover(task)
        assert len(results) == 0
        assert task.metadata["diagnostics"]["rejected_contradictory"] == 2

    def test_27_exclusions_remain_effective_before_prospect_service_import(
        self, test_env
    ):
        """27. Exclusions remain effective before ProspectService.add_prospect."""
        org = test_env["org"]
        camp = test_env["camp"]

        valid_candidate = DiscoveredBusiness(
            overture_id="ov-safe-01",
            name="Colegio Médico de Cali",
            category="professional_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )
        clinic_with_assoc_in_name = DiscoveredBusiness(
            overture_id="ov-bad-clinic",
            name="Clínica de la Asociación Médica",
            category="clinic",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )
        contradictory_candidate = DiscoveredBusiness(
            overture_id="ov-bad-contra",
            name="Asociación y Clínica Médica San Juan",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )

        gateway = MockDiscoveryGateway(
            [valid_candidate, clinic_with_assoc_in_name, contradictory_candidate]
        )
        provider = OvertureDiscoveryProvider(gateway)

        mock_prospect_service = MagicMock()
        mock_prospect_service.prospect_repo.find_existing_prospect.return_value = None
        mock_p = MagicMock()
        mock_p.id = "p-safe-01"
        mock_prospect_service.add_prospect.return_value = mock_p

        orchestrator = DiscoveryOrchestrator(
            providers=[provider],
            prospect_service=mock_prospect_service,
            research_run_repo=test_env["rr_repo"],
            campaign_repo=test_env["camp_repo"],
        )

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
            negative_keywords=["clinic", "clínica", "hospital"],
        )
        plan = SearchPlan(
            organization_id=org.id,
            campaign_id=camp.id,
            tasks=[task],
        )

        orchestrator.execute_plan(plan)
        assert mock_prospect_service.add_prospect.call_count == 1
        called_cmd = mock_prospect_service.add_prospect.call_args[0][0]
        assert called_cmd.forge_record_id == "ov-safe-01"

    def test_28_radius_boundary_remains_correct(self):
        """28. Radius boundary remains correct: 25.0 miles included, 25.01 miles excluded."""
        lat_25_00 = CALI_LAT + (25.00 * DEG_PER_MILE)
        lat_25_01 = CALI_LAT + (25.01 * DEG_PER_MILE)

        cand_25_00 = DiscoveredBusiness(
            overture_id="ov-bound-25-00",
            name="Asociación Médica en el Límite Exacto",
            category="association_or_organization",
            latitude=lat_25_00,
            longitude=CALI_LON,
        )
        cand_25_01 = DiscoveredBusiness(
            overture_id="ov-bound-25-01",
            name="Asociación Médica Apenas Fuera del Límite",
            category="association_or_organization",
            latitude=lat_25_01,
            longitude=CALI_LON,
        )

        gateway = MockDiscoveryGateway([cand_25_00, cand_25_01])
        provider = OvertureDiscoveryProvider(gateway)

        task = DiscoveryTask(
            provider="overture",
            category="medical_association",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            radius_miles=RADIUS_MILES,
        )

        results = provider.discover(task)
        assert len(results) == 1
        assert results[0].overture_id == "ov-bound-25-00"
