"""Liveness and readiness probes.

/health  -> the API process is up (no dependencies checked).
/ready   -> Neo4j is reachable, the GDS and APOC plugins are installed, and every
            constraint/index from schema.cypher exists.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from neo4j import AsyncDriver

from app import __version__
from app.db.neo4j import get_driver
from app.db.schema import load_statements, schema_object_names

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

EXPECTED_CHECKS = {"neo4j", "gds", "apoc", "schema"}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


async def _check(driver: AsyncDriver, query: str) -> dict[str, Any]:
    """Run a single-value query and report ok/error instead of raising."""
    try:
        records, _, _ = await driver.execute_query(query)
        return {"ok": True, "version": records[0]["version"]}
    except Exception as exc:  # any failure means "not ready"; the reason is reported
        logger.warning("readiness check failed", extra={"query": query, "error": str(exc)})
        return {"ok": False, "error": str(exc)}


async def _check_schema(driver: AsyncDriver) -> dict[str, Any]:
    """Compare schema.cypher against the database.

    Uniqueness constraints show up in SHOW INDEXES under the constraint's name
    (as their backing index), so one query covers constraints and indexes.
    """
    expected = schema_object_names(load_statements())
    try:
        records, _, _ = await driver.execute_query(
            "SHOW INDEXES YIELD name RETURN collect(name) AS names"
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    missing = sorted(expected - set(records[0]["names"]))
    if missing:
        return {"ok": False, "error": f"missing: {', '.join(missing)}"}
    return {"ok": True, "version": f"{len(expected)} constraints/indexes"}


@router.get("/ready")
async def ready(response: Response, driver: AsyncDriver = Depends(get_driver)) -> dict[str, Any]:
    checks = {
        "neo4j": await _check(
            driver, "CALL dbms.components() YIELD versions RETURN versions[0] AS version"
        ),
    }
    # Plugin and schema checks only make sense once Neo4j itself answers.
    if checks["neo4j"]["ok"]:
        checks["gds"] = await _check(driver, "RETURN gds.version() AS version")
        checks["apoc"] = await _check(driver, "RETURN apoc.version() AS version")
        checks["schema"] = await _check_schema(driver)

    is_ready = set(checks) == EXPECTED_CHECKS and all(c["ok"] for c in checks.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if is_ready else "not_ready", "checks": checks}
