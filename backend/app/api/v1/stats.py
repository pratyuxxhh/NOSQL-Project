"""Dashboard data: overview KPIs, rule-vs-graph comparison, evaluation,
benchmark and operational metrics (F9, F10, F11, F14)."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends

from app.api.deps import Services, get_services
from app.config import get_settings
from app.db.serialize import jsonable
from app.models.graph import Role
from app.security.rbac import require_role

router = APIRouter(prefix="/stats", tags=["stats"], dependencies=[Depends(require_role(Role.VIEWER))])

OVERVIEW = """
CALL { MATCH (t:Transaction) WHERE t.timestamp >= datetime() - duration('P1D') RETURN count(t) AS tx_24h }
CALL { MATCH (t:Transaction) RETURN count(t) AS tx_total }
CALL { MATCH (al:Alert) WHERE al.status <> 'RESOLVED' RETURN count(al) AS open_alerts }
CALL { MATCH (g:Ring) WHERE g.status IN ['NEW', 'UNDER_REVIEW', 'CONFIRMED_FRAUD'] RETURN count(g) AS active_rings }
CALL { MATCH (a:Account) WHERE a.combined_risk >= 0.5 RETURN count(a) AS accounts_at_risk }
CALL { MATCH (a:Account {pre_emptive: true}) RETURN count(a) AS pre_emptive }
CALL { MATCH (a:Account {is_flagged: true}) RETURN count(a) AS flagged }
RETURN tx_24h, tx_total, open_alerts, active_rings, accounts_at_risk, pre_emptive, flagged
"""
ALERTS_BY_DAY = """
MATCH (al:Alert) WHERE al.created_at >= datetime() - duration('P14D')
RETURN toString(date(al.created_at)) AS day, al.type AS type, count(*) AS n ORDER BY day
"""
RISK_DISTRIBUTION = """
MATCH (a:Account) WHERE coalesce(a.combined_risk, 0) > 0
WITH toInteger(floor(a.combined_risk * 10)) AS bucket, count(*) AS n
RETURN CASE WHEN bucket > 9 THEN 9 ELSE bucket END AS bucket, sum(n) AS n ORDER BY bucket
"""
RECENT_TX = """
MATCH (a:Account)-[:INITIATED]->(t:Transaction)
RETURN t.id AS id, a.id AS account_id, t.amount AS amount, t.channel AS channel, t.location AS location,
       t.timestamp AS timestamp, t.rule_score AS rule_score, t.final_score AS final_score, t.decision AS decision
ORDER BY t.timestamp DESC LIMIT 25
"""

# Which accounts each approach catches (flagged accounts are already known, so excluded).
COMPARISON = """
CALL {
  MATCH (a:Account)-[:INITIATED]->(t:Transaction)
  WHERE t.rule_score >= $flag_threshold AND NOT coalesce(a.is_flagged, false)
  RETURN collect(DISTINCT a.id) AS by_rules
}
CALL {
  MATCH (a:Account)
  WHERE NOT coalesce(a.is_flagged, false)
    AND (coalesce(a.propagated_risk, 0) >= $surface
         OR EXISTS { (a)-[:MEMBER_OF]->(g:Ring) WHERE g.status <> 'FALSE_POSITIVE' })
  RETURN collect(a.id) AS by_graph
}
RETURN by_rules, by_graph
"""


def _read_json(name: str) -> dict | None:
    path = Path(get_settings().data_dir) / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@router.get("/overview")
async def overview(s: Services = Depends(get_services)):
    kpis, _, _ = await s.driver.execute_query(OVERVIEW)
    by_day, _, _ = await s.driver.execute_query(ALERTS_BY_DAY)
    dist, _, _ = await s.driver.execute_query(RISK_DISTRIBUTION)
    recent, _, _ = await s.driver.execute_query(RECENT_TX)
    days: dict[str, dict] = {}
    for r in by_day:
        days.setdefault(r["day"], {"day": r["day"]})[r["type"]] = r["n"]
    buckets = {r["bucket"]: r["n"] for r in dist}
    return {
        "kpis": dict(kpis[0]),
        "alerts_by_day": list(days.values()),
        "risk_distribution": [
            {"range": f"{b / 10:.1f}-{(b + 1) / 10:.1f}", "accounts": buckets.get(b, 0)} for b in range(10)
        ],
        "recent_transactions": [jsonable(dict(r)) for r in recent],
        "metrics": s.metrics.snapshot(),
    }


@router.get("/comparison")
async def comparison(s: Services = Depends(get_services)):
    records, _, _ = await s.driver.execute_query(
        COMPARISON,
        flag_threshold=s.settings.rules.flag_threshold,
        surface=s.settings.propagation.surface_threshold,
    )
    rules, graph = set(records[0]["by_rules"]), set(records[0]["by_graph"])
    truth = _read_json("ground_truth.json")
    fraud = set(truth["fraud_accounts"]) if truth else None

    def group(ids: set[str]) -> dict:
        out = {"count": len(ids), "sample": sorted(ids)[:50]}
        if fraud is not None:
            out["actually_fraud"] = len(ids & fraud)
        return out

    return {
        "rules_only": group(rules - graph),
        "graph_only": group(graph - rules),
        "both": group(rules & graph),
        "evaluation": _read_json("evaluation.json"),
    }


@router.get("/benchmark")
async def benchmark():
    return _read_json("benchmark.json") or {"available": False}


@router.get("/metrics")
async def metrics(s: Services = Depends(get_services)):
    return s.metrics.snapshot()
