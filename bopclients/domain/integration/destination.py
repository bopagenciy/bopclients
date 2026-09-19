"""Integration destination and subscription domain models."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any
import json
import re
from urllib.parse import urlparse
import uuid

# Headers prohibited from being stored in destination non_secret_headers_json
SENSITIVE_HEADER_NAMES = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "x-auth-token",
    "x-access-token",
    "token",
    "secret",
}


# Strict namespaced syntax for secret references
SECRET_REFERENCE_PATTERN = r"^BOP_INTEGRATION_SECRET_[A-Z0-9_]{1,80}$"
SECRET_REFERENCE_REGEX = re.compile(SECRET_REFERENCE_PATTERN)


def validate_secret_reference(ref: str) -> str:
    """Validate that a secret key reference strictly conforms to the approved integration namespace."""
    if not ref or not isinstance(ref, str):
        raise ValueError("Secret key reference must be a non-empty string")
    clean = ref.strip()
    if not clean:
        raise ValueError("Secret key reference cannot be empty")
    if not SECRET_REFERENCE_REGEX.match(clean):
        raise ValueError(
            f"Invalid secret_key_ref '{ref}': must match namespaced pattern '^BOP_INTEGRATION_SECRET_[A-Z0-9_]{{1,80}}$'. "
            "Arbitrary environment variables cannot be accessed."
        )
    return clean


class DestinationTransportType(str, Enum):
    """Supported transport protocols for integration event delivery."""

    HTTP = "HTTP"


class DestinationAuthMode(str, Enum):
    """Supported authentication modes for integration event delivery."""

    HMAC_SHA256 = "HMAC_SHA256"
    BEARER = "BEARER"


@dataclass
class IntegrationDestination:
    """Outbound delivery endpoint definition for an external consuming application."""

    id: str
    bop_organization_id: str
    target_app_id: str
    destination_name: str
    transport_type: str
    endpoint_url: str
    secret_key_ref: Optional[str]
    headers_template_json: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str
    auth_mode: str = DestinationAuthMode.HMAC_SHA256.value

    @classmethod
    def create(
        cls,
        bop_organization_id: str,
        target_app_id: str,
        destination_name: str,
        endpoint_url: str,
        transport_type: str = DestinationTransportType.HTTP.value,
        auth_mode: str = DestinationAuthMode.HMAC_SHA256.value,
        secret_key_ref: Optional[str] = None,
        headers_template: Optional[Dict[str, str]] = None,
        is_active: bool = True,
        destination_id: Optional[str] = None,
    ) -> "IntegrationDestination":
        """Factory creating a validated IntegrationDestination."""
        if not bop_organization_id or not bop_organization_id.strip():
            raise ValueError("bop_organization_id cannot be empty")
        if not target_app_id or not target_app_id.strip():
            raise ValueError("target_app_id cannot be empty")
        if not destination_name or not destination_name.strip():
            raise ValueError("destination_name cannot be empty")
        if not endpoint_url or not endpoint_url.strip():
            raise ValueError("endpoint_url cannot be empty")

        clean_auth_mode = (auth_mode or DestinationAuthMode.HMAC_SHA256.value).strip().upper()
        if clean_auth_mode not in (
            DestinationAuthMode.HMAC_SHA256.value,
            DestinationAuthMode.BEARER.value,
        ):
            raise ValueError(
                f"Invalid auth_mode '{auth_mode}': must be one of {[m.value for m in DestinationAuthMode]}"
            )

        clean_url = endpoint_url.strip()
        parsed = urlparse(clean_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid endpoint_url '{clean_url}': must start with http:// or https://")
        if parsed.username or parsed.password:
            raise ValueError(f"Invalid endpoint_url '{clean_url}': credentials (user:password) are strictly prohibited in URLs")

        # Validate non-secret custom headers (both keys and values)
        if headers_template:
            sensitive_val_pattern = re.compile(
                r"(?i)(bearer\s+|basic\s+|api[_-]?key\s*=|apikey\s*=|access_token\s*=|refresh_token\s*=|password\s*=|secret\s*=|credential\s*=)"
            )
            for k, v in headers_template.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise ValueError("Destination header names and values must be strings")
                # Prohibit CR/LF injection
                if "\r" in k or "\n" in k:
                    raise ValueError(f"CR/LF injection detected in header name: '{repr(k)}'")
                if "\r" in v or "\n" in v:
                    raise ValueError(f"CR/LF injection detected in header value for key '{k}'")

                k_clean = k.strip().lower()
                for disallowed in SENSITIVE_HEADER_NAMES:
                    if k_clean == disallowed or k_clean.startswith(disallowed):
                        raise ValueError(f"Persisted destination headers must not contain credentials or auth headers: '{k}' is prohibited")
                if sensitive_val_pattern.search(v.strip()):
                    raise ValueError(
                        f"Persisted destination header value for '{k}' contains credential or authentication material, which is strictly prohibited. Use secret_key_ref instead."
                    )

        # Validate secret key reference if supplied
        valid_secret_ref = validate_secret_reference(secret_key_ref) if secret_key_ref else None

        now = datetime.now(timezone.utc).isoformat()
        headers_json = json.dumps(headers_template) if headers_template else None

        return cls(
            id=destination_id or str(uuid.uuid4()),
            bop_organization_id=bop_organization_id.strip(),
            target_app_id=target_app_id.strip(),
            destination_name=destination_name.strip(),
            transport_type=transport_type,
            endpoint_url=clean_url,
            secret_key_ref=valid_secret_ref,
            headers_template_json=headers_json,
            is_active=is_active,
            created_at=now,
            updated_at=now,
            auth_mode=clean_auth_mode,
        )

    def get_headers_template(self) -> Dict[str, str]:
        """Parse headers_template_json into a dictionary."""
        if not self.headers_template_json:
            return {}
        try:
            parsed = json.loads(self.headers_template_json)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


@dataclass
class IntegrationSubscription:
    """Subscription rule mapping an event type pattern to an active destination."""

    id: str
    bop_organization_id: str
    destination_id: str
    event_type: str
    is_active: bool
    created_at: str

    @classmethod
    def create(
        cls,
        bop_organization_id: str,
        destination_id: str,
        event_type: str,
        is_active: bool = True,
        subscription_id: Optional[str] = None,
    ) -> "IntegrationSubscription":
        """Factory creating a validated IntegrationSubscription."""
        if not bop_organization_id or not bop_organization_id.strip():
            raise ValueError("bop_organization_id cannot be empty")
        if not destination_id or not destination_id.strip():
            raise ValueError("destination_id cannot be empty")
        if not event_type or not event_type.strip():
            raise ValueError("event_type cannot be empty")

        now = datetime.now(timezone.utc).isoformat()
        return cls(
            id=subscription_id or str(uuid.uuid4()),
            bop_organization_id=bop_organization_id.strip(),
            destination_id=destination_id.strip(),
            event_type=event_type.strip(),
            is_active=is_active,
            created_at=now,
        )
