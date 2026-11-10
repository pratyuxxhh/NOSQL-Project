"""Alert creation (F8). Alerts are :Alert nodes linked to their subject with ABOUT
and pushed to dashboards over the WebSocket hub."""

from neo4j import AsyncDriver

from app.db.serialize import props
from app.models.graph import AlertType, Severity
from app.websocket.hub import Hub

# Allowed alert subjects: label -> unique key property (whitelist; labels can't be parameters).
SUBJECTS = {"Account": "id", "Transaction": "id", "Ring": "ring_id"}

# Creates the alert only if the subject has no unresolved alert of the same type.
CREATE_ALERT = """
MATCH (e:{label} {{{key}: $entity_id}})
OPTIONAL MATCH (e)<-[:ABOUT]-(x:Alert {{type: $type}}) WHERE x.status <> 'RESOLVED'
WITH e, count(x) AS open WHERE open = 0
CREATE (al:Alert {{id: randomUUID(), type: $type, severity: $severity, explanation: $explanation,
                  created_at: datetime(), status: 'OPEN', notes: [],
                  entity_label: $label, entity_id: $entity_id}})
CREATE (al)-[:ABOUT]->(e)
RETURN al
"""


class AlertService:
    def __init__(self, driver: AsyncDriver, hub: Hub) -> None:
        self.driver = driver
        self.hub = hub

    async def raise_alert(
        self, type: AlertType, severity: Severity, explanation: str, label: str, entity_id: str
    ) -> dict | None:
        key = SUBJECTS[label]
        records, _, _ = await self.driver.execute_query(
            CREATE_ALERT.format(label=label, key=key),
            entity_id=entity_id,
            type=type.value,
            severity=severity.value,
            explanation=explanation,
            label=label,
        )
        if not records:
            return None  # duplicate of an open alert
        alert = props(records[0]["al"])
        await self.hub.broadcast("alert", alert)
        return alert


def severity_for_risk(risk: float) -> Severity:
    if risk >= 0.8:
        return Severity.CRITICAL
    if risk >= 0.6:
        return Severity.HIGH
    if risk >= 0.4:
        return Severity.MEDIUM
    return Severity.LOW
