"""Integration tests: apply schema.cypher to a real, empty Neo4j container."""

import asyncio

import pytest
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import ConstraintError

from app.db.schema import apply_schema, load_statements, schema_object_names

pytestmark = pytest.mark.integration


async def _with_driver(neo4j_url: str, auth: tuple[str, str], fn):
    driver = AsyncGraphDatabase.driver(neo4j_url, auth=auth)
    try:
        return await fn(driver)
    finally:
        await driver.close()


def run(neo4j, fn):
    return asyncio.run(_with_driver(neo4j["url"], neo4j["auth"], fn))


async def _index_names(driver) -> set[str]:
    records, _, _ = await driver.execute_query("SHOW INDEXES YIELD name RETURN name")
    return {r["name"] for r in records}


def test_schema_creates_every_constraint_and_index(neo4j) -> None:
    async def scenario(driver):
        await apply_schema(driver)
        return await _index_names(driver)

    names = run(neo4j, scenario)
    assert schema_object_names(load_statements()) <= names


def test_schema_can_be_applied_twice(neo4j) -> None:
    async def scenario(driver):
        await apply_schema(driver)
        before = await _index_names(driver)
        await apply_schema(driver)
        return before, await _index_names(driver)

    before, after = run(neo4j, scenario)
    assert before == after


def test_duplicate_transaction_id_is_rejected(neo4j) -> None:
    async def scenario(driver):
        await apply_schema(driver)
        await driver.execute_query("MATCH (n) DETACH DELETE n")
        await driver.execute_query("CREATE (:Transaction {id: $id})", id="T-dup")
        await driver.execute_query("CREATE (:Transaction {id: $id})", id="T-dup")

    with pytest.raises(ConstraintError):
        run(neo4j, scenario)


def test_merge_on_unique_id_does_not_duplicate(neo4j) -> None:
    async def scenario(driver):
        await apply_schema(driver)
        await driver.execute_query("MATCH (n) DETACH DELETE n")
        for _ in range(3):
            await driver.execute_query("MERGE (:Account {id: $id})", id="A-1")
        records, _, _ = await driver.execute_query(
            "MATCH (a:Account {id: $id}) RETURN count(a) AS n", id="A-1"
        )
        return records[0]["n"]

    assert run(neo4j, scenario) == 1
