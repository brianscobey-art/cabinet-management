from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, role: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError on invalid/expired tokens."""
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


INVITE_PURPOSE = "invite"


def create_invite_token(email: str) -> str:
    """A short-lived, single-purpose token emailed in the set-password link."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.invite_expire_hours)
    payload = {"sub": email, "purpose": INVITE_PURPOSE, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_invite_token(token: str) -> str:
    """Returns the email from a valid invite token; raises jwt.PyJWTError otherwise."""
    settings = get_settings()
    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    if payload.get("purpose") != INVITE_PURPOSE:
        raise jwt.InvalidTokenError("not an invite token")
    return payload["sub"]
