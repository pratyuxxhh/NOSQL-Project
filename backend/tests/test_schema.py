"""Unit tests for the schema file and loader (no database needed)."""

import asyncio
from pathlib import Path

from app.db.schema import (
    apply_schema,
    apply_schema_with_retry,
    load_statements,
    schema_object_names,
)
from app.models.graph import NodeLabel

STATEMENTS = load_statements()


def test_comments_are_stripped_and_statements_split(tmp_path: Path) -> None:
    schema = tmp_path / "schema.cypher"
    schema.write_text(
        "// header\nCREATE INDEX a IF NOT EXISTS\nFOR (n:X) ON (n.p);\n\n"
        "  // indented comment\nCREATE CONSTRAINT b IF NOT EXISTS FOR (n:Y) REQUIRE n.id IS UNIQUE;\n",
        encoding="utf-8",
    )
    statements = load_statements(schema)
    assert statements == [
        "CREATE INDEX a IF NOT EXISTS\nFOR (n:X) ON (n.p)",
        "CREATE CONSTRAINT b IF NOT EXISTS FOR (n:Y) REQUIRE n.id IS UNIQUE",
    ]
    assert schema_object_names(statements) == {"a", "b"}


def test_every_statement_is_idempotent_and_named() -> None:
    for stmt in STATEMENTS:
        assert "IF NOT EXISTS" in stmt, stmt
    # One name per statement, no duplicates.
    assert len(schema_object_names(STATEMENTS)) == len(STATEMENTS)


def test_every_node_label_has_a_uniqueness_constraint() -> None:
    constrained = {
        label
        for label in NodeLabel
        for stmt in STATEMENTS
        if stmt.startswith("CREATE CONSTRAINT") and f"(n:{label})" in stmt
    }
    assert constrained == set(NodeLabel)


def test_required_indexes_exist() -> None:
    # Properties the spec says must be indexed.
    text = "\n".join(STATEMENTS)
    assert "(n:Transaction) ON (n.timestamp)" in text
    assert "(n:Account) ON (n.risk_score)" in text
    assert "(n:Account) ON (n.is_flagged)" in text


class RecordingDriver:
    def __init__(self, fail_times: int = 0) -> None:
        self.queries: list[str] = []
        self.fail_times = fail_times

    async def execute_query(self, query: str):
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("neo4j not up yet")
        self.queries.append(query)


def test_apply_schema_runs_every_statement() -> None:
    driver = RecordingDriver()
    count = asyncio.run(apply_schema(driver))  # type: ignore[arg-type]
    assert count == len(STATEMENTS)
    assert driver.queries == STATEMENTS


def test_retry_succeeds_after_transient_failure() -> None:
    driver = RecordingDriver(fail_times=2)
    ok = asyncio.run(apply_schema_with_retry(driver, attempts=3, delay_s=0))  # type: ignore[arg-type]
    assert ok is True


def test_retry_gives_up_without_raising() -> None:
    driver = RecordingDriver(fail_times=10)
    ok = asyncio.run(apply_schema_with_retry(driver, attempts=2, delay_s=0))  # type: ignore[arg-type]
    assert ok is False
