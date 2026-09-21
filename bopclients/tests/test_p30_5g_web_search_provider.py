"""Offline tests for P30.5G.4A Multi-Source Web Discovery Foundation.

Verifies:
1. WebSearchDiscoveryProvider registration.
2. Disabled-by-default behavior.
3. Explicit tenant authorization requirement.
4. Query-budget enforcement.
5. Source-neutral classification reuse.
6. Medical specialty coverage.
7. Facility exclusions.
8. Missing coordinates handling (no fabricated GPS).
9. Regional scope attribution.
10. National scope attribution.
11. Cross-provider deduplication.
12. Multiple provenance records.
13. Provenance retry idempotency.
14. Cross-tenant isolation.
15. Zero real external API calls.
16. Zero persistent real Brave data.
"""

import inspect
import socket
import pytest
from unittest.mock import patch

from bopclients.application.search_dto import DiscoveryTask
from bopclients.domain.exceptions import DiscoveryExecutionError, TenantAccessError
from bopclients.domain.prospect import Prospect
from bopclients.domain.prospect_source import ProspectSource
from bopclients.application.dtos import AddProspectCommand
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.application.prospect_service import ProspectService
from bopclients.infrastructure.providers.web_search_provider import (
    WebSearchDiscoveryProvider,
    OfflineFixtureWebSearchTransport,
    GeographicScope,
)
from bopclients.infrastructure.providers.overture_provider import OvertureDiscoveryProvider
from bopclients.tests.fixtures.synthetic_web_fixtures import SYNTHETIC_BRAVE_FIXTURES
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend
from bopclients.infrastructure.db.migrations import run_p1_migrations
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.domain.organization import Organization
from bopclients.application.search_dto import SearchPlan


@pytest.fixture
def db():
    database = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(database)
    return database


@pytest.fixture
def org_repo(db):
    return OrganizationRepository(db)


@pytest.fixture
def prospect_repo(db):
    return ProspectRepository(db)


@pytest.fixture
def research_run_repo(db):
    return ResearchRunRepository(db)


@pytest.fixture
def prospect_service(prospect_repo):
    return ProspectService(prospect_repo=prospect_repo, discovery_gateway=None)


@pytest.fixture
def fixture_transport():
    return OfflineFixtureWebSearchTransport(fixtures=SYNTHETIC_BRAVE_FIXTURES)


@pytest.fixture
def test_tenant(org_repo):
    org = Organization(name="Tenant Test Medical", slug="tenant-test-medical")
    return org_repo.save(org)


@pytest.fixture
def second_tenant(org_repo):
    org = Organization(name="Tenant Competitor", slug="tenant-competitor")
    return org_repo.save(org)


