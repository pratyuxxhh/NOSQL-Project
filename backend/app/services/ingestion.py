"""Real-time ingestion pipeline (F2).

For each transaction event:
  1. idempotency check (a known transaction ID returns the stored result)
  2. read rule context (recent activity, known device, home city, merchant tier)
  3. rule scoring (F3)
  4. MERGE every entity and relationship in one write transaction
  5. derive SHARED_* edges for this account
  6. local ring check: is the account linked to known fraud or in a ring? (F5)
  7. if so, re-run risk propagation (F7)
  8. final score + ALLOW / REVIEW / BLOCK decision, alerts and live feed (F8)

Events from the queue and synchronous /score calls run through the same
pipeline under one lock, so the graph sees transactions one at a time.
"""

import asyncio
import logging
import time
from datetime import timedelta
from pathlib import Path

from neo4j import AsyncDriver, AsyncManagedTransaction

from app.db.schema import load_statements
from app.models.events import Decision, ScoreResult, TransactionEvent
from app.models.graph import AlertType, RiskTier, Severity
from app.models.settings import RuntimeSettings
from app.security import pii
from app.services import rules
from app.services.alerting import AlertService
from app.services.flagging import propagate_and_alert
from app.services.metrics import Metrics
from app.websocket.hub import Hub

logger = logging.getLogger(__name__)

DERIVE_FOR_ACCOUNT = load_statements(
    Path(__file__).resolve().parents[1] / "cypher" / "derive_shared_edges_for_account.cypher"
)

EXISTING = """
MATCH (a:Account)-[:INITIATED]->(t:Transaction {id: $id})
RETURN t, a.id AS account_id
"""

CONTEXT = """
OPTIONAL MATCH (a:Account {id: $account_id})
OPTIONAL MATCH (a)-[:USES_DEVICE]->(d:Device {device_id: $device_id})
OPTIONAL MATCH (m:Merchant {id: $merchant_id})
CALL {
  WITH a
  OPTIONAL MATCH (a)-[:INITIATED]->(t:Transaction)
  WHERE t.timestamp >= $since AND t.timestamp <= $ts
  RETURN count(t) AS recent
}
RETURN a IS NOT NULL AS account_exists, d IS NOT NULL AS known_device,
       recent, m.risk_tier AS merchant_tier
"""

