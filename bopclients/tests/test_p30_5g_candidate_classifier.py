"""Offline tests for P30.5G.2 Source-Neutral Organization Candidate Classifier.

Verifies that OrganizationCandidateClassifier:
1. Operates as a completely source-neutral component without provider or network dependencies.
2. Accepts legitimate medical associations, scientific societies, and medical specialty organizations.
3. Recognizes broad Spanish medical specialty disciplines, practitioner forms, and adjectives.
4. Correctly rejects non-medical associations (fails sector specialization check).
5. Strictly rejects medical facilities (clinics, hospitals, medical offices, pharmacies) by name or category.
6. Blocks contradictory entity evidence (fails closed).
7. Handles edge cases and insufficient evidence gracefully.
8. Has zero imports from Overture, DuckDB, AWS S3, or forge databases.
9. Makes zero network calls.
"""

import inspect
import pytest
from typing import List

from bopclients.application.discovery.candidate_classifier import (
    CandidateClassificationRequest,
    CandidateClassificationStatus,
    ClassificationDecision,
    IOrganizationCandidateClassifier,
    OrganizationCandidateClassifier,
)
from bopclients.infrastructure.providers.overture_provider import (
    OvertureCandidateValidator,
)
from bopclients.application.interfaces.forge_gateways import DiscoveredBusiness
from bopclients.application.search_dto import DiscoveryTask


@pytest.fixture
def classifier() -> OrganizationCandidateClassifier:
    return OrganizationCandidateClassifier()


@pytest.fixture
def overture_validator() -> OvertureCandidateValidator:
    return OvertureCandidateValidator()


