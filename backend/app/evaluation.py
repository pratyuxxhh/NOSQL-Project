"""Detection quality against the planted ground truth (F10).

Compares three approaches at the ACCOUNT level:
  1. rules only        - any transaction with rule_score >= flag threshold
  2. graph detection   - members of detected rings (not marked false positive)
  3. graph + propagation - (2) plus accounts whose propagated risk crossed the threshold

Accounts flagged in the seed data are already-known fraud; they are excluded
from both the truth and the predictions, so only NEW detections are scored.
Also reports ring-level recall: a planted ring counts as found when at least
half of its accounts sit in one detected ring.

    python -m app.evaluation      # writes data/evaluation.json
"""

import asyncio
import json
from pathlib import Path

from neo4j import AsyncDriver

from app.config import Settings, get_settings
from app.db.neo4j import create_driver
from app.services.settings_store import SettingsStore

PREDICTIONS = """
CALL {
  MATCH (a:Account)-[:INITIATED]->(t:Transaction) WHERE t.rule_score >= $flag_threshold
  RETURN collect(DISTINCT a.id) AS rules
}
CALL {
  MATCH (a:Account)-[:MEMBER_OF]->(g:Ring) WHERE g.status <> 'FALSE_POSITIVE'
  RETURN collect(DISTINCT a.id) AS graph
}
CALL {
  MATCH (a:Account) WHERE a.propagated_risk >= $surface
  RETURN collect(a.id) AS propagated
}
CALL {
  MATCH (g:Ring)<-[:MEMBER_OF]-(a:Account) WHERE g.status <> 'FALSE_POSITIVE'
  RETURN collect({ring: g.ring_id, ids: [a.id]}) AS memberships
}
RETURN rules, graph, propagated, memberships
"""


def prf(predicted: set[str], truth: set[str]) -> dict:
    tp = len(predicted & truth)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "predicted": len(predicted),
        "true_positives": tp,
        "false_positives": len(predicted - truth),
        "false_negatives": len(truth - predicted),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def rings_found(gt_rings: list[dict], detected: dict[str, set[str]]) -> dict:
    found = {}
    for ring in gt_rings:
        members = set(ring["accounts"])
        best = max((len(members & ids) / len(members) for ids in detected.values()), default=0.0)
        found[ring["ring_id"]] = {"type": ring["type"], "best_overlap": round(best, 2), "found": best >= 0.5}
    by_type: dict[str, list[bool]] = {}
    for item in found.values():
        by_type.setdefault(item["type"], []).append(item["found"])
    return {
        "found": sum(v["found"] for v in found.values()),
        "total": len(found),
        "by_type": {t: f"{sum(v)}/{len(v)}" for t, v in by_type.items()},
        "rings": found,
    }


async def evaluate(driver: AsyncDriver, truth: dict) -> dict:
    store = SettingsStore(driver)
    settings = await store.load()
    records, _, _ = await driver.execute_query(
        PREDICTIONS,
        flag_threshold=settings.rules.flag_threshold,
        surface=settings.propagation.surface_threshold,
    )
    r = records[0]
    known = set(truth["flagged_accounts"])
    fraud = set(truth["fraud_accounts"]) - known
    rules = set(r["rules"]) - known
    graph = set(r["graph"]) - known
    graph_prop = (set(r["graph"]) | set(r["propagated"])) - known
    detected: dict[str, set[str]] = {}
    for m in r["memberships"]:
        detected.setdefault(m["ring"], set()).update(m["ids"])
    return {
        "truth": {"fraud_accounts": len(fraud), "known_flagged_excluded": len(known),
                  "accounts_total": truth["stats"]["accounts"]},
        "account_level": {
            "rules_only": prf(rules, fraud),
            "graph_detection": prf(graph, fraud),
            "graph_plus_propagation": prf(graph_prop, fraud),
        },
        "ring_level": rings_found(truth["rings"], detected),
        "settings": {
            "flag_threshold": settings.rules.flag_threshold,
            "surface_threshold": settings.propagation.surface_threshold,
            "algorithm": settings.detection.algorithm.value,
        },
    }


async def _main(settings: Settings) -> dict:
    data = Path(settings.data_dir)
    truth = json.loads((data / "ground_truth.json").read_text(encoding="utf-8"))
    driver = create_driver(settings)
    try:
        result = await evaluate(driver, truth)
    finally:
        await driver.close()
    (data / "evaluation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    result = asyncio.run(_main(get_settings()))
    print(f"{'approach':<26}{'precision':>10}{'recall':>8}{'f1':>7}{'TP':>6}{'FP':>6}")
    for name, m in result["account_level"].items():
        print(f"{name:<26}{m['precision']:>10}{m['recall']:>8}{m['f1']:>7}{m['true_positives']:>6}{m['false_positives']:>6}")
    ring = result["ring_level"]
    print(f"Planted rings found: {ring['found']}/{ring['total']} {ring['by_type']}")


if __name__ == "__main__":
    main()
