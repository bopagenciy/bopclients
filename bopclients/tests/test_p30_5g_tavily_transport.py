"""Mocked HTTP tests for P30.5G.4C Tavily Web Search Transport.

Verifies:
1. Correct HTTP request construction (endpoint, headers, payload, search_depth='basic').
2. Correct response mapping into standard web result contract.
3. Graceful handling of missing or partial fields.
4. Empty search results handling.
5. Invalid API key (HTTP 401/403) failure handling.
6. Rate limit (HTTP 429) failure handling.
7. Timeout failure handling.
8. Provider 5xx error handling.
9. No-key fail-closed safety gate.
10. Disabled-by-default safety gate.
11. Zero real external network calls (socket interception).
12. Full integration with WebSearchDiscoveryProvider and OrganizationCandidateClassifier.
13. Medical specialty candidate acceptance through Tavily transport.
14. Facility exclusion enforcement through Tavily transport.
15. Secret sanitization (__repr__ masking).
16. Zero persistent real Tavily data.
"""

import json
import socket
from unittest.mock import patch
import urllib.request
import urllib.error
import pytest

from bopclients.application.search_dto import DiscoveryTask
from bopclients.domain.exceptions import DiscoveryExecutionError, TenantAccessError
from bopclients.infrastructure.providers.tavily_transport import TavilyWebSearchTransport
from bopclients.infrastructure.providers.web_search_provider import (
    WebSearchDiscoveryProvider,
    GeographicScope,
)


# Synthetic mocked Tavily response payload
MOCK_TAVILY_CARDIOLOGY_RESPONSE = {
    "query": "Sociedad Colombiana de Cardiología Cali",
    "results": [
        {
            "title": "Sociedad Colombiana de Cardiología y Cirugía Cardiovascular | Inicio",
            "url": "https://scc.org.co",
            "content": "Asociación médica y científica de derecho privado que agrupa a los médicos cardiólogos y cirujanos cardiovasculares de Colombia con capítulo Valle del Cauca.",
            "score": 0.98,
        },
        {
            "title": "Clínica de la Asociación Médica de Cardiología",
            "url": "https://clinicaasociacioncardiologia.com",
            "content": "Centro hospitalario y clínica privada con urgencias 24 horas y hospitalización en Cali.",
            "score": 0.85,
        },
    ],
    "response_time": 0.32,
}

MOCK_TAVILY_UROLOGY_RESPONSE = {
    "query": "Sociedad Colombiana de Urología Cali",
    "results": [
        {
            "title": "Sociedad Colombiana de Urología - SCU",
            "url": "https://scu.org.co",
            "content": "Sociedad científica sin ánimo de lucro que congrega a los especialistas en urología de Colombia con sede nacional y actividades en Cali y el Valle.",
            "score": 0.95,
        },
        {
            "title": "Consultorio Urológico Especializado Dr. Gómez",
            "url": "https://consultoriourologicocali.com",
            "content": "Consulta médica particular de urología en Cali.",
            "score": 0.70,
        },
    ],
    "response_time": 0.28,
}


