"""Focused offline unit and integration tests for P30.5G.5A General-Purpose ICP & Classification Foundation.

Verifies:
1. Medical association acceptance (two-independent signals).
2. Clinic facility exclusion for medical ICP.
3. Nonmedical association without medical vocabulary.
4. Construction company acceptance.
5. Real estate agency rejection for construction profile.
6. Industrial distributor acceptance.
7. Unrelated retailer rejection for industrial distribution profile.
8. B2B software company acceptance.
9. Electronics retailer rejection for software profile.
10. Missing business activity evidence returns INSUFFICIENT_EVIDENCE.
11. Mandatory negative criteria enforcement.
12. Tenant-independent classification.
13. Backward compatibility with P30.5G.1 and P30.5G.2 reason codes.
14. ICP serialization round-trip in SQLite repository without schema migration.
"""

import pytest
import sqlite3
from typing import Dict, Any

from bopclients.domain.icp import IdealCustomerProfile, TargetMarket
from bopclients.domain.search_intent import SearchIntent
from bopclients.domain.normalizers import CategoryNormalizer
from bopclients.application.discovery.candidate_classifier import (
    CandidateClassificationRequest,
    CandidateClassificationStatus,
    ClassificationDecision,
    OrganizationCandidateClassifier,
)
from bopclients.infrastructure.repositories.icp_repository import ICPRepository
from bopclients.infrastructure.db.schema import BOPCLIENTS_DDL_TABLES, BOPCLIENTS_DDL_INDEXES