MERGE_ACCOUNT = """
MERGE (a:Account {id: $id})
ON CREATE SET a.account_no = $account_no, a.type = $type, a.status = 'ACTIVE',
              a.opened_at = $opened_at, a.risk_score = 0.0, a.propagated_risk = 0.0,
              a.combined_risk = 0.0, a.is_flagged = false, a.risk_explanation = [],
              a.pre_emptive = false
"""
MERGE_USER = """
MATCH (a:Account {id: $account_id})
MERGE (u:User {id: $user.id})
ON CREATE SET u.created_at = datetime()
SET u.name = $user.name, u.email = $user.email, u.phone = $user.phone, u.kyc_status = $user.kyc_status
MERGE (u)-[:OWNS]->(a)
MERGE (ad:Address {normalized_hash: $address.normalized_hash})
ON CREATE SET ad.id = $address.id, ad.line = $address.line, ad.city = $address.city, ad.pincode = $address.pincode
MERGE (u)-[:LIVES_AT]->(ad)
MERGE (p:Phone {number_hash: $phone_hash})
MERGE (u)-[:HAS_PHONE]->(p)
"""
MERGE_DEVICE = """
MATCH (a:Account {id: $account_id})
MERGE (d:Device {device_id: $device.device_id})
ON CREATE SET d.fingerprint = $device.fingerprint, d.os = $device.os
SET d.ip_last_seen = coalesce($device.ip, d.ip_last_seen)
MERGE (a)-[:USES_DEVICE]->(d)
"""
MERGE_CARD = """
MATCH (a:Account {id: $account_id})
MERGE (c:Card {card_hash: $card.card_hash})
ON CREATE SET c.last4 = $card.last4, c.bin = $card.bin, c.issuer = $card.issuer, c.type = $card.type
MERGE (a)-[:USES_CARD]->(c)
"""
# Target label is fixed per query (Merchant or Account).
MERGE_TRANSACTION = """
MATCH (a:Account {{id: $account_id}})
MERGE (dst:{label} {{id: $target_id}})
ON CREATE SET dst += $target_props
MERGE (t:Transaction {{id: $tx.id}})
SET t += $tx
MERGE (a)-[:INITIATED]->(t)
MERGE (t)-[:PAID_TO]->(dst)
MERGE (a)-[w:TRANSACTED_WITH]->(dst)
ON CREATE SET w.count = 0, w.total_amount = 0.0
SET w.count = w.count + 1,
    w.total_amount = w.total_amount + $tx.amount,
    w.last_at = CASE WHEN w.last_at IS NULL OR w.last_at < $tx.timestamp THEN $tx.timestamp ELSE w.last_at END
"""
# Own risk: the worst rule score seen (flagged accounts stay at 1.0). Used for
# account rankings and ring averages, not for the transaction's final score.
UPDATE_OWN_RISK = """
MATCH (a:Account {id: $account_id})
SET a.risk_score = CASE WHEN a.is_flagged THEN 1.0
                        ELSE CASE WHEN coalesce(a.risk_score, 0.0) > $rule_risk THEN a.risk_score ELSE $rule_risk END END
SET a.combined_risk = 1 - (1 - a.risk_score) * (1 - coalesce(a.propagated_risk, 0.0))
"""
LINK_CHECK = """
MATCH (a:Account {id: $account_id})
OPTIONAL MATCH (a)-[:MEMBER_OF]->(g:Ring)
WITH a, collect(g.ring_id) AS rings
CALL {
  WITH a
  OPTIONAL MATCH (a)-[:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE]-(n1:Account)
  OPTIONAL MATCH (n1)-[:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE]-(n2:Account)
  WITH collect(DISTINCT n1) + collect(DISTINCT n2) AS near, a
  RETURN [n IN near WHERE n IS NOT NULL AND n <> a AND n.is_flagged | n.id] AS flagged_near
}
RETURN rings, flagged_near, a.is_flagged AS is_flagged
"""
ACCOUNT_RISK = """
MATCH (a:Account {id: $account_id})
RETURN CASE WHEN a.is_flagged THEN 1.0 ELSE coalesce(a.propagated_risk, 0.0) END AS graph_risk,
       coalesce(a.propagated_risk, 0.0) AS propagated,
       coalesce(a.risk_explanation, []) AS explanation, coalesce(a.pre_emptive, false) AS pre_emptive
"""
SET_FINAL = "MATCH (t:Transaction {id: $id}) SET t.final_score = $final, t.decision = $decision"


def final_score(rule_score: float, graph_risk: float) -> float:
    """Transaction risk 0-100: noisy-OR of this transaction's rule score and the
    account's graph risk (1.0 if flagged, else its propagated risk). The account's
    own rule history is deliberately left out so a rule hit is not counted twice."""
    return round(100 * (1 - (1 - rule_score / 100) * (1 - graph_risk)), 2)


def decide(score: float, settings: RuntimeSettings) -> Decision:
    if score >= settings.decision.block_threshold:
        return Decision.BLOCK
    if score >= settings.decision.review_threshold:
        return Decision.REVIEW
    return Decision.ALLOW


