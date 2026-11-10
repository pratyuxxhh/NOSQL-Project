"""Ring detection on demand and ring management (F5, F6)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import Services, get_services
from app.db.serialize import GraphBuilder, jsonable, props
from app.models.graph import RingAlgorithm, RingStatus, Role
from app.security.audit import audit
from app.security.rbac import CurrentUser, require_role
from app.services.flagging import FLAG_BY_RING, propagate_and_alert
from app.services.ring_detection import detect_rings

router = APIRouter(prefix="/rings", tags=["rings"])

# Allowed status changes. Decided rings are final.
TRANSITIONS = {
    RingStatus.NEW: {RingStatus.UNDER_REVIEW, RingStatus.CONFIRMED_FRAUD, RingStatus.FALSE_POSITIVE},
    RingStatus.UNDER_REVIEW: {RingStatus.CONFIRMED_FRAUD, RingStatus.FALSE_POSITIVE},
    RingStatus.CONFIRMED_FRAUD: set(),
    RingStatus.FALSE_POSITIVE: set(),
}

LIST = """
MATCH (g:Ring)
WHERE ($status IS NULL OR g.status = $status)
  AND g.size >= $min_size AND coalesce(g.avg_risk, 0) >= $min_risk
WITH g ORDER BY g.flagged_members DESC, g.density DESC, g.size DESC
WITH collect(g) AS rings
RETURN size(rings) AS total, [r IN rings[$skip..$skip + $limit] | r] AS page
"""

DETAIL = """
MATCH (g:Ring {ring_id: $id})
OPTIONAL MATCH (a:Account)-[:MEMBER_OF]->(g)
WITH g, collect(a) AS members
CALL {
  WITH members
  UNWIND members AS a
  OPTIONAL MATCH (a)-[r:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE|TRANSACTED_WITH]->(b:Account)
  WHERE b IN members
  RETURN collect(DISTINCT r) AS links
}
CALL {
  WITH members
  UNWIND members AS a
  OPTIONAL MATCH (a)-[r:USES_DEVICE|USES_CARD]->(x)
  RETURN collect(DISTINCT r) AS attr_rels
}
CALL {
  WITH members
  UNWIND members AS a
  MATCH (a)<-[o:OWNS]-(u:User)
  OPTIONAL MATCH (u)-[r:LIVES_AT|HAS_PHONE]->(y)
  RETURN collect(DISTINCT o) AS owns, collect(DISTINCT r) AS user_rels
}
RETURN g, members, links, attr_rels, owns, user_rels
"""


class StatusIn(BaseModel):
    status: RingStatus
    note: str = Field(default="", max_length=500)


@router.post("/detect")
async def detect(
    algorithm: RingAlgorithm = RingAlgorithm.LOUVAIN,
    user: CurrentUser = Depends(require_role(Role.ANALYST)),
    s: Services = Depends(get_services),
):
    async with s.ingestion.lock:
        summary = await detect_rings(s.driver, s.settings, s.alerts, algorithm)
    s.metrics.last_detection = summary
    await audit(s.driver, user, "RUN_DETECTION", algorithm.value, summary)
    return summary


@router.get("", dependencies=[Depends(require_role(Role.VIEWER))])
async def list_rings(
    status: RingStatus | None = None,
    min_size: int = Query(0, ge=0),
    min_risk: float = Query(0, ge=0, le=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    s: Services = Depends(get_services),
):
    records, _, _ = await s.driver.execute_query(
        LIST, status=status.value if status else None, min_size=min_size, min_risk=min_risk,
        skip=(page - 1) * page_size, limit=page_size,
    )
    return {"total": records[0]["total"], "page": page, "page_size": page_size,
            "items": [props(r) for r in records[0]["page"]]}


def _shared_only(rels: list, members: set[str]) -> list:
    """Keep attribute links whose attribute is used by 2+ ring members."""
    users_by_attr: dict[str, set[str]] = {}
    for r in rels:
        users_by_attr.setdefault(r.end_node.element_id, set()).add(r.start_node.element_id)
    return [r for r in rels if len(users_by_attr[r.end_node.element_id]) >= 2]


@router.get("/{ring_id}", dependencies=[Depends(require_role(Role.VIEWER))])
async def get_ring(ring_id: str, s: Services = Depends(get_services)):
    records, _, _ = await s.driver.execute_query(DETAIL, id=ring_id)
    if not records:
        raise HTTPException(404, "Ring not found")
    r = records[0]
    member_ids = {m.element_id for m in r["members"]}
    graph = GraphBuilder()
    graph.add(r["members"])
    graph.add(r["links"])
    graph.add(_shared_only(r["attr_rels"], member_ids))
    shared_user_rels = _shared_only(r["user_rels"], member_ids)
    users_needed = {rel.start_node.element_id for rel in shared_user_rels}
    graph.add([o for o in r["owns"] if o.start_node.element_id in users_needed])
    graph.add(shared_user_rels)
    return {
        "ring": props(r["g"]),
        "members": sorted((props(m) for m in r["members"]), key=lambda m: -(m.get("hub_score") or 0)),
        "graph": graph.result(),
    }


@router.patch("/{ring_id}/status")
async def set_status(
    ring_id: str,
    body: StatusIn,
    user: CurrentUser = Depends(require_role(Role.ANALYST)),
    s: Services = Depends(get_services),
):
    records, _, _ = await s.driver.execute_query(
        "MATCH (g:Ring {ring_id: $id}) RETURN g.status AS status", id=ring_id
    )
    if not records:
        raise HTTPException(404, "Ring not found")
    current = RingStatus(records[0]["status"])
    if body.status not in TRANSITIONS[current]:
        raise HTTPException(409, f"Cannot move a ring from {current.value} to {body.status.value}")
    await s.driver.execute_query(
        "MATCH (g:Ring {ring_id: $id}) SET g.status = $status, g.reviewed_by = $user, "
        "g.reviewed_at = datetime(), g.review_note = $note",
        id=ring_id, status=body.status.value, user=user.username, note=body.note,
    )
    result: dict = {"ring_id": ring_id, "status": body.status.value}
    if body.status == RingStatus.CONFIRMED_FRAUD:
        # Confirming flags every member and lets their risk spread.
        async with s.ingestion.lock:
            flagged, _, _ = await s.driver.execute_query(
                FLAG_BY_RING, ring_id=ring_id, reason=f"Member of confirmed ring {ring_id}"
            )
            summary = await propagate_and_alert(s.driver, s.settings, s.alerts)
        s.metrics.last_propagation = summary
        result["flagged"] = flagged[0]["ids"]
        result["propagation"] = jsonable(summary)
    await audit(s.driver, user, "RING_STATUS", ring_id, {"from": current.value, "to": body.status.value, "note": body.note})
    await s.hub.broadcast("ring", result)
    return result
