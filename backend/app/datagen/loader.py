"""Bulk-loads a generated Dataset into Neo4j.

Every write uses UNWIND over a batch of parameter rows and MERGE on the unique
keys from schema.cypher, so loading the same dataset twice changes nothing.
"""

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from neo4j import AsyncDriver

from app.datagen.builder import Dataset
from app.db.schema import load_statements

DERIVE_SHARED_EDGES = Path(__file__).resolve().parents[1] / "cypher" / "derive_shared_edges.cypher"

# The analyst who "confirmed" the historical chargebacks in the seed data.
SEED_ANALYST = {"id": "AN0001", "username": "seed.analyst", "name": "Seed Analyst"}

logger = logging.getLogger(__name__)

# --- Node writes --------------------------------------------------------------

MERGE_MERCHANTS = "UNWIND $rows AS r MERGE (n:Merchant {id: r.id}) SET n += r"
MERGE_ADDRESSES = "UNWIND $rows AS r MERGE (n:Address {normalized_hash: r.normalized_hash}) SET n += r"
MERGE_PHONES = "UNWIND $rows AS r MERGE (:Phone {number_hash: r.number_hash})"
MERGE_USERS = "UNWIND $rows AS r MERGE (n:User {id: r.id}) SET n += r"
MERGE_ACCOUNTS = "UNWIND $rows AS r MERGE (n:Account {id: r.id}) SET n += r"
MERGE_DEVICES = "UNWIND $rows AS r MERGE (n:Device {device_id: r.device_id}) SET n += r"
MERGE_CARDS = "UNWIND $rows AS r MERGE (n:Card {card_hash: r.card_hash}) SET n += r"

# --- Relationship writes ------------------------------------------------------

MERGE_LIVES_AT = """
UNWIND $rows AS r
MATCH (u:User {id: r[0]}), (a:Address {id: r[1]})
MERGE (u)-[:LIVES_AT]->(a)"""
MERGE_HAS_PHONE = """
UNWIND $rows AS r
MATCH (u:User {id: r[0]}), (p:Phone {number_hash: r[1]})
MERGE (u)-[:HAS_PHONE]->(p)"""
MERGE_OWNS = """
UNWIND $rows AS r
MATCH (u:User {id: r[0]}), (a:Account {id: r[1]})
MERGE (u)-[:OWNS]->(a)"""
MERGE_USES_DEVICE = """
UNWIND $rows AS r
MATCH (a:Account {id: r[0]}), (d:Device {device_id: r[1]})
MERGE (a)-[:USES_DEVICE]->(d)"""
MERGE_USES_CARD = """
UNWIND $rows AS r
MATCH (a:Account {id: r[0]}), (c:Card {card_hash: r[1]})
MERGE (a)-[:USES_CARD]->(c)"""

# Transaction node + who initiated it + who was paid. Target label is fixed per
# query (Merchant or Account) so the lookup uses the unique-ID index.
MERGE_TRANSACTIONS = """
UNWIND $rows AS r
MATCH (src:Account {{id: r.source}}), (dst:{label} {{id: r.target}})
MERGE (t:Transaction {{id: r.props.id}})
SET t += r.props
MERGE (src)-[:INITIATED]->(t)
MERGE (t)-[:PAID_TO]->(dst)"""

# One TRANSACTED_WITH edge per (payer, payee) pair carrying running totals.
MERGE_TRANSACTED_WITH = """
UNWIND $rows AS r
MATCH (src:Account {{id: r.source}}), (dst:{label} {{id: r.target}})
MERGE (src)-[w:TRANSACTED_WITH]->(dst)
SET w.count = r.count, w.total_amount = r.total_amount, w.last_at = r.last_at"""

MERGE_FLAGS = """
MERGE (an:Analyst {id: $analyst.id})
SET an.username = $analyst.username, an.name = $analyst.name
WITH an
UNWIND $rows AS r
MATCH (a:Account {id: r.account})
SET a.is_flagged = true, a.risk_score = 1.0
MERGE (a)-[f:FLAGGED_BY]->(an)
SET f.reason = r.reason, f.at = r.at, f.confidence = r.confidence"""

