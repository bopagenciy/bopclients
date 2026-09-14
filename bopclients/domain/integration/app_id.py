"""Canonical application identity definitions and validation for the Bop Platform."""

import re
from enum import Enum
from typing import Set


class BopAppId(str, Enum):
    """Canonical application identifiers across the Bop Platform ecosystem."""

    BOPCLIENTS = "bopclients"
    BOPCRM = "bopcrm"
    BOPERP = "boperp"
    BOPSOCIAL = "bopsocial"
    BOPCHATBOT = "bopchatbot"
    BOPASSISTANT = "bopassistant"


# Local BopClients application identity
LOCAL_APPLICATION_ID: str = BopAppId.BOPCLIENTS.value

# Known registered platform applications
REGISTERED_BOP_APPS: Set[str] = {app.value for app in BopAppId}

# Wire syntax pattern: starts with lowercase letter, lowercase alphanumeric/hyphen/underscore, 2-32 chars
_APP_ID_SYNTAX_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")


def validate_application_id_syntax(app_id: str) -> str:
    """Validate application identifier syntax for cross-app wire compatibility.

    Args:
        app_id: Application identifier string.

    Returns:
        Normalized lowercase application identifier.

    Raises:
        ValueError: If application identifier is empty, malformed, or invalid syntax.
    """
    if not isinstance(app_id, str):
        raise ValueError(f"Application ID must be a string, got {type(app_id).__name__}")

    normalized = app_id.strip().lower()
    if not normalized:
        raise ValueError("Application ID cannot be empty")

    if not _APP_ID_SYNTAX_PATTERN.match(normalized):
        raise ValueError(
            f"Invalid application ID '{app_id}'. Must start with a lowercase letter and contain only "
            f"lowercase alphanumeric characters, hyphens, or underscores (2 to 32 characters)."
        )

    return normalized


def is_known_application_id(app_id: str) -> bool:
    """Check if application identifier is in the locally known registry."""
    if not isinstance(app_id, str):
        return False
    return app_id.strip().lower() in REGISTERED_BOP_APPS


def validate_application_id(app_id: str, enforce_known: bool = False) -> str:
    """Validate a Bop application identifier.

    By default validates wire syntactic validity so future Bop apps (e.g. 'bopinventory')
    are deserializable and wire-compatible without code changes.
    If enforce_known=True, requires registration in REGISTERED_BOP_APPS.
    """
    normalized = validate_application_id_syntax(app_id)
    if enforce_known and normalized not in REGISTERED_BOP_APPS:
        raise ValueError(f"Application ID '{normalized}' is not a registered Bop application")
    return normalized
