"""FORGE Enrichment Provider mapping product-level IEnrichmentProvider to FORGE Gateway."""

from typing import List, Dict, Any, Optional
from bopclients.domain.prospect import Prospect
from bopclients.domain.exceptions import DiscoveryProviderError
from bopclients.application.enrichment_dto import EnrichmentSnapshot
from bopclients.application.interfaces.enrichment_interfaces import IEnrichmentProvider
from bopclients.application.interfaces.forge_gateways import (
    IForgeEnrichmentGateway,
    EnrichmentTask,
)


class ForgeEnrichmentProvider(IEnrichmentProvider):
    """Enrichment provider wrapping FORGE EnrichmentPipeline via IForgeEnrichmentGateway."""

    def __init__(self, enrichment_gateway: IForgeEnrichmentGateway):
        self.enrichment_gateway = enrichment_gateway

    @property
    def name(self) -> str:
        return "forge"

    def supports(self, prospect: Prospect) -> bool:
        return True

    def enrich(self, org_id: str, prospect: Prospect) -> EnrichmentSnapshot:
        if not prospect.website_url:
            return EnrichmentSnapshot(
                provider="forge",
                prospect_id=prospect.id,
                website_url=None,
                website_reachable=False,
                scrape_status="no_website",
            )

        biz_record = {
            "id": prospect.forge_record_id or prospect.id,
            "name": prospect.name,
            "website": prospect.website_url,
            "website_url": prospect.website_url,
            "phone": prospect.phone,
            "address": prospect.address,
            "city": prospect.city,
            "state": prospect.state,
            "zip": prospect.postal_code,
            "category": prospect.industry,
        }

        task = EnrichmentTask(
            mode="email",  # Email + Web scrape mode in FORGE
            business_records=[biz_record],
            workers=2,
        )

        try:
            results = self.enrichment_gateway.enrich_batch(task)
            rec = results[0] if results else {}

            raw_status = rec.get("scrape_status") or rec.get("status") or "success"
            http_status = rec.get("status_code") or rec.get("http_status") or (200 if raw_status == "success" else None)
            
            # Map website reachability
            reachable = (
                raw_status in ("success", "partial_timeout")
                and (http_status is None or http_status in (200, 301, 302, 307, 308))
            )

            # Parse emails
            raw_emails = rec.get("emails") or []
            if isinstance(raw_emails, str):
                emails = [e.strip() for e in raw_emails.split(",") if e.strip()]
            else:
                emails = list(raw_emails)

            # Parse technologies & CMS
            raw_techs = rec.get("technologies") or []
            if isinstance(raw_techs, str):
                techs = [t.strip() for t in raw_techs.split(",") if t.strip()]
            else:
                techs = list(raw_techs)

            cms = rec.get("cms")
            if not cms:
                for t in techs:
                    if t.lower() in ("wordpress", "shopify", "squarespace", "wix", "webflow"):
                        cms = t
                        break

            # Technical flags
            ssl_val = rec.get("ssl_valid")
            ssl_bool = bool(ssl_val) if ssl_val is not None else (True if (prospect.website_url or "").startswith("https") else False)
            resp_time = rec.get("response_time_ms")
            if resp_time is not None:
                resp_time = float(resp_time)

            # Detectors for booking, chatbot, analytics from HTML/tech stack
            has_analytics = "google_analytics" in [t.lower() for t in techs] or "gtm" in [t.lower() for t in techs]
            
            raw_html = str(rec.get("raw_html") or "").lower()
            has_chatbot = any(w in raw_html or w in techs for w in ["intercom", "drift", "hubspot", "tidio", "crisp", "livechat", "zendesk", "chatwoot", "chatbot"])
            has_booking = any(b in raw_html for b in ["booking", "calendly", "acuity", "schedule appointment", "agendar cita", "reservar", "book online"])

            return EnrichmentSnapshot(
                provider="forge",
                prospect_id=prospect.id,
                website_url=prospect.website_url,
                website_reachable=reachable,
                scrape_status=raw_status,
                emails=emails,
                phones=[prospect.phone] if prospect.phone else [],
                technologies=techs,
                cms=cms,
                ssl_valid=ssl_bool,
                response_time_ms=resp_time,
                http_status=http_status,
                has_contact_page=bool(emails),
                has_booking=has_booking,
                has_chatbot=has_chatbot,
                has_analytics=has_analytics,
                raw_metadata=rec,
            )

        except Exception as e:
            return EnrichmentSnapshot(
                provider="forge",
                prospect_id=prospect.id,
                website_url=prospect.website_url,
                website_reachable=False,
                scrape_status="timeout",
                raw_metadata={"error": str(e)},
            )