class IngestionService:
    def __init__(
        self,
        driver: AsyncDriver,
        settings_provider,
        alerts: AlertService,
        hub: Hub,
        metrics: Metrics,
        pii_key: str,
    ) -> None:
        self.driver = driver
        self.settings_provider = settings_provider  # callable -> RuntimeSettings (admin may change it)
        self.alerts = alerts
        self.hub = hub
        self.metrics = metrics
        self.key = pii_key
        self.lock = asyncio.Lock()
        self.queue: asyncio.Queue[TransactionEvent] = asyncio.Queue(maxsize=10_000)

    # --- queue ----------------------------------------------------------------

    async def enqueue(self, event: TransactionEvent) -> None:
        await self.queue.put(event)
        self.metrics.queue_depth = self.queue.qsize()

    async def worker(self) -> None:
        """Background consumer: processes queued events forever."""
        while True:
            event = await self.queue.get()
            try:
                await self.process(event)
            except Exception:
                logger.exception("ingestion failed", extra={"transaction_id": event.transaction_id})
                self.metrics.errors += 1
            finally:
                self.queue.task_done()
                self.metrics.queue_depth = self.queue.qsize()

    # --- pipeline -------------------------------------------------------------

    async def process(self, event: TransactionEvent) -> ScoreResult:
        async with self.lock:
            return await self._process(event)

    async def _process(self, event: TransactionEvent) -> ScoreResult:
        start = time.perf_counter()
        settings: RuntimeSettings = self.settings_provider()

        existing, _, _ = await self.driver.execute_query(EXISTING, id=event.transaction_id)
        if existing:
            return await self._stored_result(existing[0], start)

        ctx_rec, _, _ = await self.driver.execute_query(
            CONTEXT,
            account_id=event.account.id,
            device_id=event.device.device_id if event.device else None,
            merchant_id=event.merchant.id if event.merchant else None,
            since=event.timestamp - timedelta(minutes=settings.rules.velocity_window_minutes),
            ts=event.timestamp,
        )
        ctx = ctx_rec[0]
        tier = (
            RiskTier(ctx["merchant_tier"]) if ctx["merchant_tier"]
            else (event.merchant.risk_tier if event.merchant else None)
        )
        rule_score, reasons = rules.score(
            rules.RuleContext(
                amount=event.amount,
                recent_count=ctx["recent"] + 1,
                new_device=event.device is not None and ctx["account_exists"] and not ctx["known_device"],
                location=event.location,
                merchant_tier=tier,
            ),
            settings.rules,
        )

        async with self.driver.session() as session:
            await session.execute_write(self._write, event, rule_score, reasons)
        for statement in DERIVE_FOR_ACCOUNT:
            await self.driver.execute_query(statement, account_id=event.account.id)
        await self.driver.execute_query(
            UPDATE_OWN_RISK, account_id=event.account.id, rule_risk=rule_score / 100
        )

        link, _, _ = await self.driver.execute_query(LINK_CHECK, account_id=event.account.id)
        rings_of, flagged_near = link[0]["rings"], link[0]["flagged_near"]
        linked = bool(flagged_near) and not link[0]["is_flagged"]
        if linked:
            self.metrics.last_propagation = await propagate_and_alert(self.driver, settings, self.alerts)

        risk, _, _ = await self.driver.execute_query(ACCOUNT_RISK, account_id=event.account.id)
        risk = risk[0]
        score = final_score(rule_score, risk["graph_risk"])
        decision = decide(score, settings)
        await self.driver.execute_query(SET_FINAL, id=event.transaction_id, final=score, decision=decision.value)

        if rule_score >= settings.rules.flag_threshold:
            await self.alerts.raise_alert(
                AlertType.HIGH_RULE_SCORE,
                Severity.HIGH if rule_score >= 80 else Severity.MEDIUM,
                f"Rule score {rule_score}: " + "; ".join(reasons),
                "Transaction",
                event.transaction_id,
            )
        if linked:
            await self.alerts.raise_alert(
                AlertType.LINKED_TO_FRAUD,
                Severity.HIGH,
                f"Account {event.account.id} shares attributes (within 2 hops) with flagged "
                f"account(s) {', '.join(sorted(set(flagged_near))[:5])}.",
                "Account",
                event.account.id,
            )

        latency = round((time.perf_counter() - start) * 1000, 2)
        self.metrics.record_ingest(latency)
        result = ScoreResult(
            transaction_id=event.transaction_id,
            account_id=event.account.id,
            decision=decision,
            final_score=score,
            rule_score=rule_score,
            rule_reasons=reasons,
            account_risk=round(risk["graph_risk"], 4),
            propagated_risk=round(risk["propagated"], 4),
            risk_explanation=risk["explanation"],
            linked_to_fraud=linked,
            ring_ids=rings_of,
            latency_ms=latency,
        )
        await self.hub.broadcast(
            "transaction",
            {
                "id": event.transaction_id,
                "account_id": event.account.id,
                "amount": event.amount,
                "channel": event.channel.value,
                "location": event.location,
                "timestamp": event.timestamp,
                "rule_score": rule_score,
                "final_score": score,
                "decision": decision.value,
                "linked_to_fraud": linked,
            },
        )
        return result

    async def _write(
        self, tx: AsyncManagedTransaction, event: TransactionEvent, rule_score: int, reasons: list[str]
    ) -> None:
        account = event.account
        await tx.run(
            MERGE_ACCOUNT,
            id=account.id,
            account_no=account.account_no or account.id,
            type=account.type.value,
            opened_at=account.opened_at or event.timestamp,
        )
        if event.user:
            user, address = event.user, event.user.address
            address_hash = pii.hash_address(address.line, address.city, address.pincode, self.key)
            await tx.run(
                MERGE_USER,
                account_id=account.id,
                user={
                    "id": user.id,
                    "name": user.name,
                    "email": user.email,
                    "phone": pii.mask_phone(user.phone),
                    "kyc_status": user.kyc_status.value,
                },
                address={
                    "id": "ADDR-" + address_hash[:12],
                    "line": address.line,
                    "city": address.city,
                    "pincode": address.pincode,
                    "normalized_hash": address_hash,
                },
                phone_hash=pii.hash_phone(user.phone, self.key),
            )
        if event.device:
            await tx.run(MERGE_DEVICE, account_id=account.id, device=event.device.model_dump())
        if event.card:
            digits = "".join(ch for ch in event.card.number if ch.isdigit())
            await tx.run(
                MERGE_CARD,
                account_id=account.id,
                card={
                    "card_hash": pii.hash_card(digits, self.key),
                    "last4": digits[-4:],
                    "bin": digits[:6],
                    "issuer": event.card.issuer or "Unknown",
                    "type": event.card.type.value,
                },
            )
        tx_props = {
            "id": event.transaction_id,
            "amount": event.amount,
            "currency": event.currency,
            "timestamp": event.timestamp,
            "channel": event.channel.value,
            "location": event.location,
            "status": event.status.value,
            "rule_score": rule_score,
            "rule_reasons": reasons,
            "final_score": float(rule_score),
        }
        if event.merchant:
            m = event.merchant
            label, target_id = "Merchant", m.id
            target_props = {
                "name": m.name or m.id,
                "category": m.category or "Unknown",
                "mcc": m.mcc or "0000",
                "country": m.country,
                "risk_tier": m.risk_tier.value,
            }
        else:
            label, target_id = "Account", event.counterparty_account_id
            target_props = {
                "account_no": target_id, "type": "SAVINGS", "status": "ACTIVE", "risk_score": 0.0,
                "propagated_risk": 0.0, "combined_risk": 0.0, "is_flagged": False,
            }
        await tx.run(
            MERGE_TRANSACTION.format(label=label),
            account_id=account.id,
            target_id=target_id,
            target_props=target_props,
            tx=tx_props,
        )

    async def _stored_result(self, record, start: float) -> ScoreResult:
        t = record["t"]
        risk, _, _ = await self.driver.execute_query(ACCOUNT_RISK, account_id=record["account_id"])
        return ScoreResult(
            transaction_id=t["id"],
            account_id=record["account_id"],
            decision=Decision(t.get("decision", "ALLOW")),
            final_score=float(t.get("final_score", 0)),
            rule_score=int(t.get("rule_score", 0)),
            rule_reasons=list(t.get("rule_reasons", [])),
            account_risk=round(risk[0]["graph_risk"], 4),
            propagated_risk=round(risk[0]["propagated"], 4),
            risk_explanation=risk[0]["explanation"],
            linked_to_fraud=False,
            ring_ids=[],
            duplicate=True,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )
