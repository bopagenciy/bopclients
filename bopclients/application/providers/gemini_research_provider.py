"""Google Gemini Prospect Research Provider implementing structured LLM sales research."""

import json
import time
import uuid
import httpx
from typing import Optional, List, Dict, Any
from bopclients.domain.exceptions import (
    AIConfigurationError,
    AIAuthenticationError,
    AIRateLimitError,
    AITimeoutError,
    AIProviderError,
    AIResponseValidationError,
)
from bopclients.application.ai_config import AIResearchConfig
from bopclients.application.research_dto import (
    ProspectResearchContext,
    ProspectResearchDraft,
    ResearchClaim,
    CommercialOpportunity,
    AIResearchRequest,
    AIResearchResponse,
)
from bopclients.application.prompt_templates import (
    AI_RESEARCH_PROMPT_VERSION,
    AI_RESEARCH_SYSTEM_PROMPT,
    AI_RESEARCH_USER_PROMPT_TEMPLATE,
    AI_RESEARCH_RESPONSE_SCHEMA_V1,
)
from bopclients.application.interfaces.research_interfaces import IAIProspectResearchProvider


class GeminiProspectResearchProvider(IAIProspectResearchProvider):
    """Google Gemini AI Prospect Research Provider utilizing Gemini REST API with structured output."""

    API_MODE = "generateContent_legacy"

    def __init__(
        self,
        config: Optional[AIResearchConfig] = None,
        http_client: Optional[Any] = None,
    ):
        self.config = config or AIResearchConfig()
        self.http_client = http_client

    @property
    def name(self) -> str:
        return f"gemini:{self.config.model}"

    def build_research_request(self, context: ProspectResearchContext) -> AIResearchRequest:
        """Sanitize ProspectResearchContext into a tenant-safe AIResearchRequest."""
        p = context.prospect
        snap = context.enrichment_snapshot
        signals = context.signals
        services = context.services
        icp = context.icp

        catalog: Dict[str, Any] = {}
        allowed_ev: List[str] = []
        allowed_src: List[str] = []
        allowed_svc: List[str] = []

        if snap:
            snap_id = f"enrichment:{p.id}"
            allowed_src.append(snap_id)
            catalog[snap_id] = {
                "scrape_status": snap.scrape_status,
                "http_status": snap.http_status,
                "technologies": snap.technologies,
                "cms": snap.cms,
                "response_time_ms": snap.response_time_ms,
            }

        for sig in signals:
            sig_id = f"signal:{sig.type}"
            allowed_ev.append(sig_id)
            catalog[sig_id] = {
                "type": sig.type,
                "confidence": sig.confidence,
                "value": sig.value,
                "source": sig.source,
            }
            if f"provider:{sig.source}" not in allowed_src:
                allowed_src.append(f"provider:{sig.source}")

        svc_list: List[Dict[str, Any]] = []
        for svc in services:
            if getattr(svc, 'active', True):
                svc_ref = svc.category or svc.name
                allowed_svc.append(svc_ref)
                allowed_svc.append(svc.name)
                svc_list.append({
                    "id": svc.id,
                    "name": svc.name,
                    "category": svc.category,
                    "description": svc.description,
                })

        return AIResearchRequest(
            organization_id=context.organization_id,
            prospect_name=p.name,
            industry=p.industry,
            country=p.country,
            website_url=p.website_url,
            observed_signals=[{"type": s.type, "confidence": s.confidence, "value": s.value} for s in signals],
            available_services=svc_list,
            icp_description=icp.description if icp else None,
            evidence_catalog=catalog,
            allowed_evidence_refs=allowed_ev,
            allowed_source_refs=allowed_src,
            allowed_service_ids=allowed_svc,
        )

    def _extract_error_message(self, resp: Any) -> str:
        """Safely extract clean error message from response without crashing or exposing key."""
        try:
            err_data = resp.json()
            if isinstance(err_data, dict) and "error" in err_data:
                err_obj = err_data["error"]
                if isinstance(err_obj, dict):
                    msg = err_obj.get("message", resp.text)
                    return self._sanitize_text(msg)
                return self._sanitize_text(str(err_obj))
        except Exception:
            pass
        return self._sanitize_text(resp.text or f"HTTP status {resp.status_code}")

    def _sanitize_text(self, text: str) -> str:
        """Sanitize any sensitive text to ensure API key is never leaked."""
        if not text:
            return ""
        if self.config.api_key and self.config.api_key in text:
            text = text.replace(self.config.api_key, "[REDACTED_API_KEY]")
        return text

    def _validate_local_json_schema(self, parsed: Dict[str, Any]) -> None:
        """Enforce strict local schema validation on parsed JSON response."""
        if not isinstance(parsed, dict):
            raise AIResponseValidationError("Gemini structured JSON output is not a JSON object.")

        required_root = ["executive_summary", "business_profile_notes", "claims", "commercial_opportunities", "risks", "unknowns"]
        for field_name in required_root:
            if field_name not in parsed:
                raise AIResponseValidationError(f"Missing required field in Gemini JSON output: '{field_name}'")

        if not isinstance(parsed["claims"], list):
            raise AIResponseValidationError("Field 'claims' must be a JSON array.")

        if not isinstance(parsed["commercial_opportunities"], list):
            raise AIResponseValidationError("Field 'commercial_opportunities' must be a JSON array.")

        if not isinstance(parsed["risks"], list) or not isinstance(parsed["unknowns"], list):
            raise AIResponseValidationError("Fields 'risks' and 'unknowns' must be JSON arrays of strings.")

        for idx, claim in enumerate(parsed["claims"]):
            if not isinstance(claim, dict):
                raise AIResponseValidationError(f"Claim at index {idx} must be a JSON object.")
            cls = claim.get("classification")
            if cls not in ("observed", "derived", "inferred"):
                raise AIResponseValidationError(
                    f"Claim at index {idx} has invalid classification: '{cls}'. Expected 'observed', 'derived', or 'inferred'."
                )
            if not isinstance(claim.get("statement"), str) or not claim.get("statement"):
                raise AIResponseValidationError(f"Claim at index {idx} is missing valid 'statement' string.")

        for idx, opp in enumerate(parsed["commercial_opportunities"]):
            if not isinstance(opp, dict):
                raise AIResponseValidationError(f"Commercial opportunity at index {idx} must be a JSON object.")
            prio = opp.get("priority")
            if prio not in ("low", "medium", "high"):
                raise AIResponseValidationError(
                    f"Commercial opportunity at index {idx} has invalid priority: '{prio}'. Expected 'low', 'medium', or 'high'."
                )
            if not isinstance(opp.get("title"), str) or not opp.get("title"):
                raise AIResponseValidationError(f"Commercial opportunity at index {idx} is missing valid 'title' string.")

    def generate_ai_research(self, request: AIResearchRequest) -> AIResearchResponse:
        """Invoke Google Gemini REST API via secure header authentication and JSON Schema structured output."""
        if not self.config.api_key:
            raise AIConfigurationError("GEMINI_API_KEY is not configured.")
        if not self.config.model or not self.config.model.strip():
            raise AIConfigurationError("GEMINI_MODEL configuration cannot be empty.")

        user_prompt = AI_RESEARCH_USER_PROMPT_TEMPLATE.format(
            prospect_name=request.prospect_name,
            industry=request.industry or "Unknown",
            country=request.country or "Unknown",
            website_url=request.website_url or "None",
            services_json=json.dumps(request.available_services, indent=2),
            icp_json=json.dumps(request.icp_description or "Standard B2B ICP", indent=2),
            evidence_catalog_json=json.dumps(request.evidence_catalog, indent=2),
        )

        payload = {
            "systemInstruction": {
                "parts": [{"text": AI_RESEARCH_SYSTEM_PROMPT}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": self.config.max_output_tokens,
                "responseFormat": {
                    "text": {
                        "mimeType": "application/json",
                        "schema": AI_RESEARCH_RESPONSE_SCHEMA_V1,
                    }
                },
            }
        }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.config.model}:generateContent"
        headers = {
            "x-goog-api-key": self.config.api_key,
            "Content-Type": "application/json",
        }

        max_attempts = 1 + max(0, self.config.max_retries)
        last_exception = None

        for attempt in range(max_attempts):
            try:
                if self.http_client:
                    resp = self.http_client.post(url, json=payload, headers=headers, timeout=self.config.timeout_seconds)
                else:
                    with httpx.Client(timeout=self.config.timeout_seconds) as client:
                        resp = client.post(url, json=payload, headers=headers)

                status = resp.status_code

                if status == 200:
                    try:
                        data = resp.json()
                    except Exception as err:
                        raise AIResponseValidationError(f"Failed to parse Gemini API JSON envelope: {err}") from err

                    candidates = data.get("candidates", [])
                    if not candidates or not isinstance(candidates, list):
                        prompt_feedback = data.get("promptFeedback", {})
                        block_reason = prompt_feedback.get("blockReason")
                        if block_reason:
                            raise AIResponseValidationError(f"Gemini prompt blocked by content policy (reason: '{block_reason}').")
                        raise AIResponseValidationError("Gemini API response contains no candidates.")

                    cand = candidates[0]
                    finish_reason = cand.get("finishReason")
                    if finish_reason and finish_reason not in ("STOP", "MAX_TOKENS"):
                        raise AIResponseValidationError(f"Gemini candidate completion failed (finishReason: '{finish_reason}').")

                    content_obj = cand.get("content", {})
                    parts = content_obj.get("parts", []) if isinstance(content_obj, dict) else []
                    if not parts or not isinstance(parts, list):
                        raise AIResponseValidationError("Gemini API candidate content parts are empty.")

                    raw_text = parts[0].get("text", "") if isinstance(parts[0], dict) else ""
                    if not raw_text or not raw_text.strip():
                        raise AIResponseValidationError("Gemini API candidate text is empty.")

                    # Map usage metadata tolerantly
                    usage_dict = None
                    meta = data.get("usageMetadata")
                    if meta and isinstance(meta, dict):
                        usage_dict = {
                            "input_tokens": meta.get("promptTokenCount", 0),
                            "output_tokens": meta.get("candidatesTokenCount", 0),
                            "total_tokens": meta.get("totalTokenCount", 0),
                        }

                    # Parse JSON content
                    cleaned_text = raw_text.strip()
                    if cleaned_text.startswith("```json"):
                        cleaned_text = cleaned_text[7:]
                    if cleaned_text.startswith("```"):
                        cleaned_text = cleaned_text[3:]
                    if cleaned_text.endswith("```"):
                        cleaned_text = cleaned_text[:-3]
                    cleaned_text = cleaned_text.strip()

                    try:
                        parsed = json.loads(cleaned_text)
                    except json.JSONDecodeError as err:
                        raise AIResponseValidationError(f"Failed to parse Gemini structured JSON output: {err}") from err

                    # Local Schema & Enums Validation
                    self._validate_local_json_schema(parsed)

                    return AIResearchResponse(
                        executive_summary=parsed.get("executive_summary", ""),
                        business_profile_notes=parsed.get("business_profile_notes", ""),
                        proposed_claims=parsed.get("claims", []),
                        proposed_opportunities=parsed.get("commercial_opportunities", []),
                        perceived_risks=parsed.get("risks", []),
                        perceived_unknowns=parsed.get("unknowns", []),
                        usage_metadata=usage_dict,
                    )

                else:
                    err_msg = self._extract_error_message(resp)
                    if status in (401, 403):
                        raise AIAuthenticationError(f"Gemini API authentication failed ({status}): {err_msg}")
                    elif status == 400:
                        raise AIProviderError(f"Gemini API bad request (400): {err_msg}")
                    elif status == 429:
                        last_exception = AIRateLimitError(f"Gemini API rate limit exceeded (429): {err_msg}")
                    elif status >= 500:
                        last_exception = AIProviderError(f"Gemini API server error ({status}): {err_msg}")
                    else:
                        raise AIProviderError(f"Gemini API unexpected error ({status}): {err_msg}")

            except (httpx.TimeoutException, httpx.NetworkError) as err:
                last_exception = AITimeoutError(f"Gemini API request timed out or network failed: {self._sanitize_text(str(err))}")

            if attempt < max_attempts - 1:
                time.sleep(1.0)  # Retry backoff

        if last_exception:
            raise last_exception
        raise AIProviderError("Gemini API request failed after retries.")

    def research(self, context: ProspectResearchContext) -> ProspectResearchDraft:
        """Analyze prospect context using Gemini LLM and return ProspectResearchDraft."""
        req = self.build_research_request(context)
        ai_resp = self.generate_ai_research(req)

        claims: List[ResearchClaim] = []
        for cdict in ai_resp.proposed_claims:
            claims.append(
                ResearchClaim(
                    id=cdict.get("id", f"claim:ai:{uuid.uuid4().hex[:6]}"),
                    claim_type=cdict.get("claim_type", "ai_finding"),
                    statement=cdict.get("statement", ""),
                    classification=cdict.get("classification", "derived"),
                    confidence=float(cdict.get("confidence", 0.7)),
                    evidence_refs=cdict.get("evidence_refs", []),
                    source_refs=cdict.get("source_refs", []),
                )
            )

        opportunities: List[CommercialOpportunity] = []
        for odict in ai_resp.proposed_opportunities:
            opportunities.append(
                CommercialOpportunity(
                    opportunity_type=odict.get("opportunity_type", "commercial_improvement"),
                    title=odict.get("title", "Commercial Opportunity"),
                    description=odict.get("description", ""),
                    confidence=float(odict.get("confidence", 0.7)),
                    supporting_signals=odict.get("supporting_signals", []),
                    supporting_claims=odict.get("supporting_claims", []),
                    matched_services=odict.get("matched_services", []),
                    priority=odict.get("priority", "medium"),
                )
            )

        profile = {
            "name": req.prospect_name,
            "industry": req.industry or "Unknown",
            "country": req.country or "Unknown",
            "website_url": req.website_url,
            "notes": ai_resp.business_profile_notes,
        }

        return ProspectResearchDraft(
            executive_summary=ai_resp.executive_summary,
            business_profile=profile,
            claims=claims,
            commercial_opportunities=opportunities,
            recommended_services=[],
            risks=ai_resp.perceived_risks,
            unknowns=ai_resp.perceived_unknowns,
            overall_confidence=0.80 if claims else 0.40,
        )
