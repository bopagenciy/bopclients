"""Unit tests for FORGE Gateway Adapters in BopClients."""

from unittest.mock import MagicMock
from bopclients.application.interfaces.forge_gateways import DiscoveryQuery, EnrichmentTask
from bopclients.infrastructure.gateways.forge_gateway import ForgeDiscoveryGatewayAdapter, ForgeEnrichmentGatewayAdapter


class TestForgeDiscoveryGatewayAdapter:
    def test_discover_businesses_maps_raw_overture_records(self):
        mock_discovery = MagicMock()
        mock_discovery.search.return_value = [
            {
                "overture_id": "ov-100",
                "name": "Tampa Smile Clinic",
                "address": "100 Main St",
                "city": "Tampa",
                "state": "FL",
                "zip": "33602",
                "lat": 27.95,
                "lon": -82.45,
                "phone": "813-555-0100",
                "website_url": "https://tampasmile.com",
                "category": "dentist",
                "forge_industry": "healthcare",
            }
        ]

        gateway = ForgeDiscoveryGatewayAdapter(overture_discovery=mock_discovery)
        query = DiscoveryQuery(zip_code="33602", industry="dentist", limit=10)

        results = gateway.discover_businesses(query)

        assert len(results) == 1
        b = results[0]
        assert b.overture_id == "ov-100"
        assert b.name == "Tampa Smile Clinic"
        assert b.website_url == "https://tampasmile.com"
        assert b.forge_industry == "healthcare"
        mock_discovery.search.assert_called_once_with(
            zip_code="33602",
            city=None,
            state=None,
            latitude=None,
            longitude=None,
            radius_miles=10.0,
            industry="dentist",
            limit=10,
        )


class TestForgeEnrichmentGatewayAdapter:
    def test_enrich_batch_invokes_db_and_pipeline(self):
        mock_db = MagicMock()
        mock_db.fetch_dicts.return_value = [
            {"id": "b-1", "name": "Tampa Smile Clinic", "email": "info@tampasmile.com", "tech_stack": '["wordpress"]'}
        ]

        gateway = ForgeEnrichmentGatewayAdapter(db_pool=mock_db)
        task = EnrichmentTask(
            business_records=[{"name": "Tampa Smile Clinic", "website_url": "https://tampasmile.com"}],
            mode="email",
            workers=3,
        )

        with MagicMock() as mock_pipeline:
            # Test upsert_business call
            gateway.enrich_batch(task)
            mock_db.upsert_business.assert_called_once_with(task.business_records[0])
