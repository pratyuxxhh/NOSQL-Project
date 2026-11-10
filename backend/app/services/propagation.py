"""Risk propagation engine (F7).

When an account is flagged, its risk flows outward through the graph:

    contribution = source_risk x (product of edge weights on the path) x decay^hops

For each (source, target) pair only the strongest path counts, so many
parallel paths from ONE fraudster are not mistaken for independent evidence.
Contributions from DIFFERENT sources are combined with noisy-OR:

    propagated_risk = 1 - product(1 - c_i)        (always within [0, 1])

The account's overall risk then combines its own risk with what it received:

    combined_risk = 1 - (1 - risk_score) x (1 - propagated_risk)
"""

import logging
import math
from dataclasses import dataclass

from neo4j import AsyncDriver

from app.models.settings import PropagationSettings, RuntimeSettings

logger = logging.getLogger(__name__)

PROPAGATING_TYPES = ("SHARED_DEVICE", "SHARED_CARD", "SHARED_ADDRESS", "SHARED_PHONE", "TRANSACTED_WITH")


@dataclass(frozen=True)
class PathHit:
    source: str
    source_risk: float
    target: str
    rel_types: tuple[str, ...]
    node_ids: tuple[str, ...]  # source ... target


def contribution(hit: PathHit, settings: PropagationSettings) -> float:
    weight = math.prod(settings.weights.get(t, 0.0) for t in hit.rel_types)
    return hit.source_risk * weight * settings.decay ** len(hit.rel_types)


def noisy_or(values: list[float]) -> float:
    return min(1.0, 1.0 - math.prod(1.0 - v for v in values))


def describe(hit: PathHit, value: float) -> str:
    parts = [hit.node_ids[0]]
    for rel, node in zip(hit.rel_types, hit.node_ids[1:]):
        parts += [f"-{rel}-", node]
    return f"{' '.join(parts)} ({value:.2f})"


def aggregate(hits: list[PathHit], settings: PropagationSettings) -> dict[str, tuple[float, list[str]]]:
    """target -> (propagated_risk, top-3 explanation paths)."""
    best: dict[str, dict[str, tuple[float, PathHit]]] = {}
    for hit in hits:
        if hit.target == hit.source:
            continue
        value = contribution(hit, settings)
        per_source = best.setdefault(hit.target, {})
        if value > per_source.get(hit.source, (0.0, None))[0]:
            per_source[hit.source] = (value, hit)
    result = {}
    for target, per_source in best.items():
        ranked = sorted(per_source.values(), key=lambda item: -item[0])
        result[target] = (
            round(noisy_or([v for v, _ in ranked]), 4),
            [describe(hit, v) for v, hit in ranked[:3]],
        )
    return result


def combined(own: float, propagated: float) -> float:
    return 1.0 - (1.0 - own) * (1.0 - propagated)


# Every path of up to N hops from a flagged account through account-to-account
# links. Depth cannot be a Cypher parameter, so it is validated (1-5) and inlined.
PATHS_QUERY = """
MATCH (s:Account {{is_flagged: true}})
MATCH p = (s)-[:{types}*1..{depth}]-(t:Account)
WHERE t <> s AND all(n IN nodes(p) WHERE n:Account)
RETURN s.id AS source, coalesce(s.risk_score, 1.0) AS risk, t.id AS target,
       [r IN relationships(p) | type(r)] AS types, [n IN nodes(p) | n.id] AS ids
"""

RESET_QUERY = """
MATCH (a:Account)
WHERE a.propagated_risk > 0 OR a.pre_emptive = true OR a.combined_risk IS NULL
SET a.propagated_risk = 0.0, a.risk_explanation = [], a.pre_emptive = false,
    a.combined_risk = coalesce(a.risk_score, 0.0)
"""

WRITE_QUERY = """
UNWIND $rows AS r
MATCH (a:Account {id: r.id})
SET a.propagated_risk = r.risk, a.risk_explanation = r.explanation,
    a.combined_risk = 1 - (1 - coalesce(a.risk_score, 0.0)) * (1 - r.risk)
"""

# Surfaced accounts that no rule caught and nobody flagged: pre-emptive detections.
PRE_EMPTIVE_QUERY = """
UNWIND $ids AS id
MATCH (a:Account {id: id})
WHERE NOT coalesce(a.is_flagged, false)
OPTIONAL MATCH (a)-[:INITIATED]->(t:Transaction)
WITH a, max(coalesce(t.rule_score, 0)) AS max_rule
WHERE max_rule < $flag_threshold
SET a.pre_emptive = true
RETURN a.id AS id, a.propagated_risk AS risk, a.risk_explanation AS explanation
"""


async def run_propagation(driver: AsyncDriver, settings: RuntimeSettings) -> dict:
    """Recompute propagated risk for the whole graph from all flagged accounts.

    A full recompute (rather than an incremental update) keeps noisy-OR exact:
    each target always sees every source exactly once.
    """
    prop = settings.propagation
    query = PATHS_QUERY.format(types="|".join(PROPAGATING_TYPES), depth=int(prop.max_depth))
    records, _, _ = await driver.execute_query(query)
    hits = [
        PathHit(r["source"], float(r["risk"]), r["target"], tuple(r["types"]), tuple(r["ids"]))
        for r in records
    ]
    result = aggregate(hits, prop)
    await driver.execute_query(RESET_QUERY)
    rows = [{"id": t, "risk": risk, "explanation": expl} for t, (risk, expl) in result.items()]
    if rows:
        await driver.execute_query(WRITE_QUERY, rows=rows)
    surfaced = [t for t, (risk, _) in result.items() if risk >= prop.surface_threshold]
    pre_emptive, _, _ = await driver.execute_query(
        PRE_EMPTIVE_QUERY, ids=surfaced, flag_threshold=settings.rules.flag_threshold
    )
    summary = {
        "sources": len({h.source for h in hits}),
        "paths": len(hits),
        "affected": len(result),
        "surfaced": len(surfaced),
        "pre_emptive": [dict(r) for r in pre_emptive],
    }
    logger.info("propagation done", extra={k: v for k, v in summary.items() if k != "pre_emptive"})
    return summary