class MockDb:
    """In-memory SQLite database wrapper implementing fetch_dicts, execute, and commit."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self._setup()

    def _setup(self):
        cur = self.conn.cursor()
        for ddl in BOPCLIENTS_DDL_TABLES:
            cur.execute(ddl)
        for ddl in BOPCLIENTS_DDL_INDEXES:
            cur.execute(ddl)
        self.conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.conn.cursor().execute(sql, params)

    def commit(self) -> None:
        self.conn.commit()

    def fetch_dicts(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


class TestP30_5G5A_GeneralPurposeICPAndClassifier:
    """Test suite for general-purpose ICP semantics and sector-aware candidate classification."""

    @pytest.fixture
    def classifier(self) -> OrganizationCandidateClassifier:
        return OrganizationCandidateClassifier()

    @pytest.fixture
    def memory_db(self) -> MockDb:
        db = MockDb()
        # Seed test tenants
        db.execute(
            """
            INSERT INTO organizations (id, bop_organization_id, name, slug, created_at, updated_at)
            VALUES ('org-bop', 'bop-001', 'Bop Agencia', 'bop-agencia', '2026-01-01', '2026-01-01')
            """
        )
        db.execute(
            """
            INSERT INTO organizations (id, bop_organization_id, name, slug, created_at, updated_at)
            VALUES ('org-industrial', 'ind-001', 'The Industrial Depot', 'industrial-depot', '2026-01-01', '2026-01-01')
            """
        )
        db.execute(
            """
            INSERT INTO organizations (id, bop_organization_id, name, slug, created_at, updated_at)
            VALUES ('org-tech', 'tech-001', 'SaaS Corp', 'saas-corp', '2026-01-01', '2026-01-01')
            """
        )
        db.commit()
        return db

    # 1. Medical association acceptance
    def test_01_medical_association_acceptance(self, classifier):
        req = CandidateClassificationRequest(
            name="Asociación Colombiana de Neurología",
            target_intent="medical_association",
            canonical_category_hints={"association"},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE
        assert decision.is_valid is True
        assert decision.reason is None

    # 2. Clinic exclusion for medical ICP
    def test_02_clinic_exclusion_for_medical_icp(self, classifier):
        req = CandidateClassificationRequest(
            name="Clínica Pediátrica del Valle",
            target_intent="medical_association",
            canonical_category_hints={"association"},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.REJECTED
        assert decision.is_valid is False
        assert "EXCLUDED_FACILITY_NAME" in decision.reason

    # 3. Nonmedical association without medical vocabulary
    def test_03_nonmedical_association_without_medical_vocabulary(self, classifier):
        req = CandidateClassificationRequest(
            name="Asociación Nacional de Exportadores",
            target_intent="association",
            target_organization_types=["association"],
            canonical_category_hints={"association"},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE
        assert decision.is_valid is True
        assert decision.reason is None

    # 4. Construction company acceptance
    def test_04_construction_company_acceptance(self, classifier):
        req = CandidateClassificationRequest(
            name="Constructora Bolívar S.A.",
            target_intent="construction",
            raw_metadata={"snippet": "Empresa constructora de edificaciones y obras civiles en Colombia."},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE
        assert decision.is_valid is True
        assert decision.details.get("sector") == "construction"

    # 5. Real estate agency rejection for construction ICP
    def test_05_real_estate_agency_rejection(self, classifier):
        req = CandidateClassificationRequest(
            name="Inmobiliaria y Arrendamientos del Valle",
            target_intent="construction",
            raw_metadata={"snippet": "Agencia inmobiliaria dedicada a bienes raíces, venta y alquiler de propiedades."},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.REJECTED
        assert decision.is_valid is False
        assert "EXCLUDED_REAL_ESTATE_AGENCY" in decision.reason

    # 6. Industrial distributor acceptance
    def test_06_industrial_distributor_acceptance(self, classifier):
        req = CandidateClassificationRequest(
            name="Distribuidora Industrial de Abrasivos S.A.S.",
            target_intent="industrial_distributor",
            raw_metadata={"snippet": "Distribución mayorista de herramientas industriales, abrasivos y equipos de seguridad."},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE
        assert decision.is_valid is True
        assert decision.details.get("sector") == "industrial_distribution"

    # 7. Unrelated retailer rejection for industrial distributor ICP
    def test_07_unrelated_retailer_rejection(self, classifier):
        req = CandidateClassificationRequest(
            name="Supermercados La Gran Vía",
            target_intent="industrial_distributor",
            raw_metadata={"snippet": "Supermercado minorista con ofertas en alimentos y productos del hogar."},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.REJECTED
        assert decision.is_valid is False
        assert "EXCLUDED_RETAIL_STORE" in decision.reason

    # 8. B2B software company acceptance
    def test_08_b2b_software_company_acceptance(self, classifier):
        req = CandidateClassificationRequest(
            name="DataForge Enterprise Cloud Solutions",
            target_intent="b2b_software",
            raw_metadata={"snippet": "Plataforma SaaS para gestión empresarial y desarrollo de software B2B."},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE
        assert decision.is_valid is True
        assert decision.details.get("sector") == "b2b_software"

    # 9. Electronics retailer rejection for B2B software ICP
    def test_09_electronics_retailer_rejection(self, classifier):
        req = CandidateClassificationRequest(
            name="Tienda de Computadores y Celulares El Parque",
            target_intent="b2b_software",
            raw_metadata={"snippet": "Venta de celulares, repuestos y reparación de computadores para el público general."},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.REJECTED
        assert decision.is_valid is False
        assert "EXCLUDED_ELECTRONICS_RETAILER" in decision.reason

    # 10. Missing business activity evidence returns INSUFFICIENT_EVIDENCE
    def test_10_missing_business_activity_evidence(self, classifier):
        req = CandidateClassificationRequest(
            name="Empresa Los Pinos S.A.",
            target_intent="construction",
            raw_metadata={"snippet": "Servicios comerciales generales."},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.INSUFFICIENT_EVIDENCE
        assert decision.is_valid is False
        assert "INSUFFICIENT_EVIDENCE" in decision.reason

    # 11. Mandatory negative criteria enforcement
    def test_11_mandatory_negative_criteria(self, classifier):
        req = CandidateClassificationRequest(
            name="Florida Builders Group",
            target_intent="construction",
            negative_keywords=["individual contractor", "residential"],
            raw_metadata={"snippet": "Residential builder and contractor."},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.REJECTED
        assert decision.is_valid is False
        assert "EXCLUDED_BY_NEGATIVE_KEYWORD" in decision.reason

    # 12. Tenant-independent classification
    def test_12_tenant_independent_classification(self, classifier):
        req_tenant_a = CandidateClassificationRequest(
            name="Constructora Andina",
            target_intent="construction",
            raw_metadata={"snippet": "Constructora de proyectos de infraestructura."},
        )
        req_tenant_b = CandidateClassificationRequest(
            name="Inmobiliaria Andina",
            target_intent="construction",
            raw_metadata={"snippet": "Bienes raíces y gestión de arrendamientos."},
        )
        dec_a = classifier.classify(req_tenant_a)
        dec_b = classifier.classify(req_tenant_b)

        assert dec_a.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE
        assert dec_b.status == CandidateClassificationStatus.REJECTED

    # 13. Backward compatibility with P30.5G.1 and P30.5G.2
    def test_13_backward_compatibility_p30_5g1_and_5g2(self, classifier):
        # Unverified medical specialization rejected
        req_unverified = CandidateClassificationRequest(
            name="Asociación Colombiana de Bananeros",
            target_intent="medical_association",
        )
        dec_unverified = classifier.classify(req_unverified)
        assert dec_unverified.status == CandidateClassificationStatus.REJECTED
        assert "UNVERIFIED_MEDICAL_SPECIALIZATION" in dec_unverified.reason

        # Not an association rejected
        req_not_assoc = CandidateClassificationRequest(
            name="Cardiología Integral S.A.",
            target_intent="medical_association",
        )
        dec_not_assoc = classifier.classify(req_not_assoc)
        assert dec_not_assoc.status == CandidateClassificationStatus.REJECTED
        assert "NOT_AN_ASSOCIATION" in dec_not_assoc.reason

    # 14. ICP serialization round-trip in SQLite repository without schema migration
    def test_14_icp_serialization_round_trip(self, memory_db):
        repo = ICPRepository(memory_db)
        tm = TargetMarket(country="US", region="FL", city="Miami", radius_miles=25.0)

        icp = IdealCustomerProfile(
            organization_id="org-bop",
            name="General Construction ICP",
            description="Targeting commercial construction companies in Florida",
            industries=["construction"],
            company_sizes=["11-50", "51-200"],
            target_organization_types=["company"],
            target_industries=["construction"],
            target_business_activities=["construction", "general_contracting"],
            target_offerings=["commercial_construction"],
            target_specializations=["commercial"],
            required_attributes=["licensed_contractor"],
            excluded_attributes=["real_estate_brokerage"],
            excluded_organization_types=["real_estate", "individual_contractor"],
            tenant_offerings=["digital_marketing_services"],
            target_markets=[tm],
        )

        saved = repo.save("org-bop", icp)
        assert saved.id == icp.id

        loaded = repo.get_by_id("org-bop", icp.id)
        assert loaded is not None
        assert loaded.id == icp.id
        assert loaded.organization_id == "org-bop"
        assert loaded.name == "General Construction ICP"
        assert loaded.description == "Targeting commercial construction companies in Florida"
        assert loaded.industries == ["construction"]
        assert loaded.target_organization_types == ["company"]
        assert loaded.target_industries == ["construction"]
        assert loaded.target_business_activities == ["construction", "general_contracting"]
        assert loaded.target_offerings == ["commercial_construction"]
        assert loaded.target_specializations == ["commercial"]
        assert loaded.required_attributes == ["licensed_contractor"]
        assert loaded.excluded_attributes == ["real_estate_brokerage"]
        assert loaded.excluded_organization_types == ["real_estate", "individual_contractor"]
        assert loaded.tenant_offerings == ["digital_marketing_services"]
        assert len(loaded.target_markets) == 1
        assert loaded.target_markets[0].city == "Miami"
        assert loaded.target_markets[0].region == "FL"

        # Verify effective derivation accessors
        assert loaded.get_effective_organization_types() == ["company"]
        assert loaded.get_effective_industries() == ["construction"]
        assert loaded.get_effective_business_activities() == ["construction", "general_contracting"]
        assert loaded.get_effective_target_offerings() == ["commercial_construction"]
        assert loaded.get_effective_tenant_offerings() == ["digital_marketing_services"]
        assert loaded.get_effective_excluded_organization_types() == ["real_estate", "individual_contractor"]
