"""Tavily web search transport implementation for WebSearchDiscoveryProvider.

Implements IWebSearchTransport using the official documented Tavily Search API contract.
Enforces disabled-by-default behavior, no-key fail closed, and strict request boundaries.
"""

import json
import logging
from typing import Dict, Any, Optional, List, Callable
import urllib.request
import urllib.error

from bopclients.infrastructure.providers.web_search_provider import IWebSearchTransport
from bopclients.domain.exceptions import DiscoveryExecutionError

logger = logging.getLogger("bopclients.providers.tavily")


class TavilyWebSearchTransport(IWebSearchTransport):
    """Transport adapter connecting to the official Tavily Search API.

    Safety:
    1. Disabled by default (`enabled=False`).
    2. Fails closed with `DiscoveryExecutionError` if no API key is provided.
    3. Never exposes API keys in logs or string representations.
    4. Enforces request bounds (clamped to max 20 results, `search_depth='basic'`).
    5. Pluggable `http_client` callable to allow 100% deterministic offline mocked testing.
    """

    DEFAULT_ENDPOINT = "https://api.tavily.com/search"
    MAX_RESULTS_PER_REQUEST = 20

    # Supported Tavily country names mapping from standard ISO alpha-2 codes or full names
    SUPPORTED_COUNTRY_MAP: Dict[str, str] = {
        "co": "colombia",
        "colombia": "colombia",
        "us": "united states",
        "usa": "united states",
        "united states": "united states",
    }

    def __init__(
        self,
        api_key: str = "",
        enabled: bool = False,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout_seconds: float = 10.0,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        http_client: Optional[Callable[[urllib.request.Request, float], bytes]] = None,
    ):
        self.api_key = (api_key or "").strip()
        self.enabled = enabled
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.include_domains = list(include_domains or [])
        self.exclude_domains = list(exclude_domains or [])
        self._http_client = http_client

    def __repr__(self) -> str:
        key_repr = "SET (***)" if self.api_key else "NOT SET"
        return f"TavilyWebSearchTransport(enabled={self.enabled}, api_key={key_repr}, endpoint='{self.endpoint}')"

    def search(
        self,
        query: str,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        count: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Execute Tavily search query and map into standard web result contract."""
        # 1. Gate: Explicit enablement
        if not self.enabled:
            raise DiscoveryExecutionError(
                "TavilyWebSearchTransport is disabled. Explicit enablement required."
            )

        # 2. Gate: API Key required
        if not self.api_key:
            raise DiscoveryExecutionError(
                "Tavily API key is not configured. Transport is inactive."
            )

        clean_query = (query or "").strip()
        if not clean_query:
            return {
                "query": {"original": query, "more_results_available": False},
                "web": {"results": []},
            }

        # 3. Construct documented Tavily JSON payload
        clamped_count = min(max(1, count), self.MAX_RESULTS_PER_REQUEST)
        payload: Dict[str, Any] = {
            "query": clean_query,
            "search_depth": "basic",
            "topic": "general",
            "max_results": clamped_count,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }

        if country:
            norm_country = country.strip().lower()
            tavily_country = self.SUPPORTED_COUNTRY_MAP.get(norm_country)
            if tavily_country:
                payload["country"] = tavily_country

        if self.include_domains:
            payload["include_domains"] = list(self.include_domains)

        if self.exclude_domains:
            payload["exclude_domains"] = list(self.exclude_domains)

        # 4. Execute HTTP request via injected client or urllib
        raw_bytes = self._execute_http(payload)

        # 5. Parse and map response
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except Exception as e:
            raise DiscoveryExecutionError(f"Tavily response parsing error: {e}")

        return self._map_response(clean_query, data)

    def _execute_http(self, payload: Dict[str, Any]) -> bytes:
        """Execute HTTP request with sanitized error handling."""
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        req = urllib.request.Request(
            url=self.endpoint,
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            if self._http_client is not None:
                return self._http_client(req, self.timeout_seconds)

            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            err_detail = ""
            try:
                raw_err = e.read()
                if raw_err:
                    err_json = json.loads(raw_err.decode("utf-8"))
                    if isinstance(err_json, dict):
                        detail_val = err_json.get("detail") or err_json.get("message")
                        if detail_val:
                            err_detail = f": {detail_val}"
            except Exception:
                pass

            if e.code in (401, 403):
                raise DiscoveryExecutionError(
                    f"Tavily authentication failed: invalid or unauthorized API key (HTTP {e.code}){err_detail}"
                )
            elif e.code == 429:
                raise DiscoveryExecutionError(
                    f"Tavily rate limit or quota exceeded (HTTP 429){err_detail}"
                )
            else:
                raise DiscoveryExecutionError(
                    f"Tavily search request failed with HTTP {e.code}{err_detail}"
                )
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError) or "timed out" in str(e.reason).lower():
                raise DiscoveryExecutionError(
                    f"Tavily request timed out after {self.timeout_seconds}s"
                )
            raise DiscoveryExecutionError(
                f"Tavily connection error: {e.reason}"
            )
        except TimeoutError:
            raise DiscoveryExecutionError(
                f"Tavily request timed out after {self.timeout_seconds}s"
            )
        except Exception as e:
            raise DiscoveryExecutionError(f"Tavily request failed: {e}")

    def _map_response(self, query: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Tavily response into standard provider-neutral result contract."""
        raw_results = data.get("results", []) if isinstance(data, dict) else []
        mapped_results: List[Dict[str, Any]] = []

        if isinstance(raw_results, list):
            for item in raw_results:
                if not isinstance(item, dict):
                    continue

                title = str(item.get("title") or "").strip()
                url = str(item.get("url") or "").strip()
                # Tavily returns snippet in 'content'
                description = str(item.get("content") or item.get("description") or "").strip()

                if not title or not url:
                    continue

                mapped_results.append(
                    {
                        "title": title,
                        "url": url,
                        "description": description,
                        "score": item.get("score"),
                    }
                )

        return {
            "query": {"original": query, "more_results_available": False},
            "web": {"results": mapped_results},
        }
