"""Password hashing and signed session token helpers."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()
TOKEN_ISSUER = "offerpilot-api"


def hash_password(password: str) -> str:
    """Hash a plaintext password using the recommended Argon2id configuration."""

    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against its Argon2id hash."""

    return password_hash.verify(password, stored_hash)


def create_session_token(user_id: UUID, secret: str, ttl_minutes: int) -> str:
    """Create a signed, short-lived JWT for the HttpOnly session cookie."""

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iss": TOKEN_ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def read_session_token(token: str, secret: str) -> UUID:
    """Validate a session token and return its user id."""

    payload = jwt.decode(token, secret, algorithms=["HS256"], issuer=TOKEN_ISSUER)
    return UUID(payload["sub"])
