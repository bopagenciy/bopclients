"""Tests for forge.discovery."""

import pytest

from forge.discovery.overture import (
    _CATEGORY_TO_INDUSTRY,
    _INDUSTRY_TO_CATEGORIES,
    MILES_TO_DEGREES,
    OvertureDiscoveryError,
)
from forge.discovery.zip_centroids import get_zip_centroid

# ---------------------------------------------------------------------------
# Tests: get_zip_centroid
# ---------------------------------------------------------------------------


class TestGetZipCentroid:
    def test_known_zip_tampa(self):
        result = get_zip_centroid("33602")
        assert result is not None
        assert result["city"] == "Tampa"
        assert result["state"] == "FL"
        assert abs(result["lat"] - 27.9517) < 0.01
        assert abs(result["lon"] - (-82.4588)) < 0.01

    def test_known_zip_nyc(self):
        result = get_zip_centroid("10001")
        assert result is not None
        assert result["city"] == "New York"
        assert result["state"] == "NY"

    def test_known_zip_chicago(self):
        result = get_zip_centroid("60601")
        assert result is not None
        assert result["city"] == "Chicago"
        assert result["state"] == "IL"

    def test_known_zip_la(self):
        result = get_zip_centroid("90001")
        assert result is not None
        assert result["city"] == "Los Angeles"
        assert result["state"] == "CA"

    def test_known_zip_sf(self):
        result = get_zip_centroid("94102")
        assert result is not None
        assert result["city"] == "San Francisco"
        assert result["state"] == "CA"

    def test_known_zip_houston(self):
        result = get_zip_centroid("77001")
        assert result is not None
        assert result["city"] == "Houston"
        assert result["state"] == "TX"

    def test_known_zip_phoenix(self):
        result = get_zip_centroid("85001")
        assert result is not None
        assert result["city"] == "Phoenix"
        assert result["state"] == "AZ"

    def test_known_zip_miami(self):
        result = get_zip_centroid("33101")
        assert result is not None
        assert result["city"] == "Miami"
        assert result["state"] == "FL"

    def test_known_zip_dc(self):
        result = get_zip_centroid("20001")
        assert result is not None
        assert result["city"] == "Washington"
        assert result["state"] == "DC"

    def test_known_zip_atlanta(self):
        result = get_zip_centroid("30301")
        assert result is not None
        assert result["city"] == "Atlanta"
        assert result["state"] == "GA"

    def test_unknown_zip_returns_none(self):
        result = get_zip_centroid("00000")
        assert result is None

    def test_unknown_rural_zip(self):
        result = get_zip_centroid("99999")
        assert result is None

    def test_zero_padded(self):
        # Should pad to 5 digits
        result = get_zip_centroid("10001")
        assert result is not None

    def test_numeric_input(self):
        # Accepts numeric string
        result = get_zip_centroid("33602")
        assert result is not None

    def test_result_keys(self):
        result = get_zip_centroid("33602")
        assert set(result.keys()) == {"lat", "lon", "city", "state"}


# ---------------------------------------------------------------------------
# Tests: Overture Maps category mapping
# ---------------------------------------------------------------------------


class TestCategoryMapping:
    def test_restaurant_maps_to_restaurant(self):
        assert _CATEGORY_TO_INDUSTRY["restaurant"] == "restaurant"

    def test_dentist_maps_to_healthcare(self):
        assert _CATEGORY_TO_INDUSTRY["dentist"] == "healthcare"

    def test_hair_salon_maps_to_beauty(self):
        assert _CATEGORY_TO_INDUSTRY["hair_salon"] == "beauty"

    def test_gym_maps_to_fitness(self):
        assert _CATEGORY_TO_INDUSTRY["gym"] == "fitness"

    def test_lawyer_maps_to_legal(self):
        assert _CATEGORY_TO_INDUSTRY["lawyer"] == "legal"

    def test_plumber_maps_to_home_services(self):
        assert _CATEGORY_TO_INDUSTRY["plumber"] == "home_services"

    def test_hotel_maps_to_hospitality(self):
        assert _CATEGORY_TO_INDUSTRY["hotel"] == "hospitality"

    def test_reverse_mapping_completeness(self):
        """Every FORGE industry should have at least one category."""
        all_industries = set(_CATEGORY_TO_INDUSTRY.values())
        for ind in all_industries:
            assert ind in _INDUSTRY_TO_CATEGORIES
            assert len(_INDUSTRY_TO_CATEGORIES[ind]) >= 1

    def test_category_count(self):
        """Should have a substantial number of category mappings."""
        assert len(_CATEGORY_TO_INDUSTRY) > 40


