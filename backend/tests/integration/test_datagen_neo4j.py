"""Integration tests: load a small generated dataset into a real Neo4j."""

import asyncio
from datetime import datetime, timezone

import pytest
from neo4j import AsyncGraphDatabase

from app.datagen.generator import GenParams, generate
from app.datagen.loader import graph_counts, load, wipe
from app.db.schema import apply_schema

pytestmark = pytest.mark.integration

KEY = "integration-key-0123456789"
PARAMS = GenParams(users=300, accounts=400, merchants=30, transactions=3000, rings_per_type=2, seed=11)
DS = generate(PARAMS, KEY, now=datetime(2026, 11, 1, tzinfo=timezone.utc))


def run(neo4j, scenario):
    async def wrapper():
        driver = AsyncGraphDatabase.driver(neo4j["url"], auth=neo4j["auth"])
        try:
            return await scenario(driver)
        finally:
            await driver.close()

    return asyncio.run(wrapper())


@pytest.fixture(scope="module")
def loaded(neo4j):
    async def scenario(driver):
        await wipe(driver)
        await apply_schema(driver)
        await load(driver, DS)
        return await graph_counts(driver)

    return run(neo4j, scenario)


def test_node_counts_match_dataset(loaded) -> None:
    assert loaded["User"] == PARAMS.users
    assert loaded["Account"] == PARAMS.accounts
    assert loaded["Merchant"] == PARAMS.merchants
    assert loaded["Transaction"] == PARAMS.transactions
    assert loaded["INITIATED"] == PARAMS.transactions
    assert loaded["PAID_TO"] == PARAMS.transactions
    assert loaded["Analyst"] == 1


def test_loading_twice_is_idempotent(neo4j, loaded) -> None:
    async def scenario(driver):
        await load(driver, DS)
        return await graph_counts(driver)

    assert run(neo4j, scenario) == loaded


def test_shared_device_ring_members_are_linked(neo4j, loaded) -> None:
    ring = next(r for r in DS.rings if r["type"] == "shared_device")

    async def scenario(driver):
        records, _, _ = await driver.execute_query(
            """
            UNWIND $ids AS id
            MATCH (a:Account {id: id})-[:SHARED_DEVICE]-(b:Account)
            WHERE b.id IN $ids
            RETURN a.id AS id, count(DISTINCT b) AS linked
            """,
            ids=ring["accounts"],
        )
        return {r["id"]: r["linked"] for r in records}

    linked = run(neo4j, scenario)
    # Everyone uses the ring's first device, so each member links to all others.
    assert linked == {a: len(ring["accounts"]) - 1 for a in ring["accounts"]}


def test_every_ring_type_produces_shared_edges(neo4j, loaded) -> None:
    edge_for = {
        "shared_device": "SHARED_DEVICE",
        "shared_address_mule": "SHARED_ADDRESS",
        "card_testing": "SHARED_CARD",
        "layering_chain": "SHARED_PHONE",
    }

    async def scenario(driver):
        result = {}
        for ring in DS.rings:
            records, _, _ = await driver.execute_query(
                f"MATCH (a:Account)-[r:{edge_for[ring['type']]}]-(b:Account) "
                "WHERE a.id IN $ids AND b.id IN $ids RETURN count(r) AS n",
                ids=ring["accounts"],
            )
            result[ring["ring_id"]] = records[0]["n"]
        return result

    assert all(n > 0 for n in run(neo4j, scenario).values())


def test_no_shared_edges_between_accounts_of_the_same_owner(neo4j, loaded) -> None:
    async def scenario(driver):
        records, _, _ = await driver.execute_query(
            "MATCH (a1:Account)<-[:OWNS]-(:User)-[:OWNS]->(a2:Account), "
            "(a1)-[r:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE]-(a2) "
            "RETURN count(r) AS n"
        )
        return records[0]["n"]

    assert run(neo4j, scenario) == 0


def test_flagged_accounts_link_to_seed_analyst(neo4j, loaded) -> None:
    async def scenario(driver):
        records, _, _ = await driver.execute_query(
            "MATCH (a:Account {is_flagged: true})-[:FLAGGED_BY]->(:Analyst) RETURN collect(a.id) AS ids"
        )
        return set(records[0]["ids"])

    assert run(neo4j, scenario) == {f["account"] for f in DS.flags}
