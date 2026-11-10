"""Role-based access control. Roles are ordered: ADMIN > ANALYST > VIEWER, so an
endpoint that needs ANALYST also admits ADMIN."""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.models.graph import Role
from app.security.jwt import TokenError, decode_token

RANK = {Role.VIEWER: 1, Role.ANALYST: 2, Role.ADMIN: 3}
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    username: str
    role: Role


def has_role(user_role: Role, required: Role) -> bool:
    return RANK[user_role] >= RANK[required]


async def current_user(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(credentials.credentials, "access", get_settings())
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc),
                            headers={"WWW-Authenticate": "Bearer"}) from exc
    return CurrentUser(username=payload["sub"], role=Role(payload["role"]))


def require_role(role: Role):
    """FastAPI dependency: the caller must be logged in with at least `role`."""

    async def check(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if not has_role(user.role, role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{role.value} role required")
        return user

    return check
