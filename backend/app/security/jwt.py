"""JWT access and refresh tokens (HS256).

Access tokens are short-lived (default 15 min) and sent on every request.
Refresh tokens (default 7 days) can only be exchanged for a new access token.
The `type` claim stops one being used as the other.
"""

from datetime import datetime, timedelta, timezone

import jwt

from app.config import Settings

ALGORITHM = "HS256"


class TokenError(Exception):
    pass


def create_token(subject: str, role: str, kind: str, settings: Settings) -> str:
    lifetime = (
        timedelta(minutes=settings.access_token_minutes)
        if kind == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "role": role, "type": kind, "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str, expected_kind: str, settings: Settings) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc
    if payload.get("type") != expected_kind:
        raise TokenError(f"expected a {expected_kind} token")
    return payload
