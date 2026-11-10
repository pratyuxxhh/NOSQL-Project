"""Automated fraud ring detection with Neo4j Graph Data Science (F5).

1. Project Account nodes and account-to-account links (SHARED_*, TRANSACTED_WITH)
   into an in-memory GDS graph, each link weighted by how strongly it suggests
   a common operator.
2. Weakly Connected Components over the SHARED_* links only (identity links):
   accounts tied together by devices/cards/addresses/phones. A component small
   enough to be a ring (<= max_ring_size) is taken as one candidate group.
3. Louvain or Label Propagation over all links: splits components that are too
   big to be one ring into tightly knit communities (`community_id`).
   Running community detection on everything at once would let the ring's
   ordinary money links (victims paying mules, a deposit entering a chain)
   pull ring members into large communities of normal customers.
4. PageRank: `hub_score` marks the most central account inside each ring.
5. A group becomes a :Ring when it is big enough AND either contains a flagged
   account, OR is densely linked by shared attributes AND made up mostly of
   newly opened accounts. (Families sharing an address are dense too, but
   their accounts are old; rings run on freshly created identities.)

The projection is always dropped afterwards so no in-memory graph leaks.
"""

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass

from neo4j import AsyncDriver

from app.models.graph import AlertType, RingAlgorithm, Severity
from app.models.settings import DetectionSettings, RuntimeSettings
from app.services.alerting import AlertService

logger = logging.getLogger(__name__)

# Each run projects under its own name, so a scheduled run and an on-demand run
# (or the seed script) never collide on one in-memory graph.
GRAPH_PREFIX = "fraudmesh-accounts-"
SHARED_TYPES = ("SHARED_DEVICE", "SHARED_CARD", "SHARED_ADDRESS", "SHARED_PHONE")

# Cypher projection: every account-to-account link, undirected, weighted by type.
PROJECT = """
MATCH (a:Account)-[r:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE|TRANSACTED_WITH]->(b:Account)
WITH gds.graph.project($name, a, b,
       {relationshipType: type(r), relationshipProperties: {weight: coalesce($weights[type(r)], 0.1)}},
       {undirectedRelationshipTypes: ['*']}) AS g
RETURN g.nodeCount AS nodes, g.relationshipCount AS relationships
"""
DROP = "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName"
WCC = (
    "CALL gds.wcc.write($name, {writeProperty: 'component_id', relationshipTypes: $shared_types}) "
    "YIELD componentCount RETURN componentCount"
)
COMMUNITY = {
    RingAlgorithm.LOUVAIN: (
        "CALL gds.louvain.write($name, {writeProperty: 'community_id', "
        "relationshipWeightProperty: 'weight'}) YIELD communityCount RETURN communityCount"
    ),
    RingAlgorithm.LPA: (
        "CALL gds.labelPropagation.write($name, {writeProperty: 'community_id', "
        "relationshipWeightProperty: 'weight'}) YIELD communityCount RETURN communityCount"
    ),
}
PAGERANK = (
    "CALL gds.pageRank.write($name, {writeProperty: 'hub_score', "
    "relationshipWeightProperty: 'weight'}) YIELD nodePropertiesWritten RETURN nodePropertiesWritten"
)
CLEAR_COMMUNITIES = (
    "MATCH (a:Account) WHERE a.community_id IS NOT NULL OR a.component_id IS NOT NULL "
    "REMOVE a.community_id, a.component_id, a.hub_score"
)

CANDIDATES = """
MATCH (a:Account) WHERE a.component_id IS NOT NULL
WITH a.component_id AS component, collect(a) AS component_members
UNWIND component_members AS a
WITH a, size(component_members) AS component_size
// Small identity clusters are candidates as they are; big ones are split by community.
WITH CASE WHEN component_size <= $max_size THEN 'C' + toString(a.component_id)
          ELSE 'L' + toString(a.community_id) END AS cid, a
WITH cid, collect(a) AS members
WHERE size(members) >= $min_size AND size(members) <= $max_size
RETURN cid,
       [m IN members | m.id] AS ids,
       size([m IN members WHERE m.is_flagged]) AS flagged,
       reduce(s = 0.0, m IN members | s + coalesce(m.combined_risk, m.risk_score, 0.0)) / size(members) AS avg_risk,
       [m IN members | coalesce(m.hub_score, 0.0)] AS hub_scores,
       toFloat(size([m IN members WHERE m.opened_at >= datetime() - duration({days: $new_days})]))
         / size(members) AS new_ratio
"""