# Deletes in chunks so a large graph does not need one huge transaction.
WIPE = "MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS"


async def _batches(driver: AsyncDriver, query: str, rows: list, size: int, **params: Any) -> None:
    for start in range(0, len(rows), size):
        await driver.execute_query(query, rows=rows[start : start + size], **params)


async def wipe(driver: AsyncDriver) -> None:
    # CALL ... IN TRANSACTIONS must run in an auto-commit transaction (session.run).
    async with driver.session() as session:
        result = await session.run(WIPE)
        await result.consume()


def _aggregate_transacted_with(ds: Dataset) -> dict[bool, list[dict]]:
    totals: dict[tuple[str, str, bool], dict] = defaultdict(
        lambda: {"count": 0, "total_amount": 0.0, "last_at": None}
    )
    for record in ds.transactions:
        pair = totals[(record.source, record.target, record.to_merchant)]
        pair["count"] += 1
        pair["total_amount"] = round(pair["total_amount"] + record.tx.amount, 2)
        if pair["last_at"] is None or record.tx.timestamp > pair["last_at"]:
            pair["last_at"] = record.tx.timestamp
    by_target: dict[bool, list[dict]] = {True: [], False: []}
    for (source, target, to_merchant), agg in totals.items():
        by_target[to_merchant].append({"source": source, "target": target, **agg})
    return by_target


async def load(driver: AsyncDriver, ds: Dataset, batch_size: int = 5000) -> None:
    def dump(models) -> list[dict]:
        return [m.model_dump() for m in models]

    steps: list[tuple[str, str, list]] = [
        ("merchants", MERGE_MERCHANTS, dump(ds.merchants)),
        ("addresses", MERGE_ADDRESSES, dump(ds.addresses.values())),
        ("phones", MERGE_PHONES, dump(ds.phones.values())),
        ("users", MERGE_USERS, dump(ds.users)),
        ("accounts", MERGE_ACCOUNTS, dump(ds.accounts)),
        ("devices", MERGE_DEVICES, dump(ds.devices.values())),
        ("cards", MERGE_CARDS, dump(ds.cards.values())),
        ("LIVES_AT", MERGE_LIVES_AT, ds.lives_at),
        ("HAS_PHONE", MERGE_HAS_PHONE, ds.has_phone),
        ("OWNS", MERGE_OWNS, ds.owns),
        ("USES_DEVICE", MERGE_USES_DEVICE, ds.uses_device),
        ("USES_CARD", MERGE_USES_CARD, ds.uses_card),
    ]
    for to_merchant, label in ((True, "Merchant"), (False, "Account")):
        rows = [
            {"source": r.source, "target": r.target, "props": r.tx.model_dump()}
            for r in ds.transactions
            if r.to_merchant == to_merchant
        ]
        steps.append((f"transactions -> {label}", MERGE_TRANSACTIONS.format(label=label), rows))
    for to_merchant, rows in _aggregate_transacted_with(ds).items():
        label = "Merchant" if to_merchant else "Account"
        steps.append((f"TRANSACTED_WITH -> {label}", MERGE_TRANSACTED_WITH.format(label=label), rows))

    for name, query, rows in steps:
        await _batches(driver, query, rows, batch_size)
        logger.info("loaded", extra={"step": name, "rows": len(rows)})

    await _batches(driver, MERGE_FLAGS, ds.flags, batch_size, analyst=SEED_ANALYST)
    for statement in load_statements(DERIVE_SHARED_EDGES):
        await driver.execute_query(statement)
    logger.info("derived SHARED_* edges")


async def graph_counts(driver: AsyncDriver) -> dict[str, int]:
    """Node counts per label and relationship counts per type."""
    nodes, _, _ = await driver.execute_query(
        "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n ORDER BY label"
    )
    rels, _, _ = await driver.execute_query(
        "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY type"
    )
    return {r["label"]: r["n"] for r in nodes} | {r["type"]: r["n"] for r in rels}
