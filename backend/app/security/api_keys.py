"""API keys for transaction-processing services (the ingestion clients).

A key looks like `fm_<random>`. Only its SHA-256 is stored, so a database leak
does not reveal usable keys; the full key is shown once, at creation.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from neo4j import AsyncDriver

from app.db.neo4j import get_driver
from app.security.rate_limit import ingest_window

header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(frozen=True)
class ApiClient:
    id: str
    name: str
    rate_limit_per_min: int


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_key() -> str:
    return "fm_" + secrets.token_urlsafe(32)


async def create_api_key(driver: AsyncDriver, name: str, rate_limit_per_min: int = 6000) -> dict:
    key = generate_key()
    record = {
        "id": str(uuid.uuid4()),
        "name": name,
        "prefix": key[:8],
        "key_hash": hash_key(key),
        "rate_limit_per_min": rate_limit_per_min,
        "active": True,
    }
    await driver.execute_query("CREATE (k:ApiKey $props) SET k.created_at = datetime()", props=record)
    return {**{k: v for k, v in record.items() if k != "key_hash"}, "key": key}


async def api_client(request: Request, key: str | None = Depends(header)) -> ApiClient:
    """FastAPI dependency: a valid, active API key within its rate limit."""
    if not key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key header")
    driver: AsyncDriver = get_driver(request)
    records, _, _ = await driver.execute_query(
        "MATCH (k:ApiKey {key_hash: $hash, active: true}) "
        "SET k.last_used_at = datetime() RETURN k.id AS id, k.name AS name, k.rate_limit_per_min AS rl",
        hash=hash_key(key),
    )
    if not records:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key")
    client = ApiClient(records[0]["id"], records[0]["name"], int(records[0]["rl"]))
    cost = getattr(request.state, "event_count", 1)
    if not ingest_window.allow(client.id, client.rate_limit_per_min, cost):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "API key rate limit exceeded")
    return client