class TestP30_5G4C_TavilyTransport:
    """Mocked unit test suite for TavilyWebSearchTransport."""

    # 1. Correct Request Construction
    def test_01_request_construction(self):
        recorded_request = {}

        def mock_client(req: urllib.request.Request, timeout: float) -> bytes:
            recorded_request["url"] = req.full_url
            recorded_request["method"] = req.get_method()
            recorded_request["headers"] = dict(req.headers)
            recorded_request["body"] = json.loads(req.data.decode("utf-8"))
            recorded_request["timeout"] = timeout
            return json.dumps({"results": []}).encode("utf-8")

        transport = TavilyWebSearchTransport(
            api_key="tvly-mock-test-key-12345",
            enabled=True,
            include_domains=["sociedadescientificas.com"],
            exclude_domains=["spam.com"],
            http_client=mock_client,
        )

        transport.search(
            query="Sociedad Colombiana de Cardiología",
            country="CO",
            count=10,
        )

        assert recorded_request["url"] == "https://api.tavily.com/search"
        assert recorded_request["method"] == "POST"
        assert recorded_request["headers"]["Authorization"] == "Bearer tvly-mock-test-key-12345"
        assert recorded_request["headers"]["Content-type"] == "application/json"

        body = recorded_request["body"]
        assert body["query"] == "Sociedad Colombiana de Cardiología"
        assert body["search_depth"] == "basic"
        assert body["topic"] == "general"
        assert body["max_results"] == 10
        assert body["country"] == "colombia"
        assert body["include_domains"] == ["sociedadescientificas.com"]
        assert body["exclude_domains"] == ["spam.com"]
        assert body["include_answer"] is False

    # 2. Correct Response Mapping
    def test_02_response_mapping(self):
        def mock_client(req, timeout) -> bytes:
            return json.dumps(MOCK_TAVILY_CARDIOLOGY_RESPONSE).encode("utf-8")

        transport = TavilyWebSearchTransport(
            api_key="tvly-test-key",
            enabled=True,
            http_client=mock_client,
        )

        mapped = transport.search("Sociedad Colombiana de Cardiología Cali")
        results = mapped["web"]["results"]
        assert len(results) == 2

        r1 = results[0]
        assert r1["title"] == "Sociedad Colombiana de Cardiología y Cirugía Cardiovascular | Inicio"
        assert r1["url"] == "https://scc.org.co"
        assert "Asociación médica y científica" in r1["description"]
        assert r1["score"] == 0.98

    # 3. Missing or Partial Fields Handled Gracefully
    def test_03_missing_partial_fields_handled(self):
        partial_data = {
            "results": [
                {"title": "Valid Society", "url": "https://valid.org"},  # Missing content
                {"title": "", "url": "https://notitle.org", "content": "Desc"},  # Missing title
                {"title": "No URL", "content": "Desc"},  # Missing url
                "unexpected_non_dict_element",
            ]
        }

        def mock_client(req, timeout) -> bytes:
            return json.dumps(partial_data).encode("utf-8")

        transport = TavilyWebSearchTransport(
            api_key="tvly-test-key",
            enabled=True,
            http_client=mock_client,
        )

        mapped = transport.search("Query")
        results = mapped["web"]["results"]
        assert len(results) == 1
        assert results[0]["title"] == "Valid Society"
        assert results[0]["url"] == "https://valid.org"
        assert results[0]["description"] == ""

    # 4. Empty Search Results
    def test_04_empty_results_handled(self):
        def mock_client(req, timeout) -> bytes:
            return json.dumps({"query": "Nonexistent", "results": []}).encode("utf-8")

        transport = TavilyWebSearchTransport(
            api_key="tvly-test-key",
            enabled=True,
            http_client=mock_client,
        )

        mapped = transport.search("Nonexistent Organization")
        assert mapped["web"]["results"] == []

    # 5. Invalid API Key Response (HTTP 401 / 403)
    def test_05_invalid_api_key_error(self):
        def mock_client(req, timeout) -> bytes:
            raise urllib.error.HTTPError(
                url="https://api.tavily.com/search",
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=None,
            )

        transport = TavilyWebSearchTransport(
            api_key="tvly-invalid-key",
            enabled=True,
            http_client=mock_client,
        )

        with pytest.raises(DiscoveryExecutionError) as exc_info:
            transport.search("Query")
        assert "authentication failed" in str(exc_info.value).lower()
        assert "401" in str(exc_info.value)

    # 6. Rate Limit Response (HTTP 429)
    def test_06_rate_limit_error(self):
        def mock_client(req, timeout) -> bytes:
            raise urllib.error.HTTPError(
                url="https://api.tavily.com/search",
                code=429,
                msg="Too Many Requests",
                hdrs={},
                fp=None,
            )

        transport = TavilyWebSearchTransport(
            api_key="tvly-test-key",
            enabled=True,
            http_client=mock_client,
        )

        with pytest.raises(DiscoveryExecutionError) as exc_info:
            transport.search("Query")
        assert "rate limit or quota exceeded" in str(exc_info.value).lower()

    # 7. Timeout Error
    def test_07_timeout_error(self):
        def mock_client(req, timeout) -> bytes:
            raise TimeoutError("Connection timed out")

        transport = TavilyWebSearchTransport(
            api_key="tvly-test-key",
            enabled=True,
            http_client=mock_client,
        )

        with pytest.raises(DiscoveryExecutionError) as exc_info:
            transport.search("Query")
        assert "timed out" in str(exc_info.value).lower()

    # 8. Provider 5xx Error
    def test_08_provider_server_error(self):
        def mock_client(req, timeout) -> bytes:
            raise urllib.error.HTTPError(
                url="https://api.tavily.com/search",
                code=500,
                msg="Internal Server Error",
                hdrs={},
                fp=None,
            )

        transport = TavilyWebSearchTransport(
            api_key="tvly-test-key",
            enabled=True,
            http_client=mock_client,
        )

        with pytest.raises(DiscoveryExecutionError) as exc_info:
            transport.search("Query")
        assert "failed with http 500" in str(exc_info.value).lower()

    # 9. No-Key Fail Closed Gate
    def test_09_no_key_fails_closed(self):
        transport = TavilyWebSearchTransport(api_key="", enabled=True)
        with pytest.raises(DiscoveryExecutionError) as exc_info:
            transport.search("Query")
        assert "api key is not configured" in str(exc_info.value).lower()

    # 10. Disabled-by-Default Gate
    def test_10_disabled_by_default(self):
        transport = TavilyWebSearchTransport(api_key="tvly-valid-key", enabled=False)
        with pytest.raises(DiscoveryExecutionError) as exc_info:
            transport.search("Query")
        assert "disabled" in str(exc_info.value).lower()

    # 11. Zero Real External Network Calls
    def test_11_zero_real_network_calls(self):
        def mock_client(req, timeout) -> bytes:
            return json.dumps({"results": []}).encode("utf-8")

        transport = TavilyWebSearchTransport(
            api_key="tvly-test-key",
            enabled=True,
            http_client=mock_client,
        )

        with patch("socket.socket") as mock_socket:
            transport.search("Query")
            assert mock_socket.call_count == 0

    # 12. Full Integration with WebSearchDiscoveryProvider
    def test_12_provider_integration_end_to_end(self):
        def mock_client(req, timeout) -> bytes:
            return json.dumps(MOCK_TAVILY_CARDIOLOGY_RESPONSE).encode("utf-8")

        tavily_transport = TavilyWebSearchTransport(
            api_key="tvly-test-key",
            enabled=True,
            http_client=mock_client,
        )

        provider = WebSearchDiscoveryProvider(
            transport=tavily_transport,
            enabled=True,
            authorized_tenants={"tenant-123"},
        )

        task = DiscoveryTask(
            provider="web_search",
            category="medical_association",
            query="Sociedad Colombiana de Cardiología Cali",
            metadata={"organization_id": "tenant-123"},
        )

        candidates = provider.discover(task)
        # Should accept the society and reject the clinic
        assert len(candidates) == 1
        c = candidates[0]
        assert c.name == "Sociedad Colombiana de Cardiología y Cirugía Cardiovascular"
        assert c.website_url == "https://scc.org.co"
        assert c.latitude is None
        assert c.longitude is None
        assert c.raw_data["geographic_scope"] == GeographicScope.REGIONAL_COVERAGE_EVIDENCED.value
        assert c.raw_data["classification_status"] == "ACCEPTED_CANDIDATE"

    # 13. Medical Specialties Accepted Through Tavily Transport
    def test_13_medical_specialty_accepted(self):
        def mock_client(req, timeout) -> bytes:
            return json.dumps(MOCK_TAVILY_UROLOGY_RESPONSE).encode("utf-8")

        tavily_transport = TavilyWebSearchTransport(
            api_key="tvly-test-key",
            enabled=True,
            http_client=mock_client,
        )

        provider = WebSearchDiscoveryProvider(
            transport=tavily_transport,
            enabled=True,
            authorized_tenants={"tenant-123"},
        )

        task = DiscoveryTask(
            provider="web_search",
            category="medical_association",
            query="Sociedad Colombiana de Urología Cali",
            metadata={"organization_id": "tenant-123"},
        )

        candidates = provider.discover(task)
        assert len(candidates) == 1
        assert "urología" in candidates[0].name.lower()
        assert candidates[0].website_url == "https://scu.org.co"

    # 14. Facility Exclusions Enforced Through Tavily Transport
    def test_14_facility_exclusions_enforced(self):
        def mock_client(req, timeout) -> bytes:
            return json.dumps({
                "results": [
                    {
                        "title": "Hospital Universitario San José",
                        "url": "https://hospitalsanjose.org",
                        "content": "Hospital de tercer nivel con especialidades médicas.",
                    },
                    {
                        "title": "Farmacia Médica San Jorge",
                        "url": "https://farmaciasanjorge.com",
                        "content": "Distribución de productos farmacéuticos.",
                    },
                ]
            }).encode("utf-8")

        tavily_transport = TavilyWebSearchTransport(
            api_key="tvly-test-key",
            enabled=True,
            http_client=mock_client,
        )

        provider = WebSearchDiscoveryProvider(
            transport=tavily_transport,
            enabled=True,
            authorized_tenants={"tenant-123"},
        )

        task = DiscoveryTask(
            provider="web_search",
            category="medical_association",
            query="Hospitales y farmacias",
            metadata={"organization_id": "tenant-123"},
        )

        candidates = provider.discover(task)
        assert len(candidates) == 0

    # 15. Secret Sanitization in Repr
    def test_15_secret_sanitization(self):
        transport = TavilyWebSearchTransport(
            api_key="tvly-secret-raw-key-sensitive",
            enabled=True,
        )
        repr_str = repr(transport)
        assert "tvly-secret-raw-key-sensitive" not in repr_str
        assert "SET (***)" in repr_str

    # 16. Zero Real Tavily Persistence
    def test_16_zero_real_tavily_persistence(self):
        """Verifies that no live credentials or persistent Tavily files exist."""
        import bopclients.infrastructure.providers.tavily_transport as mod
        import inspect

        source = inspect.getsource(mod)
        # Ensure default key is empty
        assert 'api_key: str = ""' in source
        # Ensure disabled by default
        assert "enabled: bool = False" in source

    # 17. Country Parameter Contract Mapping & Safe Omission
    def test_17_country_parameter_contract_mapping(self):
        """Verifies country code mapping: CO->colombia, US->united states, unsupported->omitted."""
        recorded_payloads = []

        def mock_client(req: urllib.request.Request, timeout: float) -> bytes:
            body = json.loads(req.data.decode("utf-8"))
            recorded_payloads.append(body)
            return json.dumps({"results": []}).encode("utf-8")

        transport = TavilyWebSearchTransport(
            api_key="tvly-mock-key",
            enabled=True,
            http_client=mock_client,
        )

        # A. Canonical CO variations -> "colombia"
        for co_val in ["CO", "co", " Colombia ", "colombia"]:
            transport.search("query test", country=co_val)
            last = recorded_payloads[-1]
            assert last.get("country") == "colombia", f"Expected 'colombia' for {co_val}, got {last.get('country')}"

        # B. Canonical US variations -> "united states"
        for us_val in ["US", "us", " USA ", "United States", "united states"]:
            transport.search("query test", country=us_val)
            last = recorded_payloads[-1]
            assert last.get("country") == "united states", f"Expected 'united states' for {us_val}, got {last.get('country')}"

        # C. Unsupported countries -> omitted from payload (do not send invalid codes to Tavily)
        for unsupp in ["DE", "FR", "GB", "ES", "XYZ", "unknown"]:
            transport.search("query test", country=unsupp)
            last = recorded_payloads[-1]
            assert "country" not in last, f"Expected 'country' to be omitted for unsupported '{unsupp}', got {last.get('country')}"

        # D. None or empty string -> omitted from payload
        for empty_val in [None, "", "   "]:
            transport.search("query test", country=empty_val)
            last = recorded_payloads[-1]
            assert "country" not in last, f"Expected 'country' to be omitted for empty value, got {last.get('country')}"

    # 18. Country Boost Does Not Bypass Candidate Classification
    def test_18_country_boost_does_not_bypass_classification(self):
        """Verifies that sending country='colombia' does not mark an unrelated entity as verified."""
        def mock_client(req, timeout) -> bytes:
            # Return an entity that is unrelated (e.g., a hardware store)
            resp = {
                "results": [
                    {
                        "title": "Ferretería El Tornillo | Materiales de Construcción",
                        "url": "https://ferreteriaeltornillo.com",
                        "content": "Venta de herramientas y tornillos en Colombia.",
                    }
                ]
            }
            return json.dumps(resp).encode("utf-8")

        transport = TavilyWebSearchTransport(
            api_key="tvly-mock-key",
            enabled=True,
            http_client=mock_client,
        )

        provider = WebSearchDiscoveryProvider(
            transport=transport,
            enabled=True,
            authorized_tenants={"tenant-123"},
        )

        task = DiscoveryTask(
            provider="web_search",
            category="medical_association",
            country="CO",
            query="asociaciones medicas cali",
            metadata={"organization_id": "tenant-123"},
        )

        # Classification must reject the hardware store despite country='colombia' boost
        candidates = provider.discover(task)
        assert len(candidates) == 0