# Shared-attribute links inside each candidate community, plus its money volume.
INTERNAL = """
UNWIND $groups AS g
UNWIND g.ids AS id
MATCH (a:Account {id: id})
OPTIONAL MATCH (a)-[r:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE]->(b:Account)
WHERE b.id IN g.ids
OPTIONAL MATCH (a)-[:INITIATED]->(t:Transaction)
WITH g, a, r, b, sum(t.amount) AS volume
RETURN g.cid AS cid,
       collect(CASE WHEN r IS NULL THEN null ELSE
         {a: a.id, b: b.id, type: type(r),
          key: coalesce(r.device_id, r.card_hash, r.address_id, r.number_hash)} END) AS edges,
       collect(DISTINCT {id: a.id, volume: volume}) AS volumes
"""

REVIEWED_RINGS = """
MATCH (g:Ring) WHERE g.status <> 'NEW'
OPTIONAL MATCH (a:Account)-[:MEMBER_OF]->(g)
RETURN g.ring_id AS ring_id, collect(a.id) AS ids
"""

UPSERT_RING = """
MERGE (g:Ring {ring_id: $ring_id})
ON CREATE SET g.status = 'NEW', g.detected_at = datetime(), g.created = true
ON MATCH SET g.created = false
SET g += $props, g.last_seen_at = datetime()
WITH g
OPTIONAL MATCH (g)<-[old:MEMBER_OF]-()
DELETE old
WITH DISTINCT g
UNWIND $ids AS id
MATCH (a:Account {id: id})
MERGE (a)-[:MEMBER_OF]->(g)
WITH DISTINCT g
RETURN g.created AS created
"""
DELETE_STALE = "MATCH (g:Ring {status: 'NEW'}) WHERE NOT g.ring_id IN $keep DETACH DELETE g"


@dataclass
class Candidate:
    cid: str
    ids: list[str]
    flagged: int
    avg_risk: float
    hub: str | None
    new_ratio: float = 0.0


def ring_metrics(ids: list[str], edges: list[dict]) -> dict:
    """Density = share of member pairs linked by at least one shared attribute."""
    pairs = {tuple(sorted((e["a"], e["b"]))) for e in edges}
    n = len(ids)
    possible = n * (n - 1) / 2
    shared = {t: {e["key"] for e in edges if e["type"] == t} for t in SHARED_TYPES}
    return {
        "density": round(len(pairs) / possible, 4) if possible else 0.0,
        "shared_devices": len(shared["SHARED_DEVICE"]),
        "shared_cards": len(shared["SHARED_CARD"]),
        "shared_addresses": len(shared["SHARED_ADDRESS"]),
        "shared_phones": len(shared["SHARED_PHONE"]),
    }


def is_suspicious(size: int, density: float, flagged: int, new_ratio: float, settings: DetectionSettings) -> bool:
    """Suspicion criteria: big enough AND (known fraud inside OR (dense shared-attribute
    links AND mostly new accounts))."""
    if size < settings.min_ring_size:
        return False
    if flagged >= 1:
        return True
    return density >= settings.density_threshold and new_ratio >= settings.min_new_account_ratio


def ring_id_for(ids: list[str]) -> str:
    """Stable ID from the member set, so re-detecting the same ring updates it."""
    return "R-" + hashlib.sha1(",".join(sorted(ids)).encode()).hexdigest()[:10]


def overlaps(ids: list[str], other: list[str], threshold: float = 0.5) -> bool:
    if not ids or not other:
        return False
    return len(set(ids) & set(other)) / min(len(ids), len(other)) >= threshold


