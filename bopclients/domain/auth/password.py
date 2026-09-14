"""Secure password hashing abstraction utilizing Argon2id with constant-time verification."""

import base64
import hashlib
import hmac
import logging
import os
import secrets
from typing import Optional

logger = logging.getLogger("bopclients.auth.password")

try:
    from argon2 import PasswordHasher as _Argon2PasswordHasher
    from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

    _HAS_ARGON2 = True
    try:
        _DUMMY_ARGON2_HASH = _Argon2PasswordHasher(time_cost=2, memory_cost=32768, parallelism=2).hash("dummy_password")
    except Exception:
        _DUMMY_ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQxMjM0NTY3OA$q1+0mZ/w961VqR8j55XhW5R5vG+l+j7VqgL8rF9q1vY"
except ImportError:  # pragma: no cover
    _HAS_ARGON2 = False
    _Argon2PasswordHasher = None
    _DUMMY_ARGON2_HASH = "$scrypt$ln=14,r=8,p=1$c29tZXNhbHQxMjM0NTY3OA==$c29tZWhhc2gxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMzQ="


class PasswordHasher:
    """Production password hasher providing adaptive Argon2id hashing and fallback."""

    def __init__(
        self,
        time_cost: int = 3,
        memory_cost: int = 65536,
        parallelism: int = 4,
        hash_len: int = 32,
        salt_len: int = 16,
        preferred_algorithm: str = "argon2id",
    ):
        self.time_cost = time_cost
        self.memory_cost = memory_cost
        self.parallelism = parallelism
        self.hash_len = hash_len
        self.salt_len = salt_len
        self.preferred_algorithm = preferred_algorithm.lower()

        if _HAS_ARGON2:
            self._argon2_hasher = _Argon2PasswordHasher(
                time_cost=self.time_cost,
                memory_cost=self.memory_cost,
                parallelism=self.parallelism,
                hash_len=self.hash_len,
                salt_len=self.salt_len,
            )
        else:
            self._argon2_hasher = None

        self._hasher = self._argon2_hasher if self.preferred_algorithm == "argon2id" else None

    def hash(self, password: str) -> str:
        """Generate a secure, salted, adaptive password hash."""
        if not password or not isinstance(password, str):
            raise ValueError("Password must be a non-empty string")

        if self._hasher is not None:
            return self._hasher.hash(password)

        # Secure fallback using standard library scrypt
        salt = secrets.token_bytes(self.salt_len)
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=16384,
            r=8,
            p=1,
            maxmem=64 * 1024 * 1024,
            dklen=self.hash_len,
        )
        salt_b64 = base64.b64encode(salt).decode("ascii")
        hash_b64 = base64.b64encode(derived).decode("ascii")
        return f"$scrypt$ln=14,r=8,p=1${salt_b64}${hash_b64}"

    def verify(self, password: str, password_hash: Optional[str]) -> bool:
        """Verify password against stored hash in constant time."""
        if not password or not password_hash:
            return False

        if password_hash.startswith("$argon2"):
            hasher_to_use = self._argon2_hasher or self._hasher
            if hasher_to_use is not None:
                try:
                    return hasher_to_use.verify(password_hash, password)
                except (VerifyMismatchError, VerificationError, InvalidHashError):
                    return False
                except Exception as ex:
                    logger.warning(f"Unexpected error during Argon2 verification: {type(ex).__name__}")
                    return False
            else:
                logger.error("Argon2 hash encountered but argon2-cffi is not installed")
                return False

        if password_hash.startswith("$scrypt$"):
            try:
                parts = password_hash.split("$")
                # format: "", "scrypt", "ln=14,r=8,p=1", salt, hash
                if len(parts) != 5:
                    return False
                salt = base64.b64decode(parts[3])
                expected_hash = base64.b64decode(parts[4])
                candidate = hashlib.scrypt(
                    password.encode("utf-8"),
                    salt=salt,
                    n=16384,
                    r=8,
                    p=1,
                    maxmem=64 * 1024 * 1024,
                    dklen=len(expected_hash),
                )
                return hmac.compare_digest(candidate, expected_hash)
            except Exception:
                return False

        return False

    def dummy_verify(self) -> None:
        """Run constant-time dummy verification for timing attack mitigation."""
        self.verify("dummy_password", _DUMMY_ARGON2_HASH)

    # Convenience aliases
    verify_password = verify
    hash_password = hash

    def __repr__(self) -> str:
        algo = "Argon2id" if _HAS_ARGON2 else "scrypt"
        return f"<PasswordHasher algorithm={algo}>"