class TestP30_5G2_CandidateClassifier:
    """Offline test suite for source-neutral organization candidate classification."""

    # 1. Genuine Medical Association
    def test_01_genuine_medical_association_accepted(self, classifier):
        req = CandidateClassificationRequest(
            name="Asociación Colombiana de Medicina Interna",
            target_intent="medical_association",
            canonical_category_hints={"association"},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE
        assert decision.is_valid is True
        assert decision.reason is None

    # 2. Scientific Society
    def test_02_scientific_society_accepted(self, classifier):
        req = CandidateClassificationRequest(
            name="Sociedad Colombiana de Pediatría",
            target_intent="scientific_society",
            canonical_category_hints={"association"},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE
        assert decision.is_valid is True
        assert decision.reason is None

    # 3. Specialty Professional Association
    def test_03_specialty_professional_association_accepted(self, classifier):
        req = CandidateClassificationRequest(
            name="Colegio Médico de Cundinamarca",
            target_intent="medical_association",
            canonical_category_hints={"professional_association"},
        )
        decision = classifier.classify(req)
        assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE
        assert decision.is_valid is True

    # 4. Specialty: Cardiology
    def test_04_specialty_cardiology_accepted(self, classifier):
        names = [
            "Sociedad Colombiana de Cardiología",
            "Asociación de Cardiólogos del Valle",
            "Sociedad de Cardiología y Cirugía Cardiovascular",
        ]
        for name in names:
            req = CandidateClassificationRequest(
                name=name,
                target_intent="medical_association",
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE, f"Failed for {name}"
            assert decision.is_valid is True

    # 5. Specialty: Urology
    def test_05_specialty_urology_accepted(self, classifier):
        names = [
            "Sociedad Colombiana de Urología",
            "Asociación de Urólogos de Colombia",
            "Sociedad Colombiana de Urologia",  # unaccented
        ]
        for name in names:
            req = CandidateClassificationRequest(
                name=name,
                target_intent="medical_association",
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE, f"Failed for {name}"
            assert decision.is_valid is True

    # 6. Specialty: Endocrinology
    def test_06_specialty_endocrinology_accepted(self, classifier):
        names = [
            "Asociación Colombiana de Endocrinología",
            "Sociedad de Endocrinologia, Diabetes y Metabolismo",
            "Asociación de Endocrinólogos de Colombia",
        ]
        for name in names:
            req = CandidateClassificationRequest(
                name=name,
                target_intent="medical_association",
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE, f"Failed for {name}"
            assert decision.is_valid is True

    # 7. Specialty: Obstetrics & Gynecology
    def test_07_specialty_obstetrics_gynecology_accepted(self, classifier):
        names = [
            "Federación Colombiana de Obstetricia y Ginecología",
            "Sociedad de Gineco-Obstetricia del Valle",
            "Asociación Colombiana de Ginecólogos y Obstetras",
            "Sociedad Colombiana de Medicina Materno-Fetal",
        ]
        for name in names:
            req = CandidateClassificationRequest(
                name=name,
                target_intent="medical_association",
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE, f"Failed for {name}"
            assert decision.is_valid is True

    # 8. Specialty: Pediatrics
    def test_08_specialty_pediatrics_accepted(self, classifier):
        names = [
            "Sociedad Colombiana de Pediatría",
            "Asociación Colombiana de Pediatría y Neonatología",
            "Asociación de Pediatras del Valle del Cauca",
            "Sociedad Colombiana de Perinatología",
        ]
        for name in names:
            req = CandidateClassificationRequest(
                name=name,
                target_intent="medical_association",
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE, f"Failed for {name}"
            assert decision.is_valid is True

    # 9. Other Specialties across Medical Spectrum
    def test_09_other_specialties_accepted(self, classifier):
        specialty_names = [
            "Sociedad Colombiana de Anestesiología y Reanimación",
            "Asociación Colombiana de Dermatología y Cirugía Dermatológica",
            "Asociación Colombiana de Neurología",
            "Sociedad Colombiana de Radiología",
            "Asociación Colombiana de Psiquiatría",
            "Asociación Colombiana de Hematología y Oncología",
            "Asociación Colombiana de Reumatología",
            "Asociación Colombiana de Nefrología e Hipertensión Arterial",
            "Sociedad Colombiana de Cirugía Ortopédica y Traumatología",
            "Sociedad Colombiana de Oftalmología",
            "Asociación Colombiana de Gastroenterología",
            "Asociación Colombiana de Infectología",
            "Asociación Colombiana de Neumología y Cirugía de Tórax",
            "Sociedad Colombiana de Otorrinolaringología",
            "Sociedad Colombiana de Patología",
            "Asociación Colombiana de Genética Humana",
        ]
        for name in specialty_names:
            req = CandidateClassificationRequest(
                name=name,
                target_intent="medical_association",
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.ACCEPTED_CANDIDATE, f"Failed for {name}: {decision.reason}"
            assert decision.is_valid is True

    # 10. Non-Medical Association Rejected (Fails Pillar 2: Sector Specialization)
    def test_10_non_medical_association_rejected(self, classifier):
        non_medical = [
            "Asociación Colombiana de Ingenieros",
            "Sociedad de Abogados de Cali",
            "Federación Nacional de Comerciantes",
            "Colegio de Contadores Públicos",
            "Asociación de Arquitectos del Valle",
        ]
        for name in non_medical:
            req = CandidateClassificationRequest(
                name=name,
                target_intent="medical_association",
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.REJECTED, f"Expected rejection for {name}"
            assert decision.is_valid is False
            assert "UNVERIFIED_MEDICAL_SPECIALIZATION" in decision.reason

    # 11. Facility Prefix: Clinic Rejected
    def test_11_clinic_facility_rejected(self, classifier):
        clinics = [
            "Clínica de la Asociación Médica",
            "Clinica de Cardiología del Valle",
            "Clínica Pediátrica Santa Clara",
        ]
        for name in clinics:
            req = CandidateClassificationRequest(
                name=name,
                target_intent="medical_association",
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.REJECTED
            assert decision.is_valid is False
            assert "EXCLUDED_FACILITY_NAME" in decision.reason

    # 12. Facility Prefix: Hospital Rejected
    def test_12_hospital_facility_rejected(self, classifier):
        hospitals = [
            "Hospital Universitario del Valle",
            "Hospital San Juan de Dios",
            "Hospital de la Sociedad Médica",
        ]
        for name in hospitals:
            req = CandidateClassificationRequest(
                name=name,
                target_intent="medical_association",
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.REJECTED
            assert decision.is_valid is False
            assert "EXCLUDED_FACILITY_NAME" in decision.reason

    # 13. Facility Prefix: Medical Office / Center Rejected
    def test_13_medical_office_rejected(self, classifier):
        offices = [
            "Consultorio Médico Dra. Gómez",
            "Centro Médico de Especialistas de Cali",
            "Policlínica del Sur",
            "Sanatorio Quirúrgico",
        ]
        for name in offices:
            req = CandidateClassificationRequest(
                name=name,
                target_intent="medical_association",
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.REJECTED
            assert decision.is_valid is False
            assert "EXCLUDED_FACILITY_NAME" in decision.reason

    # 14. Facility Prefix: Pharmacy Rejected
    def test_14_pharmacy_facility_rejected(self, classifier):
        pharmacies = [
            "Farmacia Médica San Jorge",
            "Droguería Médica del Valle",
        ]
        for name in pharmacies:
            req = CandidateClassificationRequest(
                name=name,
                target_intent="medical_association",
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.REJECTED
            assert decision.is_valid is False
            assert "EXCLUDED_FACILITY_NAME" in decision.reason

    # 15. Canonical Facility Category Hint Rejected
    def test_15_canonical_facility_category_hint_rejected(self, classifier):
        facility_hints = [
            {"clinic"},
            {"hospital"},
            {"medical_office"},
            {"pharmacy"},
            {"doctor"},
            {"dentist"},
        ]
        for hints in facility_hints:
            req = CandidateClassificationRequest(
                name="Sociedad Colombiana de Cardiología",  # Genuine name, but category claims facility
                target_intent="medical_association",
                canonical_facility_hints=hints,
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.REJECTED
            assert decision.is_valid is False
            assert "EXCLUDED_FACILITY_CATEGORY" in decision.reason

    # 16. Contradictory Evidence Failing Closed
    def test_16_contradictory_evidence_fails_closed(self, classifier):
        # 16A. Contradictory metadata flag
        req_flag = CandidateClassificationRequest(
            name="Sociedad Colombiana de Cardiología",
            target_intent="medical_association",
            raw_metadata={"contradictory": True},
        )
        dec_flag = classifier.classify(req_flag)
        assert dec_flag.status == CandidateClassificationStatus.REJECTED
        assert dec_flag.is_valid is False
        assert "CONTRADICTORY_ENTITY_EVIDENCE" in dec_flag.reason

        # 16B. Alternate categories contain facility
        req_alt = CandidateClassificationRequest(
            name="Sociedad Colombiana de Urología",
            target_intent="medical_association",
            raw_metadata={"alternate_categories": ["clinic", "health_services"]},
        )
        dec_alt = classifier.classify(req_alt)
        assert dec_alt.status == CandidateClassificationStatus.REJECTED
        assert dec_alt.is_valid is False
        assert "CONTRADICTORY_ENTITY_EVIDENCE" in dec_alt.reason

        # 16C. Dual-nature name
        req_dual = CandidateClassificationRequest(
            name="Sociedad y Clínica Oftalmológica de Cali",
            target_intent="medical_association",
        )
        dec_dual = classifier.classify(req_dual)
        assert dec_dual.status == CandidateClassificationStatus.REJECTED
        assert dec_dual.is_valid is False
        assert "CONTRADICTORY_ENTITY_EVIDENCE" in dec_dual.reason

    # 17. Insufficient Evidence Handling
    def test_17_insufficient_evidence(self, classifier):
        invalid_names = ["", "   ", None]
        for name in invalid_names:
            req = CandidateClassificationRequest(
                name=name,
                target_intent="medical_association",
            )
            decision = classifier.classify(req)
            assert decision.status == CandidateClassificationStatus.INSUFFICIENT_EVIDENCE
            assert decision.is_valid is False
            assert decision.reason == "MISSING_ORGANIZATION_NAME"

    # 18. Source Neutrality & Zero External Dependencies
    def test_18_source_neutrality_and_no_external_imports(self):
        """Verifies candidate_classifier.py has NO imports of overture, duckdb, s3, or forge db."""
        import bopclients.application.discovery.candidate_classifier as mod

        source = inspect.getsource(mod)
        forbidden_terms = [
            "overture",
            "duckdb",
            "boto3",
            "s3",
            "forge.db",
            "DiscoveredBusiness",
            "requests",
            "httpx",
            "urllib3",
        ]
        for term in forbidden_terms:
            assert term.lower() not in source.lower(), (
                f"Forbidden dependency or term '{term}' found in candidate_classifier.py"
            )

        # Confirm interface contract conformance
        assert issubclass(OrganizationCandidateClassifier, IOrganizationCandidateClassifier)

    # 19. Adapter Delegation Verification (OvertureCandidateValidator delegates to classifier)
    def test_19_overture_validator_delegates_to_classifier(self, overture_validator):
        """Verifies OvertureCandidateValidator correctly delegates semantic classification to OrganizationCandidateClassifier."""
        task = DiscoveryTask(
            id="task-test-01",
            provider="overture",
            category="medical_association",
            latitude=3.4516,
            longitude=-76.5320,
            radius_miles=25.0,
        )

        biz_valid = DiscoveredBusiness(
            overture_id="ov-valid-01",
            name="Sociedad Colombiana de Cardiología",
            category="non_governmental_association",
            latitude=3.4516,
            longitude=-76.5320,
        )
        is_val, reason = overture_validator.validate_candidate(biz_valid, task)
        assert is_val is True
        assert reason is None

        biz_facility = DiscoveredBusiness(
            overture_id="ov-fac-01",
            name="Clínica de Cardiología",
            category="clinic",
            latitude=3.4516,
            longitude=-76.5320,
        )
        is_val, reason = overture_validator.validate_candidate(biz_facility, task)
        assert is_val is False
        assert "EXCLUDED_FACILITY" in reason
