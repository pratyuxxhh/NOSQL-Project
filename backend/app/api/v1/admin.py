"""Administration (ADMIN only): users and roles, API keys, runtime settings,
audit log (F9 Admin and Audit pages, F12)."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import Services, get_services
from app.db.serialize import props
from app.models.graph import Role
from app.models.settings import RuntimeSettings
from app.security.api_keys import create_api_key
from app.security.audit import audit
from app.security.passwords import hash_password
from app.security.rbac import CurrentUser, require_role

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require_role(Role.ADMIN)


class UserIn(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9._-]{3,32}$")
    name: str = Field(min_length=1, max_length=80)
    role: Role
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    role: Role | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    rate_limit_per_min: int = Field(default=6000, ge=1, le=100_000)


@router.get("/users")
async def list_users(_: CurrentUser = Depends(admin_only), s: Services = Depends(get_services)):
    records, _, _ = await s.driver.execute_query(
        "MATCH (u:Analyst) WHERE u.role IS NOT NULL RETURN u ORDER BY u.username"
    )
    return [props(r["u"]) for r in records]


@router.post("/users", status_code=201)
async def create_user(body: UserIn, user: CurrentUser = Depends(admin_only), s: Services = Depends(get_services)):
    existing, _, _ = await s.driver.execute_query(
        "MATCH (u:Analyst {username: $u}) RETURN u", u=body.username
    )
    if existing:
        raise HTTPException(409, "Username already exists")
    await s.driver.execute_query(
        "CREATE (u:Analyst {id: randomUUID(), username: $username, name: $name, role: $role, "
        "active: true, password_hash: $hash, created_at: datetime()})",
        username=body.username, name=body.name, role=body.role.value, hash=hash_password(body.password),
    )
    await audit(s.driver, user, "CREATE_USER", body.username, {"role": body.role.value})
    return {"username": body.username, "role": body.role.value}


@router.patch("/users/{username}")
async def update_user(
    username: str, body: UserUpdate, user: CurrentUser = Depends(admin_only), s: Services = Depends(get_services)
):
    if username == user.username and (body.role not in (None, Role.ADMIN) or body.active is False):
        raise HTTPException(400, "You cannot demote or disable yourself")
    records, _, _ = await s.driver.execute_query(
        "MATCH (u:Analyst {username: $username}) "
        "SET u.role = coalesce($role, u.role), u.active = coalesce($active, u.active), "
        "u.password_hash = coalesce($hash, u.password_hash) RETURN u",
        username=username,
        role=body.role.value if body.role else None,
        active=body.active,
        hash=hash_password(body.password) if body.password else None,
    )
    if not records:
        raise HTTPException(404, "User not found")
    await audit(s.driver, user, "UPDATE_USER", username,
                body.model_dump(exclude_none=True, exclude={"password"}))
    return props(records[0]["u"])


@router.get("/api-keys")
async def list_keys(_: CurrentUser = Depends(admin_only), s: Services = Depends(get_services)):
    records, _, _ = await s.driver.execute_query("MATCH (k:ApiKey) RETURN k ORDER BY k.created_at DESC")
    return [props(r["k"]) for r in records]


@router.post("/api-keys", status_code=201)
async def new_key(body: ApiKeyIn, user: CurrentUser = Depends(admin_only), s: Services = Depends(get_services)):
    created = await create_api_key(s.driver, body.name, body.rate_limit_per_min)
    await audit(s.driver, user, "CREATE_API_KEY", body.name)
    return created  # the only time the full key is returned


@router.delete("/api-keys/{key_id}")
async def revoke_key(key_id: str, user: CurrentUser = Depends(admin_only), s: Services = Depends(get_services)):
    records, _, _ = await s.driver.execute_query(
        "MATCH (k:ApiKey {id: $id}) SET k.active = false, k.revoked_at = datetime() RETURN k.name AS name",
        id=key_id,
    )
    if not records:
        raise HTTPException(404, "API key not found")
    await audit(s.driver, user, "REVOKE_API_KEY", records[0]["name"])
    return {"revoked": key_id}


@router.get("/settings")
async def get_runtime_settings(_: CurrentUser = Depends(admin_only), s: Services = Depends(get_services)):
    return s.settings


@router.put("/settings")
async def put_runtime_settings(
    body: RuntimeSettings, user: CurrentUser = Depends(admin_only), s: Services = Depends(get_services)
):
    before = s.settings.model_dump()
    saved = await s.settings_store.save(body)
    changed = {k: v for k, v in saved.model_dump().items() if before.get(k) != v}
    await audit(s.driver, user, "UPDATE_SETTINGS", "runtime", changed)
    return saved


@router.get("/audit")
async def audit_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: str | None = None,
    action: str | None = None,
    _: CurrentUser = Depends(admin_only),
    s: Services = Depends(get_services),
):
    records, _, _ = await s.driver.execute_query(
        """
        MATCH (l:AuditLog)
        WHERE ($actor IS NULL OR l.actor = $actor) AND ($action IS NULL OR l.action = $action)
        WITH l ORDER BY l.at DESC
        WITH collect(l) AS rows
        RETURN size(rows) AS total, rows[$skip..$skip + $limit] AS page
        """,
        actor=actor, action=action, skip=(page - 1) * page_size, limit=page_size,
    )
    items = []
    for row in records[0]["page"]:
        item = props(row)
        item["details"] = json.loads(item.get("details") or "{}")
        items.append(item)
    return {"total": records[0]["total"], "items": items}