async def detect_rings(
    driver: AsyncDriver,
    settings: RuntimeSettings,
    alerts: AlertService | None = None,
    algorithm: RingAlgorithm | None = None,
) -> dict:
    det = settings.detection
    algorithm = algorithm or det.algorithm
    start = time.perf_counter()
    graph_name = GRAPH_PREFIX + uuid.uuid4().hex[:8]

    try:
        projected, _, _ = await driver.execute_query(
            PROJECT, name=graph_name, weights=settings.propagation.weights
        )
        if not projected or projected[0]["nodes"] == 0:
            return {"rings": 0, "new_rings": 0, "algorithm": algorithm.value, "projected_nodes": 0}
        await driver.execute_query(CLEAR_COMMUNITIES)
        wcc, _, _ = await driver.execute_query(WCC, name=graph_name, shared_types=list(SHARED_TYPES))
        communities, _, _ = await driver.execute_query(COMMUNITY[algorithm], name=graph_name)
        await driver.execute_query(PAGERANK, name=graph_name)
    finally:
        await driver.execute_query(DROP, name=graph_name)

    records, _, _ = await driver.execute_query(
        CANDIDATES, min_size=det.min_ring_size, max_size=det.max_ring_size, new_days=det.new_account_days
    )
    candidates = [
        Candidate(r["cid"], r["ids"], r["flagged"], r["avg_risk"],
                  max(zip(r["hub_scores"], r["ids"]))[1] if r["ids"] else None, r["new_ratio"])
        for r in records
    ]
    internal, _, _ = await driver.execute_query(
        INTERNAL, groups=[{"cid": c.cid, "ids": c.ids} for c in candidates]
    )
    by_cid = {r["cid"]: r for r in internal}
    reviewed, _, _ = await driver.execute_query(REVIEWED_RINGS)

    keep, new_rings = [], 0
    for c in candidates:
        info = by_cid.get(c.cid)
        edges = [e for e in (info["edges"] if info else []) if e]
        metrics = ring_metrics(c.ids, edges)
        if not is_suspicious(len(c.ids), metrics["density"], c.flagged, c.new_ratio, det):
            continue
        if any(overlaps(c.ids, r["ids"]) for r in reviewed):
            continue  # already under review / decided: leave the analyst's ring alone
        ring_id = ring_id_for(c.ids)
        volume = sum((v["volume"] or 0) for v in (info["volumes"] if info else []))
        props = {
            "algorithm": algorithm.value,
            "size": len(c.ids),
            "avg_risk": round(float(c.avg_risk or 0), 4),
            "flagged_members": c.flagged,
            "hub_account": c.hub,
            "new_account_ratio": round(c.new_ratio, 2),
            "total_volume": round(float(volume), 2),
            **metrics,
        }
        result, _, _ = await driver.execute_query(UPSERT_RING, ring_id=ring_id, props=props, ids=c.ids)
        keep.append(ring_id)
        if result and result[0]["created"]:
            new_rings += 1
            if alerts:
                await alerts.raise_alert(
                    AlertType.RING_DETECTED,
                    Severity.CRITICAL if c.flagged else Severity.HIGH,
                    f"{len(c.ids)} accounts linked by {metrics['shared_devices']} devices, "
                    f"{metrics['shared_cards']} cards, {metrics['shared_addresses']} addresses, "
                    f"{metrics['shared_phones']} phones (density {metrics['density']:.2f}"
                    f"{', contains known fraud' if c.flagged else ''}).",
                    "Ring",
                    ring_id,
                )
    await driver.execute_query(DELETE_STALE, keep=keep)

    summary = {
        "algorithm": algorithm.value,
        "projected_nodes": projected[0]["nodes"],
        "projected_relationships": projected[0]["relationships"],
        "components": wcc[0]["componentCount"],
        "communities": communities[0]["communityCount"],
        "candidates": len(candidates),
        "rings": len(keep),
        "new_rings": new_rings,
        "duration_ms": round((time.perf_counter() - start) * 1000, 1),
    }
    logger.info("ring detection done", extra=summary)
    return summary
