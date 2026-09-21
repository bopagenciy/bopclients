"""Offline tests for P30.5G.1 Medical Specialty Classification.

Verifies that OvertureCandidateValidator:
1. Correctly accepts legitimate medical specialty discipline nouns and practitioner forms.
2. Supports both accented and unaccented Spanish variants.
3. Enforces the two-independent-signals rule (Organization-Type + Medical Specialty).
4. Strictly excludes facilities (clinics, hospitals, doctor offices, pharmacies).
5. Blocks contradictory source evidence.
6. Passes all 13 AUDIT 1A test cases.
7. Makes zero remote calls.
"""

import pytest
from bopclients.infrastructure.providers.overture_provider import (
    OvertureCandidateValidator,
    OvertureDiscoveryProvider,
)
from bopclients.application.interfaces.forge_gateways import (
    DiscoveredBusiness,
    IForgeDiscoveryGateway,
    DiscoveryQuery,
)
from bopclients.application.search_dto import DiscoveryTask


CALI_LAT = 3.4516
CALI_LON = -76.5320
RADIUS_MILES = 25.0


class MockGateway(IForgeDiscoveryGateway):
    def __init__(self, candidates=None):
        self._candidates = candidates or []

    def discover_businesses(self, query: DiscoveryQuery):
        return list(self._candidates)


@pytest.fixture
def validator():
    return OvertureCandidateValidator()


@pytest.fixture
def base_task():
    return DiscoveryTask(
        id="task-med-001",
        provider="overture",
        category="medical_association",
        latitude=CALI_LAT,
        longitude=CALI_LON,
        radius_miles=RADIUS_MILES,
        negative_keywords=["clinic", "hospital", "medical_office", "pharmacy"],
    )


