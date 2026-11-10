"""Manual flagging and risk propagation (F7)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import Services, get_services
from app.db.serialize import GraphBuilder, jsonable, props
from app.models.graph import Role
from app.security.audit import audit
from app.security.rbac import CurrentUser, require_role
from app.services.flagging import FLAG_BY_ANALYST, propagate_and_alert
from app.services.propagation import PROPAGATING_TYPES

router = APIRouter(prefix="/risk", tags=["risk"])


class FlagIn(BaseModel):
    reason: str = Field(default="Flagged by analyst", max_length=300)
    confidence: float = Field(default=0.9, ge=0, le=1)


@router.post("/propagate/{node_id}")
async def propagate(
    node_id: str,
    body: FlagIn | None = None,
    user: CurrentUser = Depends(require_role(Role.ANALYST)),
    s: Services = Depends(get_services),
):
    """Flag an account (if not already) and spread its risk through the graph."""
    body = body or FlagIn()
    async with s.ingestion.lock:
        flagged, _, _ = await s.driver.execute_query(
            FLAG_BY_ANALYST, id=node_id, username=user.username, reason=body.reason, confidence=body.confidence
        )
        if not flagged:
            raise HTTPException(404, "Account not found (or analyst user missing)")
        summary = await propagate_and_alert(s.driver, s.settings, s.alerts)
    s.metrics.last_propagation = summary
    await audit(s.driver, user, "FLAG_ACCOUNT", node_id, {"reason": body.reason})
    return {"flagged": node_id, **jsonable(summary)}


@router.post("/recompute", dependencies=[Depends(require_role(Role.ANALYST))])
async def recompute(s: Services = Depends(get_services)):
    async with s.ingestion.lock:
        summary = await propagate_and_alert(s.driver, s.settings, s.alerts)
    s.metrics.last_propagation = summary
    return jsonable(summary)


@router.get("/accounts", dependencies=[Depends(require_role(Role.VIEWER))])
async def risky_accounts(
    min_risk: float = Query(0.3, ge=0, le=1),
    pre_emptive: bool = False,
    limit: int = Query(100, ge=1, le=500),
    s: Services = Depends(get_services),
):
    records, _, _ = await s.driver.execute_query(
        """
        MATCH (a:Account)
        WHERE coalesce(a.combined_risk, 0) >= $min_risk AND (NOT $pre_emptive OR a.pre_emptive)
        RETURN a ORDER BY a.combined_risk DESC, a.id LIMIT $limit
        """,
        min_risk=min_risk, pre_emptive=pre_emptive, limit=limit,
    )
    return [props(r["a"]) for r in records]


@router.get("/spread/{account_id}", dependencies=[Depends(require_role(Role.VIEWER))])
async def spread(account_id: str, s: Services = Depends(get_services)):
    """How risk spread FROM this (flagged) account: the accounts it reached, by hop,
    with their scores and the explanation paths that start at this account."""
    depth = s.settings.propagation.max_depth
    records, _, _ = await s.driver.execute_query(
        f"""
        MATCH (src:Account {{id: $id}})
        CALL apoc.path.subgraphAll(src, {{maxLevel: {int(depth)},
             relationshipFilter: $types, labelFilter: '+Account'}})
        YIELD nodes, relationships
        RETURN src, nodes, relationships
        """,
        id=account_id, types="|".join(PROPAGATING_TYPES),
    )
    if not records:
        raise HTTPException(404, "Account not found")
    r = records[0]
    graph = GraphBuilder()
    graph.add(r["src"])
    graph.add(r["nodes"])
    graph.add(r["relationships"])
    affected = []
    for n in r["nodes"]:
        explanation = [e for e in (n.get("risk_explanation") or []) if e.startswith(account_id + " ")]
        if n["id"] != account_id and explanation:
            affected.append({
                "id": n["id"],
                "propagated_risk": n.get("propagated_risk", 0),
                "combined_risk": n.get("combined_risk", 0),
                "pre_emptive": n.get("pre_emptive", False),
                "hops": explanation[0].count(" -"),
                "explanation": explanation,
            })
    affected.sort(key=lambda a: (a["hops"], -a["propagated_risk"]))
    return {"source": props(r["src"]), "affected": affected, "graph": graph.result()}
