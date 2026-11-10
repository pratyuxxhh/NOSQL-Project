"""Alert listing and workflow: acknowledge, assign, resolve, add notes (F8)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import Services, get_services
from app.db.serialize import props
from app.models.graph import AlertStatus, AlertType, Role, Severity
from app.security.audit import audit
from app.security.rbac import CurrentUser, require_role

router = APIRouter(prefix="/alerts", tags=["alerts"])

LIST = """
MATCH (al:Alert)
WHERE ($status IS NULL OR al.status = $status)
  AND ($type IS NULL OR al.type = $type)
  AND ($severity IS NULL OR al.severity = $severity)
OPTIONAL MATCH (al)-[:ASSIGNED_TO]->(an:Analyst)
WITH al, an.username AS assignee ORDER BY al.created_at DESC
WITH collect({alert: al, assignee: assignee}) AS rows
RETURN size(rows) AS total, rows[$skip..$skip + $limit] AS page
"""


class AlertUpdate(BaseModel):
    status: AlertStatus | None = None
    assignee: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=1000)


@router.get("", dependencies=[Depends(require_role(Role.VIEWER))])
async def list_alerts(
    status: AlertStatus | None = None,
    type: AlertType | None = None,
    severity: Severity | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    s: Services = Depends(get_services),
):
    records, _, _ = await s.driver.execute_query(
        LIST,
        status=status.value if status else None,
        type=type.value if type else None,
        severity=severity.value if severity else None,
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    return {
        "total": records[0]["total"],
        "items": [{**props(row["alert"]), "assignee": row["assignee"]} for row in records[0]["page"]],
    }


@router.patch("/{alert_id}")
async def update_alert(
    alert_id: str,
    body: AlertUpdate,
    user: CurrentUser = Depends(require_role(Role.ANALYST)),
    s: Services = Depends(get_services),
):
    records, _, _ = await s.driver.execute_query(
        """
        MATCH (al:Alert {id: $id})
        SET al.status = coalesce($status, al.status),
            al.notes = CASE WHEN $note IS NULL THEN al.notes
                            ELSE al.notes + [$author + ': ' + $note] END,
            al.updated_at = datetime()
        WITH al
        CALL {
          WITH al
          WITH al WHERE $assignee IS NOT NULL
          OPTIONAL MATCH (al)-[old:ASSIGNED_TO]->() DELETE old
          WITH DISTINCT al
          MATCH (an:Analyst {username: $assignee})
          MERGE (al)-[:ASSIGNED_TO]->(an)
          RETURN count(*) AS assigned
        }
        RETURN al
        """,
        id=alert_id,
        status=body.status.value if body.status else None,
        note=body.note,
        author=user.username,
        assignee=body.assignee,
    )
    if not records:
        raise HTTPException(404, "Alert not found")
    await audit(s.driver, user, "UPDATE_ALERT", alert_id, body.model_dump(exclude_none=True))
    alert = props(records[0]["al"])
    await s.hub.broadcast("alert_updated", alert)
    return alert
