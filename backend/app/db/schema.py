"""Loads backend/schema.cypher and applies it to Neo4j.

Every statement in the file uses IF NOT EXISTS, so applying it repeatedly is safe.
Run manually with:  python -m app.db.schema
"""

import asyncio
import logging
import re
from pathlib import Path

from neo4j import AsyncDriver

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema.cypher"

# Captures the name in "CREATE CONSTRAINT <name> ..." / "CREATE INDEX <name> ...".
_NAME_PATTERN = re.compile(r"^CREATE\s+(?:CONSTRAINT|INDEX)\s+(\w+)", re.IGNORECASE)

logger = logging.getLogger(__name__)


def load_statements(path: Path = SCHEMA_PATH) -> list[str]:
    """Split the schema file into statements, dropping full-line // comments."""
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("//")
    ]
    return [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]


def schema_object_names(statements: list[str]) -> set[str]:
    """Names of the constraints and indexes the statements create."""
    return {match.group(1) for stmt in statements if (match := _NAME_PATTERN.match(stmt))}


async def apply_schema(driver: AsyncDriver, statements: list[str] | None = None) -> int:
    """Run every schema statement; returns how many were run."""
    statements = statements if statements is not None else load_statements()
    for stmt in statements:
        await driver.execute_query(stmt)
    return len(statements)


async def apply_schema_with_retry(
    driver: AsyncDriver, attempts: int = 5, delay_s: float = 2.0
) -> bool:
    """Apply the schema at startup, retrying while Neo4j finishes booting.

    Returns False instead of raising, so the API still starts and /ready reports
    the missing schema.
    """
    for attempt in range(1, attempts + 1):
        try:
            count = await apply_schema(driver)
            logger.info("schema applied", extra={"statements": count})
            return True
        except Exception as exc:  # connection refused, auth error, bad statement...
            logger.warning(
                "schema apply failed", extra={"attempt": attempt, "error": str(exc)}
            )
            if attempt < attempts:
                await asyncio.sleep(delay_s)
    return False


async def _main() -> None:
    from app.config import get_settings
    from app.db.neo4j import create_driver

    driver = create_driver(get_settings())
    try:
        count = await apply_schema(driver)
        print(f"Applied {count} schema statements from {SCHEMA_PATH}")
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(_main())
