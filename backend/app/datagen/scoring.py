"""Rule-score a generated dataset in bulk, exactly as live ingestion would score
each transaction, then write the scores to Neo4j."""

from collections import defaultdict, deque
from datetime import timedelta

from neo4j import AsyncDriver

from app.datagen.builder import Dataset
from app.models.graph import RiskTier
from app.models.settings import RuleSettings
from app.services import rules

WRITE_TX_SCORES = """
UNWIND $rows AS r
MATCH (t:Transaction {id: r.id})
SET t.rule_score = r.score, t.rule_reasons = r.reasons, t.final_score = toFloat(r.score)
"""
# Own risk = worst rule score of the account (flagged accounts stay at 1.0).
WRITE_ACCOUNT_RISK = """
UNWIND $rows AS r
MATCH (a:Account {id: r.id})
SET a.risk_score = CASE WHEN a.is_flagged THEN 1.0 ELSE r.risk END,
    a.combined_risk = CASE WHEN a.is_flagged THEN 1.0 ELSE r.risk END,
    a.propagated_risk = 0.0, a.pre_emptive = false, a.risk_explanation = []
"""


def score_dataset(ds: Dataset, settings: RuleSettings) -> tuple[list[dict], dict[str, float]]:
    """Return per-transaction scores and per-account own risk (max rule score / 100)."""
    tiers = {m.id: m.risk_tier for m in ds.merchants}

    window = timedelta(minutes=settings.velocity_window_minutes)
    recent: dict[str, deque] = defaultdict(deque)
    rows, account_risk = [], defaultdict(float)
    for record in sorted(ds.transactions, key=lambda r: r.tx.timestamp):
        tx = record.tx
        times = recent[record.source]
        while times and tx.timestamp - times[0] > window:
            times.popleft()
        times.append(tx.timestamp)
        score, reasons = rules.score(
            rules.RuleContext(
                amount=tx.amount,
                recent_count=len(times),
                new_device=False,  # bulk history has no per-transaction device
                location=tx.location,
                merchant_tier=RiskTier(tiers[record.target]) if record.to_merchant else None,
            ),
            settings,
        )
        rows.append({"id": tx.id, "score": score, "reasons": reasons})
        account_risk[record.source] = max(account_risk[record.source], score / 100)
    return rows, dict(account_risk)


async def write_scores(driver: AsyncDriver, ds: Dataset, settings: RuleSettings, batch: int = 5000) -> dict:
    rows, account_risk = score_dataset(ds, settings)
    for i in range(0, len(rows), batch):
        await driver.execute_query(WRITE_TX_SCORES, rows=rows[i : i + batch])
    risk_rows = [{"id": a.id, "risk": round(account_risk.get(a.id, 0.0), 4)} for a in ds.accounts]
    for i in range(0, len(risk_rows), batch):
        await driver.execute_query(WRITE_ACCOUNT_RISK, rows=risk_rows[i : i + batch])
    flagged = sum(1 for r in rows if r["score"] >= settings.flag_threshold)
    return {"scored": len(rows), "over_threshold": flagged}
