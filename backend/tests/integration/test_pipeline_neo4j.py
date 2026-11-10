"""Integration tests for the full detection pipeline on a real Neo4j with GDS + APOC:
ring detection finds planted rings, propagation reaches expected neighbours with
expected scores, multi-hop queries, and idempotent real-time ingestion."""

import asyncio
from datetime import datetime, timezone

import pytest
from neo4j import AsyncGraphDatabase

from app.datagen.generator import GenParams, generate
from app.datagen.loader import load, wipe
from app.datagen.scoring import write_scores
from app.db.schema import apply_schema
from app.models.events import TransactionEvent
from app.models.settings import RuntimeSettings
from app.services import graph_queries
from app.services.alerting import AlertService
from app.services.ingestion import IngestionService
from app.services.metrics import Metrics
from app.services.propagation import run_propagation
from app.services.ring_detection import detect_rings
from app.websocket.hub import Hub

pytestmark = pytest.mark.integration

KEY = "integration-key-0123456789"
PARAMS = GenParams(users=400, accounts=520, merchants=30, transactions=3000, rings_per_type=2, seed=5)
DS = generate(PARAMS, KEY, now=datetime.now(timezone.utc).replace(microsecond=0))
SETTINGS = RuntimeSettings()


def run(neo4j, scenario):
    async def wrapper():
        driver = AsyncGraphDatabase.driver(neo4j["url"], auth=neo4j["auth"])
        try:
            return await scenario(driver)
        finally:
            await driver.close()

    return asyncio.run(wrapper())


@pytest.fixture(scope="module")
def pipeline(neo4j):
    async def scenario(driver):
        await wipe(driver)
        await apply_schema(driver)
        await load(driver, DS)
        await write_scores(driver, DS, SETTINGS.rules)
        propagation = await run_propagation(driver, SETTINGS)
        detection = await detect_rings(driver, SETTINGS, AlertService(driver, Hub()))
        members, _, _ = await driver.execute_query(
            "MATCH (g:Ring)<-[:MEMBER_OF]-(a:Account) RETURN g.ring_id AS ring, collect(a.id) AS ids"
        )
        return propagation, detection, {r["ring"]: set(r["ids"]) for r in members}

    return run(neo4j, scenario)


def test_every_planted_ring_is_detected(pipeline) -> None:
    _, detection, rings = pipeline
    assert detection["rings"] >= len(DS.rings)
    for planted in DS.rings:
        accounts = set(planted["accounts"])
        best = max(len(accounts & ids) / len(accounts) for ids in rings.values())
        assert best >= 0.5, f"{planted['ring_id']} not found"


def test_projection_is_dropped_after_detection(neo4j, pipeline) -> None:
    async def scenario(driver):
        records, _, _ = await driver.execute_query("CALL gds.graph.list() YIELD graphName RETURN graphName")
        return [r["graphName"] for r in records]

    assert run(neo4j, scenario) == []


def test_propagation_reaches_shared_device_neighbours_with_expected_score(neo4j, pipeline) -> None:
    ring = next(r for r in DS.rings if r["type"] == "shared_device" and r["flagged_accounts"])
    flagged = ring["flagged_accounts"][0]
    others = [a for a in ring["accounts"] if a != flagged]

    async def scenario(driver):
        records, _, _ = await driver.execute_query(
            "UNWIND $ids AS id MATCH (a:Account {id: id}) RETURN a.id AS id, a.propagated_risk AS risk",
            ids=others,
        )
        return {r["id"]: r["risk"] for r in records}

    risks = run(neo4j, scenario)
    # Every member shares the ring's device with the flagged account: >= 1.0 x 0.9 x 0.5.
    assert all(risk >= 0.45 - 1e-9 for risk in risks.values())


def test_shortest_path_names_the_shared_device(neo4j, pipeline) -> None:
    ring = next(r for r in DS.rings if r["type"] == "shared_device")
    a, b = ring["accounts"][0], ring["accounts"][2]
    result = run(neo4j, lambda d: graph_queries.shortest_path(d, a, b))
    assert result["found"] and result["hops"] == 2
    assert "USES_DEVICE" in result["paths"][0]


def test_neighbourhood_and_link_to_fraud(neo4j, pipeline) -> None:
    ring = next(r for r in DS.rings if r["type"] == "shared_device" and r["flagged_accounts"])
    member = next(a for a in ring["accounts"] if a not in ring["flagged_accounts"])
    hood = run(neo4j, lambda d: graph_queries.neighbourhood(d, "Account", member, 2, None))
    keys = {n["key"] for n in hood["nodes"]}
    assert set(ring["accounts"]) <= keys
    linked = run(neo4j, lambda d: graph_queries.linked_to_fraud(d, member, 2))
    assert linked["linked"] and linked["matches"][0]["hops"] == 1


def test_ingestion_is_idempotent_and_links_new_account_to_ring(neo4j, pipeline) -> None:
    ring = next(r for r in DS.rings if r["type"] == "shared_device" and r["flagged_accounts"])
    event = TransactionEvent(
        transaction_id="LIVE-1",
        timestamp=datetime.now(timezone.utc),
        amount=1200,
        channel="UPI",
        location="Pune, IN",
        account={"id": "NEW-ACC-1"},
        user={"id": "NEW-USR-1", "name": "New Person", "email": "n@example.com", "phone": "+919800000001",
              "address": {"line": "1 Test Road", "city": "Pune", "pincode": "411001"}},
        device={"device_id": ring["shared"]["devices"][0]},
        merchant={"id": DS.merchants[0].id},
    )

    async def scenario(driver):
        service = IngestionService(driver, lambda: SETTINGS, AlertService(driver, Hub()), Hub(), Metrics(), KEY)
        first = await service.process(event)
        second = await service.process(event)
        counts, _, _ = await driver.execute_query(
            "MATCH (t:Transaction {id: 'LIVE-1'}) WITH count(t) AS t "
            "MATCH (:Account {id: 'NEW-ACC-1'})-[r:SHARED_DEVICE]-() RETURN t, count(r) AS shared"
        )
        alerts, _, _ = await driver.execute_query(
            "MATCH (al:Alert)-[:ABOUT]->(:Account {id: 'NEW-ACC-1'}) RETURN collect(al.type) AS types"
        )
        return first, second, counts[0], alerts[0]["types"]

    first, second, counts, alert_types = run(neo4j, scenario)
    assert first.linked_to_fraud and first.propagated_risk >= 0.45
    assert first.rule_score < SETTINGS.rules.flag_threshold  # the rules alone see nothing
    assert second.duplicate and counts["t"] == 1
    assert counts["shared"] == len(ring["accounts"])
    assert "LINKED_TO_FRAUD" in alert_types and "PROPAGATED_RISK" in alert_types
