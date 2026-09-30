from __future__ import annotations

import hashlib
import hmac
import secrets


def new_id(prefix: str) -> str:
    """128-bit random, URL-safe identifier."""
    return f"{prefix}_{secrets.token_urlsafe(16)}"


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_matches(token: str | None, token_hash: str) -> bool:
    if not token:
        return False
    return hmac.compare_digest(hash_token(token), token_hash)


def sign(secret: str, *parts: str) -> str:
    msg = "\x1f".join(parts).encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def verify_signature(secret: str, signature: str, *parts: str) -> bool:
    return hmac.compare_digest(sign(secret, *parts), signature)