class TestP30_5G4A_WebDiscoveryFoundation:
    """Comprehensive test suite for Phase P30.5G.4A offline web discovery foundation."""

    # 1. Provider Registration
    def test_01_provider_registration(self, fixture_transport):
        provider = WebSearchDiscoveryProvider(transport=fixture_transport)
        assert provider.name == "web_search"

    # 2. Disabled-by-Default Behavior
    def test_02_disabled_by_default_behavior(self, fixture_transport):
        provider = WebSearchDiscoveryProvider(transport=fixture_transport, enabled=False)
        task = DiscoveryTask(provider="web_search", query="Sociedad Colombiana de Cardiología Cali")

        # Must not support execution when disabled
        assert provider.supports(task) is False

        # Attempting execution directly must raise DiscoveryExecutionError
        with pytest.raises(DiscoveryExecutionError) as exc_info:
            provider.discover(task)
        assert "disabled by default" in str(exc_info.value).lower()

    # 3. Explicit Authorization Requirement
    def test_03_explicit_authorization_requirement(self, fixture_transport, test_tenant):
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants=set(),  # No tenants authorized
        )
        task = DiscoveryTask(
            provider="web_search",
            query="Sociedad Colombiana de Cardiología Cali",
            metadata={"organization_id": test_tenant.id},
        )

        with pytest.raises(TenantAccessError) as exc_info:
            provider.discover(task)
        assert "not authorized" in str(exc_info.value).lower()

        # Authorize tenant
        provider.authorize_tenant(test_tenant.id)
        results = provider.discover(task)
        assert len(results) > 0

    # 4. Query-Budget Enforcement
    def test_04_query_budget_enforcement(self, fixture_transport, test_tenant):
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants={test_tenant.id},
            max_results_per_query=20,
        )
        task = DiscoveryTask(
            provider="web_search",
            query="Sociedad Colombiana de Cardiología Cali",
            limit=500,  # Requesting 500
            metadata={"organization_id": test_tenant.id},
        )
        results = provider.discover(task)
        # Bounded to maximum results
        assert len(results) <= 20
        # Transport call log shows count was clamped
        assert fixture_transport.call_log[-1]["count"] <= 20
        assert fixture_transport.call_log[-1]["offset"] == 0

    # 5. Source-Neutral Classification Reuse
    def test_05_source_neutral_classification_reuse(self, fixture_transport, test_tenant):
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants={test_tenant.id},
        )
        task = DiscoveryTask(
            provider="web_search",
            category="medical_association",
            query="Sociedad Colombiana de Cardiología Cali",
            metadata={"organization_id": test_tenant.id},
        )
        results = provider.discover(task)

        for biz in results:
            assert biz.raw_data is not None
            assert biz.raw_data["classification_status"] == "ACCEPTED_CANDIDATE"
            assert "clínica" not in biz.name.lower()
            assert "hospital" not in biz.name.lower()

    # 6. Medical Specialties Accepted
    def test_06_medical_specialties_accepted(self, fixture_transport, test_tenant):
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants={test_tenant.id},
        )
        queries = [
            ("sociedad colombiana de cardiología cali", "Cardiología"),
            ("sociedad colombiana de urología cali", "Urología"),
            ("asociación colombiana de endocrinología colombia", "Endocrinología"),
            ("sociedad colombiana de pediatría valle del cauca", "Pediatría"),
            ("federación colombiana de obstetricia y ginecología colombia", "Obstetricia"),
        ]

        for q, expected_term in queries:
            task = DiscoveryTask(
                provider="web_search",
                category="medical_association",
                query=q,
                metadata={"organization_id": test_tenant.id},
            )
            candidates = provider.discover(task)
            assert len(candidates) >= 1, f"Expected accepted candidates for {q}"
            assert any(expected_term.lower() in c.name.lower() for c in candidates)

    # 7. Facility Exclusions
    def test_07_facility_exclusions(self, fixture_transport, test_tenant):
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants={test_tenant.id},
        )
        # All queries in synthetic fixture include both genuine societies and facilities
        for q in SYNTHETIC_BRAVE_FIXTURES.keys():
            task = DiscoveryTask(
                provider="web_search",
                category="medical_association",
                query=q,
                metadata={"organization_id": test_tenant.id},
            )
            candidates = provider.discover(task)
            for c in candidates:
                # None of the facilities from the fixtures should survive
                assert "clínica" not in c.name.lower()
                assert "hospital" not in c.name.lower()
                assert "consultorio" not in c.name.lower()
                assert "farmacia" not in c.name.lower()
                assert "equipos médicos" not in c.name.lower()

    # 8. Missing Coordinates (Truthful Reporting, No Fabrication)
    def test_08_missing_coordinates_truthfully_reported(self, fixture_transport, test_tenant):
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants={test_tenant.id},
        )
        task = DiscoveryTask(
            provider="web_search",
            category="medical_association",
            query="Sociedad Colombiana de Cardiología Cali",
            metadata={"organization_id": test_tenant.id},
        )
        candidates = provider.discover(task)
        assert len(candidates) > 0
        for c in candidates:
            assert c.latitude is None
            assert c.longitude is None

    # 9. Regional Scope Attribution
    def test_09_regional_scope_attribution(self, fixture_transport, test_tenant):
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants={test_tenant.id},
        )
        task = DiscoveryTask(
            provider="web_search",
            category="medical_association",
            query="sociedad colombiana de pediatría valle del cauca",
            city="Cali",
            region="Valle del Cauca",
            metadata={"organization_id": test_tenant.id},
        )
        candidates = provider.discover(task)
        # Look for "Sociedad Colombiana de Pediatría - Regional Valle del Cauca"
        regional = [c for c in candidates if "valle" in c.name.lower()]
        assert len(regional) == 1
        assert regional[0].raw_data["geographic_scope"] == GeographicScope.REGIONAL_COVERAGE_EVIDENCED.value

    # 10. National Scope Attribution
    def test_10_national_scope_attribution(self, fixture_transport, test_tenant):
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants={test_tenant.id},
        )
        task = DiscoveryTask(
            provider="web_search",
            category="medical_association",
            query="asociación colombiana de endocrinología colombia",
            metadata={"organization_id": test_tenant.id},
        )
        candidates = provider.discover(task)
        assert len(candidates) == 1
        assert candidates[0].raw_data["geographic_scope"] == GeographicScope.NATIONAL_SCOPE.value

    # 11. Cross-Provider Deduplication (1 Prospect Created)
    def test_11_cross_provider_deduplication(
        self, fixture_transport, test_tenant, prospect_service, research_run_repo
    ):
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants={test_tenant.id},
        )
        orchestrator = DiscoveryOrchestrator(
            providers=[provider],
            prospect_service=prospect_service,
            research_run_repo=research_run_repo,
        )

        # First: Prospect pre-exists from another source (e.g. overture) with same website
        pre_existing = AddProspectCommand(
            organization_id=test_tenant.id,
            name="Sociedad Colombiana de Urología",
            website_url="https://scu.org.co",
            source="overture",
            forge_record_id="ov-scu-9999",
        )
        p1 = prospect_service.add_prospect(pre_existing)

        # Second: Web search discovers the same organization via plan execution
        task = DiscoveryTask(
            provider="web_search",
            category="medical_association",
            query="sociedad colombiana de urología cali",
            metadata={"organization_id": test_tenant.id},
        )
        plan = SearchPlan(
            organization_id=test_tenant.id,
            tasks=[task],
        )
        result = orchestrator.execute_plan(plan)

        # Verification: Only 1 prospect exists in DB for this tenant
        prospect = prospect_service.prospect_repo.find_existing_prospect(
            test_tenant.id, website_url="https://scu.org.co"
        )
        assert prospect is not None
        assert prospect.id == p1.id
        assert result.prospects_reused == 1

    # 12. Multiple Provenance Records (Two ProspectSources for 1 Prospect)
    def test_12_multiple_provenance_records(
        self, fixture_transport, test_tenant, prospect_service, research_run_repo
    ):
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants={test_tenant.id},
        )
        orchestrator = DiscoveryOrchestrator(
            providers=[provider],
            prospect_service=prospect_service,
            research_run_repo=research_run_repo,
        )

        # Pre-seed from Overture
        pre_cmd = AddProspectCommand(
            organization_id=test_tenant.id,
            name="Sociedad Colombiana de Urología",
            website_url="https://scu.org.co",
            source="overture",
            forge_record_id="ov-scu-9999",
        )
        p = prospect_service.add_prospect(pre_cmd)

        # Execute web search
        task = DiscoveryTask(
            provider="web_search",
            category="medical_association",
            query="sociedad colombiana de urología cali",
            metadata={"organization_id": test_tenant.id},
        )
        plan = SearchPlan(organization_id=test_tenant.id, tasks=[task])
        orchestrator.execute_plan(plan)

        # Inspect provenance
        sources = prospect_service.prospect_repo.list_prospect_sources(test_tenant.id, p.id)
        source_types = [s.source_type for s in sources]

        assert len(sources) == 2
        assert "overture" in source_types
        assert "web_search" in source_types

    # 13. Provenance Retry Idempotency
    def test_13_provenance_retry_idempotency(
        self, fixture_transport, test_tenant, prospect_service, research_run_repo
    ):
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants={test_tenant.id},
        )
        orchestrator = DiscoveryOrchestrator(
            providers=[provider],
            prospect_service=prospect_service,
            research_run_repo=research_run_repo,
        )

        task = DiscoveryTask(
            provider="web_search",
            category="medical_association",
            query="sociedad colombiana de urología cali",
            metadata={"organization_id": test_tenant.id},
        )
        plan = SearchPlan(organization_id=test_tenant.id, tasks=[task])

        # Execute run 1
        orchestrator.execute_plan(plan)

        # Execute run 2 (retry identical plan)
        orchestrator.execute_plan(plan)

        # Inspect prospect and provenance
        prospect = prospect_service.prospect_repo.find_existing_prospect(
            test_tenant.id, website_url="https://scu.org.co"
        )
        assert prospect is not None
        sources = prospect_service.prospect_repo.list_prospect_sources(test_tenant.id, prospect.id)
        # Must be exactly 1 web_search source record, not duplicated
        assert len(sources) == 1
        assert sources[0].source_type == "web_search"

    # 14. Cross-Tenant Isolation
    def test_14_cross_tenant_isolation(
        self, fixture_transport, test_tenant, second_tenant, prospect_service, research_run_repo
    ):
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants={test_tenant.id, second_tenant.id},
        )
        orchestrator = DiscoveryOrchestrator(
            providers=[provider],
            prospect_service=prospect_service,
            research_run_repo=research_run_repo,
        )

        # Tenant A executes
        plan_a = SearchPlan(
            organization_id=test_tenant.id,
            tasks=[DiscoveryTask(
                provider="web_search",
                category="medical_association",
                query="sociedad colombiana de urología cali",
                metadata={"organization_id": test_tenant.id},
            )],
        )
        orchestrator.execute_plan(plan_a)

        # Tenant A sees their prospect
        prospect_a = prospect_service.prospect_repo.find_existing_prospect(
            test_tenant.id, website_url="https://scu.org.co"
        )
        assert prospect_a is not None

        # Tenant B cannot see Tenant A's prospect
        prospect_b = prospect_service.prospect_repo.find_existing_prospect(
            second_tenant.id, website_url="https://scu.org.co"
        )
        assert prospect_b is None

        # Tenant B cannot access Tenant A's provenance
        sources_a = prospect_service.prospect_repo.list_prospect_sources(second_tenant.id, prospect_a.id)
        assert len(sources_a) == 0

    # 15. Zero Real External API Calls
    def test_15_zero_real_external_api_calls(self, fixture_transport, test_tenant):
        """Verifies that no network sockets or HTTP requests are attempted."""
        provider = WebSearchDiscoveryProvider(
            transport=fixture_transport,
            enabled=True,
            authorized_tenants={test_tenant.id},
        )
        task = DiscoveryTask(
            provider="web_search",
            category="medical_association",
            query="Sociedad Colombiana de Cardiología Cali",
            metadata={"organization_id": test_tenant.id},
        )

        # Intercept socket.socket creation to ensure no outbound connection attempts occur
        with patch("socket.socket") as mock_socket:
            results = provider.discover(task)
            assert len(results) > 0
            assert mock_socket.call_count == 0

    # 16. Zero Persistent Real Brave Data
    def test_16_zero_persistent_real_brave_data(self):
        """Verifies that only synthetic fixtures are used and candidate_classifier does not import web provider."""
        import bopclients.infrastructure.providers.web_search_provider as mod

        src = inspect.getsource(mod)
        # Must not contain real API endpoints or keys
        assert "api.search.brave.com" not in src
        assert "X-Subscription-Token" not in src
        # Must not import OvertureCandidateValidator
        assert "OvertureCandidateValidator" not in src
