"""Multi-hop relationship discovery (F4). Query text lives in app/cypher/*.cypher.

Cypher cannot take labels, relationship types or path-length bounds as
parameters, so those are checked against whitelists / ranges here and only
then placed into the query. Every user-supplied value is a parameter.
"""

from pathlib import Path

from fastapi import HTTPException
from neo4j import AsyncDriver

from app.db.schema import load_statements
from app.db.serialize import GraphBuilder, path_in_words

CYPHER_DIR = Path(__file__).resolve().parents[1] / "cypher"

# Searchable node types and the property that identifies each.
NODE_KEYS = {
    "Account": "id",
    "User": "id",
    "Device": "device_id",
    "Card": "card_hash",
    "Address": "id",
    "Phone": "number_hash",
    "Merchant": "id",
    "Transaction": "id",
    "Ring": "ring_id",
}
RELATIONSHIP_TYPES = {
    "TRANSACTED_WITH", "SHARED_DEVICE", "SHARED_ADDRESS", "SHARED_CARD", "SHARED_PHONE",
    "FLAGGED_BY", "OWNS", "USES_DEVICE", "USES_CARD", "LIVES_AT", "HAS_PHONE",
    "INITIATED", "PAID_TO", "MEMBER_OF",
}
MAX_DEPTH = 6


def _query(name: str) -> str:
    return load_statements(CYPHER_DIR / f"{name}.cypher")[0]


def check_depth(depth: int) -> int:
    if not 1 <= depth <= MAX_DEPTH:
        raise HTTPException(422, f"depth must be between 1 and {MAX_DEPTH}")
    return depth


def check_label(label: str) -> str:
    if label not in NODE_KEYS:
        raise HTTPException(422, f"label must be one of {sorted(NODE_KEYS)}")
    return label


def check_types(types: list[str] | None) -> list[str]:
    types = types or sorted(RELATIONSHIP_TYPES - {"INITIATED", "PAID_TO"})
    bad = set(types) - RELATIONSHIP_TYPES
    if bad:
        raise HTTPException(422, f"unknown relationship types: {sorted(bad)}")
    return types


async def neighbourhood(
    driver: AsyncDriver, label: str, key: str, depth: int, types: list[str] | None, limit: int = 300
) -> dict:
    label = check_label(label)
    query = _query("neighbourhood").format(label=label, key=NODE_KEYS[label])
    records, _, _ = await driver.execute_query(
        query, key=key, depth=check_depth(depth), rel_filter="|".join(check_types(types)), limit=limit
    )
    if not records:
        raise HTTPException(404, f"{label} {key} not found")
    graph = GraphBuilder()
    graph.add(records[0]["start"])
    graph.add(records[0]["nodes"])
    graph.add(records[0]["relationships"])
    result = graph.result()
    result["start"] = records[0]["start"].element_id
    result["truncated"] = len(result["nodes"]) >= limit
    return result


async def shortest_path(driver: AsyncDriver, source: str, target: str, all_paths: bool = False) -> dict:
    query = _query("shortest_path").format(
        function="allShortestPaths" if all_paths else "shortestPath", max_hops=10
    )
    records, _, _ = await driver.execute_query(query, **{"from": source, "to": target})
    if not records:
        return {"found": False, "paths": [], "nodes": [], "edges": []}
    graph = GraphBuilder()
    for r in records:
        graph.add(r["p"])
    return {
        "found": True,
        "hops": len(records[0]["p"].relationships),
        "paths": [path_in_words(r["p"]) for r in records],
        **graph.result(),
    }


async def shared_attributes(driver: AsyncDriver, account_id: str, min_shared: int = 1) -> list[dict]:
    records, _, _ = await driver.execute_query(
        _query("shared_attributes"), id=account_id, min_shared=min_shared
    )
    return [dict(r) for r in records]


async def linked_to_fraud(driver: AsyncDriver, account_id: str, depth: int = 3) -> dict:
    query = _query("linked_to_fraud").format(depth=check_depth(depth))
    records, _, _ = await driver.execute_query(query, id=account_id)
    graph = GraphBuilder()
    for r in records:
        graph.add(r["p"])
    return {
        "linked": bool(records),
        "matches": [
            {"flagged_account": r["flagged_account"], "hops": r["hops"], "path": path_in_words(r["p"])}
            for r in records
        ],
        **graph.result(),
    }


SEARCH = """
CALL {
  MATCH (n:Account) WHERE n.id STARTS WITH $q RETURN n LIMIT 10
  UNION
  MATCH (n:Device) WHERE n.device_id STARTS WITH $q RETURN n LIMIT 10
  UNION
  MATCH (n:User) WHERE n.id STARTS WITH $q OR toLower(n.name) CONTAINS toLower($q) RETURN n LIMIT 10
  UNION
  MATCH (n:Merchant) WHERE n.id STARTS WITH $q OR toLower(n.name) CONTAINS toLower($q) RETURN n LIMIT 10
  UNION
  MATCH (n:Card) WHERE n.last4 = $q RETURN n LIMIT 10
  UNION
  MATCH (n:Address) WHERE n.id STARTS WITH $q OR toLower(n.line) CONTAINS toLower($q) RETURN n LIMIT 10
  UNION
  MATCH (n:Ring) WHERE n.ring_id STARTS WITH $q RETURN n LIMIT 10
}
RETURN n LIMIT 30
"""


async def search(driver: AsyncDriver, q: str) -> list[dict]:
    from app.db.serialize import node_dict

    records, _, _ = await driver.execute_query(SEARCH, q=q.strip())
    return [node_dict(r["n"]) for r in records]