class TestP30_5G_MedicalSpecialtyClassification:
    """Offline test suite for medical specialty classification in OvertureCandidateValidator."""

    # 1. Audit 1A 13 Core Cases
    def test_01_audit_1a_legitimate_specialties_accepted(self, validator, base_task):
        """Audit 1A: Legitimate specialty medical societies must be accepted."""
        cases = [
            ("ov-01", "Sociedad Colombiana de Cardiología", "non_governmental_association"),
            ("ov-02", "Sociedad Colombiana de Urología", "non_governmental_association"),
            ("ov-03", "Asociación Colombiana de Endocrinología", "community_services_non_profits"),
            ("ov-04", "Federación Colombiana de Obstetricia y Ginecología", "non_governmental_association"),
            ("ov-05", "Sociedad Colombiana de Anestesiología y Reanimación", "non_governmental_association"),
            ("ov-06", "Asociación Colombiana de Reumatología", "community_services_non_profits"),
            ("ov-07", "Sociedad Colombiana de Dermatología", "non_governmental_association"),
            ("ov-08", "Sociedad Colombiana de Pediatría", "non_governmental_association"),
            ("ov-09", "Colegio Médico del Valle", "non_governmental_association"),
            ("ov-10", "Sociedad de Cirugía de Cali", "non_governmental_association"),
        ]

        for ov_id, name, cat in cases:
            biz = DiscoveredBusiness(
                overture_id=ov_id,
                name=name,
                category=cat,
                latitude=CALI_LAT,
                longitude=CALI_LON,
            )
            valid, reason = validator.validate_candidate(biz, base_task)
            assert valid is True, f"Expected '{name}' to be accepted, but was rejected: {reason}"

    def test_02_audit_1a_facilities_and_providers_rejected(self, validator, base_task):
        """Audit 1A: Medical facilities, clinics, and doctor offices must be rejected even with specialty names."""
        cases = [
            ("ov-fac-01", "Clínica de Cardiología del Valle", "clinic"),
            ("ov-fac-02", "Centro Radiológico de Cali", "medical_office"),
            ("ov-fac-03", "Urología Láser Avanzada S.A.S.", "doctor"),
        ]

        for ov_id, name, cat in cases:
            biz = DiscoveredBusiness(
                overture_id=ov_id,
                name=name,
                category=cat,
                latitude=CALI_LAT,
                longitude=CALI_LON,
            )
            valid, reason = validator.validate_candidate(biz, base_task)
            assert valid is False, f"Expected facility '{name}' to be rejected, but was accepted"
            assert "EXCLUDED_FACILITY_" in str(reason) or "NOT_AN_ASSOCIATION" in str(reason)

    # 2. Specialty Discipline Nouns Coverage
    def test_03_all_mandated_discipline_nouns_accepted(self, validator, base_task):
        """Verify all mandated specialties in Spanish discipline noun form (-logía, -ia, etc.)."""
        disciplines = [
            "Ginecología", "Obstetricia", "Medicina Maternofetal", "Perinatología",
            "Endocrinología", "Pediatría", "Neonatología", "Urología", "Cardiología",
            "Psiquiatría", "Radiología", "Neurología", "Dermatología", "Oncología",
            "Anestesiología", "Oftalmología", "Cirugía", "Medicina Interna",
            "Reumatología", "Neumología", "Gastroenterología", "Hematología",
            "Infectología", "Ortopedia", "Traumatología", "Otorrinolaringología",
            "Nefrología", "Genética Médica", "Epidemiología", "Inmunología",
            "Patología", "Geriatría", "Alergología",
        ]

        for spec in disciplines:
            biz = DiscoveredBusiness(
                overture_id=f"ov-{spec.lower()}",
                name=f"Sociedad Colombiana de {spec}",
                category="non_governmental_association",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            )
            valid, reason = validator.validate_candidate(biz, base_task)
            assert valid is True, f"Specialty discipline '{spec}' rejected: {reason}"

    # 3. Practitioner Plural Forms Coverage
    def test_04_practitioner_plural_forms_accepted(self, validator, base_task):
        """Verify practitioner plurals (-logos, -logas, -iatras, -istas, -anos)."""
        practitioners = [
            "Cardiólogos", "Cardiólogas", "Urólogos", "Urólogas", "Endocrinólogos",
            "Ginecólogos", "Pediatras", "Neonatólogos", "Psiquiatras", "Radiólogos",
            "Neurólogos", "Dermatólogos", "Oncólogos", "Anestesiólogos",
            "Oftalmólogos", "Cirujanos", "Internistas", "Reumatólogos",
            "Neumólogos", "Gastroenterólogos", "Hematólogos", "Infectólogos",
            "Ortopedistas", "Traumatólogos", "Otorrinos", "Nefrólogos",
            "Genetistas", "Epidemiólogos", "Inmunólogos", "Patólogos",
        ]

        for pract in practitioners:
            biz = DiscoveredBusiness(
                overture_id=f"ov-{pract.lower()}",
                name=f"Colegio de {pract} del Valle",
                category="professional_association",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            )
            valid, reason = validator.validate_candidate(biz, base_task)
            assert valid is True, f"Practitioner plural '{pract}' rejected: {reason}"

    # 4. Accented and Unaccented Variants
    def test_05_unaccented_variants_accepted(self, validator, base_task):
        """Verify unaccented variants are accepted gracefully."""
        unaccented_cases = [
            "Sociedad Colombiana de Cardiologia",
            "Asociacion Colombiana de Urologia",
            "Sociedad de Ginecologia y Obstetricia",
            "Colegio de Endocrinologos",
            "Asociacion de Radiologia",
            "Sociedad Colombiana de Cirugia",
            "Colegio Medico de Cirujanos",
        ]

        for name in unaccented_cases:
            biz = DiscoveredBusiness(
                overture_id="ov-unacc",
                name=name,
                category="association_or_organization",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            )
            valid, reason = validator.validate_candidate(biz, base_task)
            assert valid is True, f"Unaccented '{name}' was rejected: {reason}"

    # 5. Two-Independent-Signals Rule: Non-Medical Association Rejected
    def test_06_nonmedical_associations_rejected(self, validator, base_task):
        """Two-Independent-Signals: Genuine associations without medical/scientific specialization must be rejected."""
        non_medical = [
            "Sociedad de Amigos del Valle",
            "Club de Leones de Cali Monarca",
            "Asociación de Ingenieros Civiles del Valle",
            "Colegio de Abogados de Cali",
            "Federación Nacional de Cafeteros",
            "Sociedad Geográfica de Colombia",
            "Asociación Tecniambientales",
        ]

        for name in non_medical:
            biz = DiscoveredBusiness(
                overture_id="ov-nonmed",
                name=name,
                category="association_or_organization",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            )
            valid, reason = validator.validate_candidate(biz, base_task)
            assert valid is False, f"Expected non-medical association '{name}' to be rejected"
            assert "UNVERIFIED_MEDICAL_SPECIALIZATION" in str(reason)

    # 6. Two-Independent-Signals Rule: Specialty Word without Association Markers Rejected
    def test_07_specialty_without_association_marker_rejected(self, validator, base_task):
        """Two-Independent-Signals: Business with specialty words but no association markers must be rejected."""
        commercial_specialties = [
            ("Cardiología Integral S.A.S.", "professional_services"),
            ("Urología Avanzada de Occidente", "professional_services"),
            ("Dermatología y Estética Cali", "professional_services"),
            ("Oncología Diagnóstica", "professional_services"),
        ]

        for name, cat in commercial_specialties:
            biz = DiscoveredBusiness(
                overture_id="ov-comm",
                name=name,
                category=cat,
                latitude=CALI_LAT,
                longitude=CALI_LON,
            )
            valid, reason = validator.validate_candidate(biz, base_task)
            assert valid is False, f"Expected commercial entity '{name}' to be rejected"
            assert "NOT_AN_ASSOCIATION" in str(reason) or "EXCLUDED_" in str(reason)

    # 7. Safe Keyword Handling: Clinical Research Society Accepted
    def test_08_clinical_research_society_not_excluded_by_negative_keywords(self, validator, base_task):
        """Clinical/hospital terms in legitimate association names must not trigger negative keyword exclusion."""
        biz = DiscoveredBusiness(
            overture_id="ov-clin-res",
            name="Sociedad de Investigación Clínica de Colombia",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )
        valid, reason = validator.validate_candidate(biz, base_task)
        assert valid is True, f"Expected clinical research society to be accepted, but was rejected: {reason}"

    # 8. Facility Prefix Override: Clínica Asociación Médica del Norte Rejected
    def test_09_facility_prefix_rejects_even_with_association_terms(self, validator, base_task):
        """Facility prefix takes precedence over association keywords."""
        biz = DiscoveredBusiness(
            overture_id="ov-fac-prefix",
            name="Clínica Asociación Médica del Norte",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
        )
        valid, reason = validator.validate_candidate(biz, base_task)
        assert valid is False, "Expected facility prefix to cause rejection"
        assert "EXCLUDED_FACILITY_NAME" in str(reason)

    # 9. Alternate Category Facility Disqualification
    def test_10_alternate_category_facility_disqualification(self, validator, base_task):
        """If primary category is association but alternate category includes a facility, reject."""
        biz = DiscoveredBusiness(
            overture_id="ov-alt-fac",
            name="Sociedad Médica San José",
            category="association_or_organization",
            latitude=CALI_LAT,
            longitude=CALI_LON,
            raw_data={
                "categories": {
                    "alternate": ["clinic"]
                }
            }
        )
        valid, reason = validator.validate_candidate(biz, base_task)
        assert valid is False, "Expected alternate facility category to cause rejection"
        assert "CONTRADICTORY_ENTITY_EVIDENCE" in str(reason)

    # 10. Provider Integration Offline Test
    def test_11_provider_discover_end_to_end_offline(self, base_task):
        """Full discover() method accepts specialty societies and excludes facilities offline."""
        candidates = [
            DiscoveredBusiness(
                overture_id="c-01",
                name="Sociedad Colombiana de Cardiología",
                category="association_or_organization",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
            DiscoveredBusiness(
                overture_id="c-02",
                name="Sociedad Colombiana de Urología",
                category="association_or_organization",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
            DiscoveredBusiness(
                overture_id="c-03",
                name="Clínica de Urología del Valle",
                category="clinic",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
            DiscoveredBusiness(
                overture_id="c-04",
                name="Club de Leones",
                category="association_or_organization",
                latitude=CALI_LAT,
                longitude=CALI_LON,
            ),
        ]
        gateway = MockGateway(candidates)
        provider = OvertureDiscoveryProvider(gateway)

        results = provider.discover(base_task)
        assert len(results) == 2
        accepted_ids = {r.overture_id for r in results}
        assert accepted_ids == {"c-01", "c-02"}
