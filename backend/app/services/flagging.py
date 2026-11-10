"""Flagging accounts as fraud, then letting the risk spread (F6, F7)."""

from neo4j import AsyncDriver

from app.models.graph import AlertType
from app.models.settings import RuntimeSettings
from app.services.alerting import AlertService, severity_for_risk
from app.services.propagation import run_propagation

# Manual flag: FLAGGED_BY points straight at the analyst who raised it.
FLAG_BY_ANALYST = """
MATCH (a:Account {id: $id})
MATCH (an:Analyst {username: $username})
SET a.is_flagged = true, a.risk_score = 1.0, a.combined_risk = 1.0, a.pre_emptive = false
MERGE (a)-[f:FLAGGED_BY]->(an)
SET f.reason = $reason, f.at = datetime(), f.confidence = $confidence
RETURN a.id AS id
"""

# Automated flag (ring confirmation): one FraudFlag node records the event.
FLAG_BY_RING = """
MATCH (g:Ring {ring_id: $ring_id})<-[:MEMBER_OF]-(a:Account)
SET a.is_flagged = true, a.risk_score = 1.0, a.combined_risk = 1.0, a.pre_emptive = false
CREATE (f:FraudFlag {id: randomUUID(), source: 'RING', reason: $reason, confidence: 0.9, created_at: datetime()})
MERGE (a)-[r:FLAGGED_BY]->(f)
SET r.reason = $reason, r.at = datetime(), r.confidence = 0.9
RETURN collect(a.id) AS ids
"""


async def propagate_and_alert(driver: AsyncDriver, settings: RuntimeSettings, alerts: AlertService) -> dict:
    summary = await run_propagation(driver, settings)
    for item in summary["pre_emptive"]:
        await alerts.raise_alert(
            AlertType.PROPAGATED_RISK,
            severity_for_risk(item["risk"]),
            f"Pre-emptive detection: propagated risk {item['risk']:.2f} with no rule triggered. "
            + " | ".join(item["explanation"][:2]),
            "Account",
            item["id"],
        )
    return summary
