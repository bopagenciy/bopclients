"""Configuration object for P5 External AI Prospect Research Providers."""

import os
from dataclasses import dataclass
from bopclients.domain.exceptions import AIConfigurationError


@dataclass
class AIResearchConfig:
    """Configuration settings for external LLM prospect research provider (Gemini 3.x aligned)."""

    provider: str = "gemini"
    model: str = ""
    api_key: str = ""
    timeout_seconds: float = 25.0
    max_output_tokens: int = 2048
    max_retries: int = 1

    def __post_init__(self):
        if not self.model or not self.model.strip():
            self.model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash").strip()
        self.model = self.model.strip()
        if not self.model:
            raise AIConfigurationError("GEMINI_MODEL configuration cannot be empty.")
        if not self.api_key:
            self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()
