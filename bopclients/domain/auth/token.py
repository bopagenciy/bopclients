"""Token security and session token management service."""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger("bopclients.auth.token")

TOKEN_ISSUER = "bopclients"
TOKEN_AUDIENCE = "bopclients-api"
TOKEN_ALGORITHM = "HS256"
DEFAULT_ACCESS_TOKEN_EXPIRE_SECONDS = 3600  # 1 hour
DEFAULT_CLOCK_SKEW_SECONDS = 30


class TokenSecurityError(Exception):
    """Base exception for token generation and verification failures."""


class TokenExpiredError(TokenSecurityError):
    """Raised when token expiration timestamp has elapsed."""


class TokenInvalidError(TokenSecurityError):
    """Raised when token signature, format, or claims are invalid."""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data.encode("ascii"))


@dataclass(frozen=True)
class TokenPayload:
    """Decoded access token claims payload."""

    sub: str  # user_id
    email: str
    session_id: str
    exp: int
    iat: int
    jti: str
    iss: str = TOKEN_ISSUER
    aud: str = TOKEN_AUDIENCE

    @property
    def user_id(self) -> str:
        return self.sub

    @property
    def expires_at(self) -> int:
        return self.exp


@dataclass
class TokenPair:
    """Access token and optional refresh/session token pair."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = DEFAULT_ACCESS_TOKEN_EXPIRE_SECONDS
    refresh_token: Optional[str] = None


class TokenService:
    """Service providing signed JWT access tokens and hashed session tokens."""

    def __init__(
        self,
        signing_key: str,
        access_token_expire_seconds: int = DEFAULT_ACCESS_TOKEN_EXPIRE_SECONDS,
        clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS,
        expire_seconds: Optional[int] = None,
    ):
        if not signing_key or not signing_key.strip():
            raise ValueError("TokenService signing_key must be a non-empty string.")
        if len(signing_key.strip()) < 32:
            raise ValueError("TokenService signing_key must be at least 32 characters for HS256 security.")

        self._signing_key = signing_key.strip().encode("utf-8")
        self.access_token_expire_seconds = expire_seconds if expire_seconds is not None else access_token_expire_seconds
        self.clock_skew_seconds = clock_skew_seconds

    @staticmethod
    def generate_opaque_session_token() -> str:
        """Generate high-entropy random session token."""
        return f"bop_sess_{secrets.token_urlsafe(32)}"

    generate_session_token = generate_opaque_session_token

    @staticmethod
    def hash_session_token(raw_token: str) -> str:
        """Compute deterministic SHA-256 hash of session token for storage."""
        if not raw_token or not raw_token.strip():
            raise ValueError("Raw token must be non-empty string.")
        return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()

    def create_access_token(
        self,
        user_id: str,
        email: str,
        session_id: str,
        expires_in: Optional[int] = None,
        custom_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Encode HMAC-SHA256 JWT access token."""
        if not user_id:
            raise ValueError("user_id cannot be empty")

        now = int(time.time())
        ttl = expires_in if expires_in is not None else self.access_token_expire_seconds
        exp = now + ttl

        header = {"alg": TOKEN_ALGORITHM, "typ": "JWT"}
        payload = {
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "sub": user_id,
            "email": email,
            "session_id": session_id,
            "iat": now,
            "exp": exp,
            "jti": str(uuid.uuid4()),
        }
        if custom_claims:
            payload.update(custom_claims)

        header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")

        signature = hmac.new(self._signing_key, signing_input, hashlib.sha256).digest()
        sig_b64 = _b64url_encode(signature)

        return f"{header_b64}.{payload_b64}.{sig_b64}"

    def verify_access_token(self, token: str) -> TokenPayload:
        """Verify JWT signature, algorithm, issuer, and expiration.

        Returns:
            Validated TokenPayload.
        Raises:
            TokenExpiredError: If token expired beyond clock skew.
            TokenInvalidError: If token format, algorithm, or signature is invalid.
        """
        if not token or not isinstance(token, str):
            raise TokenInvalidError("Missing or invalid token format.")

        parts = token.strip().split(".")
        if len(parts) != 3:
            raise TokenInvalidError("Malformed JWT structure. Exactly three segments required.")

        header_b64, payload_b64, sig_b64 = parts

        try:
            header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
            payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
            signature = _b64url_decode(sig_b64)
        except Exception as ex:
            raise TokenInvalidError(f"Failed to decode token segments: {ex}") from ex

        # 1. Algorithm enforcement: strictly HS256, reject none or unsupported
        alg = header.get("alg")
        if alg != TOKEN_ALGORITHM:
            raise TokenInvalidError(f"Unsupported algorithm '{alg}'. Only {TOKEN_ALGORITHM} is permitted.")

        # 2. Cryptographic signature check (constant-time)
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(self._signing_key, signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_sig):
            raise TokenInvalidError("Invalid token signature.")

        # 3. Issuer check
        if payload.get("iss") != TOKEN_ISSUER:
            raise TokenInvalidError(f"Invalid issuer: {payload.get('iss')!r}")

        # 4. Audience check
        if payload.get("aud") != TOKEN_AUDIENCE:
            raise TokenInvalidError(f"Invalid audience: {payload.get('aud')!r}")

        # 5. Subject check
        sub = payload.get("sub")
        if not sub:
            raise TokenInvalidError("Token missing required 'sub' subject claim.")

        # 6. Expiration check with bounded clock skew
        exp = payload.get("exp")
        if exp is None or not isinstance(exp, (int, float)):
            raise TokenInvalidError("Token missing or invalid 'exp' expiration claim.")

        now = int(time.time())
        if now > (exp + self.clock_skew_seconds):
            raise TokenExpiredError("Token has expired.")

        return TokenPayload(
            sub=str(sub),
            email=str(payload.get("email", "")),
            session_id=str(payload.get("session_id", "")),
            exp=int(exp),
            iat=int(payload.get("iat", 0)),
            jti=str(payload.get("jti", "")),
            iss=str(payload.get("iss", TOKEN_ISSUER)),
            aud=str(payload.get("aud", TOKEN_AUDIENCE)),
        )

    decode_access_token = verify_access_token

    def __repr__(self) -> str:
        return f"<TokenService issuer={TOKEN_ISSUER} algorithm={TOKEN_ALGORITHM}>"
