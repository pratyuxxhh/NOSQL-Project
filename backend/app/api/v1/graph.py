"""Multi-hop graph queries (F4)."""

from fastapi import APIRouter, Depends, Query

from app.api.deps import Services, get_services
from app.models.graph import Role
from app.security.rbac import require_role
from app.services import graph_queries

router = APIRouter(prefix="/graph", tags=["graph"], dependencies=[Depends(require_role(Role.VIEWER))])


@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=100), s: Services = Depends(get_services)):
    return await graph_queries.search(s.driver, q)


@router.get("/neighbourhood/{key}")
async def neighbourhood(
    key: str,
    label: str = "Account",
    depth: int = Query(2, ge=1, le=6),
    types: list[str] | None = Query(None, description="relationship types to follow"),
    limit: int = Query(300, ge=10, le=1000),
    s: Services = Depends(get_services),
):
    """Every node within `depth` hops of the node (default: an Account by id)."""
    return await graph_queries.neighbourhood(s.driver, label, key, depth, types, limit)


@router.get("/shortest-path")
async def shortest_path(
    source: str = Query(alias="from"),
    target: str = Query(alias="to"),
    all: bool = False,
    s: Services = Depends(get_services),
):
    """How two accounts are linked, e.g. A1 -[USES_DEVICE]- Device D1 -[USES_DEVICE]- A2."""
    return await graph_queries.shortest_path(s.driver, source, target, all)


@router.get("/shared/{account_id}")
async def shared(account_id: str, min_shared: int = Query(1, ge=1, le=20), s: Services = Depends(get_services)):
    """Accounts sharing at least `min_shared` devices/cards/addresses/phones with this one."""
    return await graph_queries.shared_attributes(s.driver, account_id, min_shared)


@router.get("/linked-to-fraud/{account_id}")
async def linked_to_fraud(account_id: str, depth: int = Query(3, ge=1, le=6), s: Services = Depends(get_services)):
    """Is the account within `depth` hops of a flagged account? Returns the closest paths."""
    return await graph_queries.linked_to_fraud(s.driver, account_id, depth)
