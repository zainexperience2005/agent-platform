import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from passlib.context import CryptContext

from agent_platform.apps.api.core.config import settings

# Passlib compatibility shim for bcrypt >= 4.0
if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = type("about", (), {"__version__": getattr(bcrypt, "__version__", "4.0.0")})()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(user_id: str, tenant_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def generate_api_key() -> tuple[str, str, str]:
    """Returns (raw_key, key_hash, key_prefix). The raw key is shown once, never stored."""
    raw = "ak_" + secrets.token_urlsafe(32)
    return raw, hash_token(raw), raw[:12]
