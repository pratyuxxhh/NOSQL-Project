"""Login, token refresh, current user (F12)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.deps import Services, get_services
from app.config import get_settings
from app.models.graph import Role
from app.security.audit import audit
from app.security.jwt import TokenError, create_token, decode_token
from app.security.passwords import verify_password
from app.security.rate_limit import limiter
from app.security.rbac import CurrentUser, current_user

router = APIRouter(prefix="/auth", tags=["auth"])

USER_QUERY = """
MATCH (u:Analyst {username: $username})
RETURN u.username AS username, u.name AS name, u.role AS role,
       u.password_hash AS password_hash, coalesce(u.active, true) AS active
"""


class LoginIn(BaseModel):
    username: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


def _tokens(username: str, role: str) -> dict:
    settings = get_settings()
    return {
        "access_token": create_token(username, role, "access", settings),
        "refresh_token": create_token(username, role, "refresh", settings),
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
    }


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginIn, s: Services = Depends(get_services)) -> dict:
    records, _, _ = await s.driver.execute_query(USER_QUERY, username=body.username)
    user = records[0] if records else None
    # Same message whether the user is unknown or the password is wrong.
    if not user or not user["active"] or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    await audit(s.driver, body.username, "LOGIN", body.username)
    return {**_tokens(user["username"], user["role"]),
            "user": {"username": user["username"], "name": user["name"], "role": user["role"]}}


@router.post("/refresh")
@limiter.limit("30/minute")
async def refresh(request: Request, body: RefreshIn, s: Services = Depends(get_services)) -> dict:
    try:
        payload = decode_token(body.refresh_token, "refresh", get_settings())
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    records, _, _ = await s.driver.execute_query(USER_QUERY, username=payload["sub"])
    if not records or not records[0]["active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User disabled")
    # Use the CURRENT role, so a role change takes effect at the next refresh.
    return _tokens(payload["sub"], records[0]["role"])


@router.get("/me")
async def me(user: CurrentUser = Depends(current_user)) -> dict:
    return {"username": user.username, "role": user.role.value,
            "is_admin": user.role == Role.ADMIN}