# ---------------------------------------------------------------------------
# Tests: Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_miles_to_degrees_reasonable(self):
        # At mid-latitudes, 1 mile ~ 0.0145 degrees
        assert 0.01 < MILES_TO_DEGREES < 0.02

    def test_overture_error_is_exception(self):
        with pytest.raises(OvertureDiscoveryError):
            raise OvertureDiscoveryError("test error")


# ---------------------------------------------------------------------------
# Tests: Overture release & SQL query generation
# ---------------------------------------------------------------------------


class TestOvertureHardening:
    def test_get_overture_places_path_default(self, monkeypatch):
        monkeypatch.delenv("FORGE_OVERTURE_RELEASE", raising=False)
        monkeypatch.delenv("OVERTURE_RELEASE", raising=False)
        from forge.discovery.overture import get_overture_places_path
        path = get_overture_places_path()
        assert "2026-08-19.0" in path

    def test_get_overture_places_path_env_override(self, monkeypatch):
        monkeypatch.setenv("FORGE_OVERTURE_RELEASE", "2025-12-01.0")
        from forge.discovery.overture import get_overture_places_path
        path = get_overture_places_path()
        assert "2025-12-01.0" in path

    def test_format_results_populates_website_and_website_url(self):
        from forge.discovery.overture import OvertureDiscovery
        rows = [
            ("id1", "Dental Clinic", "123 Main", "Miami", "FL", "33101", 25.7, -80.2, "555-1234", "https://dental.com", "dentist")
        ]
        cols = ["overture_id", "name", "address", "city", "state", "zip", "lat", "lon", "phone", "website_url", "category"]
        res = OvertureDiscovery._format_results(rows, cols)
        assert len(res) == 1
        assert res[0]["website_url"] == "https://dental.com"
        assert res[0]["website"] == "https://dental.com"
        assert res[0]["forge_industry"] == "healthcare"

    def test_build_overture_sql_uses_bbox(self):
        from forge.discovery.overture import OvertureDiscovery
        sql = OvertureDiscovery._build_overture_sql(
            self=None,
            min_lat=25.0,
            max_lat=26.0,
            min_lon=-80.5,
            max_lon=-79.5,
            industry="dentist",
            limit=100,
        )
        assert "bbox.xmin <=" in sql
        assert "bbox.ymax >=" in sql
        assert "website_url" in sql

    def test_detect_category_sql_legacy_schema(self):
        from forge.discovery.overture import OvertureDiscovery
        cols = {"categories", "bbox", "geometry"}
        select_expr, filter_clause = OvertureDiscovery._detect_category_sql(cols, "restaurant")
        assert "categories.primary" in select_expr
        assert "categories.primary IN" in filter_clause
        assert "taxonomy" not in select_expr

    def test_detect_category_sql_new_schema_without_categories(self):
        from forge.discovery.overture import OvertureDiscovery
        # NEW SCHEMA: taxonomy and basic_category present, but categories physically MISSING
        cols = {"taxonomy", "basic_category", "bbox", "geometry"}
        select_expr, filter_clause = OvertureDiscovery._detect_category_sql(cols, "restaurant")
        assert "taxonomy.primary" in select_expr
        assert "taxonomy.primary IN" in filter_clause
        assert "categories" not in select_expr
        assert "categories" not in filter_clause

    def test_detect_category_sql_fallback_basic_category(self):
        from forge.discovery.overture import OvertureDiscovery
        cols = {"basic_category", "bbox", "geometry"}
        select_expr, filter_clause = OvertureDiscovery._detect_category_sql(cols, "restaurant")
        assert select_expr == "basic_category AS category"
        assert "basic_category IN" in filter_clause
        assert "categories" not in filter_clause
        assert "taxonomy" not in filter_clause
