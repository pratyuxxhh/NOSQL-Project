"""One-command demo setup (`make seed`):

  1. generate synthetic data with planted rings and load it (replacing the graph)
  2. rule-score every transaction (the baseline)
  3. create the default users (admin / analyst / viewer) and a simulator API key
  4. run risk propagation and ring detection once
  5. raise HIGH_RULE_SCORE alerts for the worst rule hits

    python -m app.seed                 # full demo dataset
    python -m app.seed --users-only    # only (re)create users and the API key
"""

import argparse
import asyncio
import json
import time
from dataclasses import fields
from pathlib import Path

from neo4j import AsyncDriver

from app.config import Settings, get_settings
from app.datagen.__main__ import ground_truth
from app.datagen.generator import GenParams, generate
from app.datagen.loader import load, wipe
from app.datagen.scoring import write_scores
from app.db.neo4j import create_driver
from app.db.schema import apply_schema
from app.models.graph import AlertType, Role, Severity
from app.security.api_keys import create_api_key
from app.security.passwords import hash_password
from app.services.alerting import AlertService
from app.services.flagging import propagate_and_alert
from app.services.ring_detection import detect_rings
from app.services.settings_store import SettingsStore
from app.websocket.hub import Hub

DEFAULT_USERS = [
    ("admin", "Admin User", Role.ADMIN),
    ("analyst", "Fraud Analyst", Role.ANALYST),
    ("viewer", "Read-only Viewer", Role.VIEWER),
]

UPSERT_USER = """
MERGE (u:Analyst {username: $username})
ON CREATE SET u.id = randomUUID(), u.created_at = datetime()
SET u.name = $name, u.role = $role, u.active = true, u.password_hash = $hash
"""

TOP_RULE_HITS = """
MATCH (t:Transaction) WHERE t.rule_score >= $threshold
RETURN t.id AS id, t.rule_score AS score, t.rule_reasons AS reasons
ORDER BY t.timestamp DESC LIMIT $limit
"""


async def seed_users(driver: AsyncDriver, settings: Settings) -> str:
    password_hash = hash_password(settings.default_admin_password)
    for username, name, role in DEFAULT_USERS:
        await driver.execute_query(UPSERT_USER, username=username, name=name, role=role.value, hash=password_hash)
    await driver.execute_query("MATCH (k:ApiKey {name: 'simulator'}) SET k.active = false")
    key = await create_api_key(driver, "simulator", rate_limit_per_min=60_000)
    path = Path(settings.data_dir) / "simulator_api_key.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key["key"], encoding="utf-8")
    return str(path)


async def run(settings: Settings, params: GenParams, users_only: bool) -> None:
    driver = create_driver(settings)
    try:
        await apply_schema(driver)
        if not users_only:
            start = time.perf_counter()
            ds = generate(params, settings.pii_hash_key)
            out = Path(settings.data_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "ground_truth.json").write_text(json.dumps(ground_truth(ds, params), indent=2), encoding="utf-8")
            print(f"Generated {len(ds.transactions)} transactions, {len(ds.rings)} planted rings")
            await wipe(driver)
            await apply_schema(driver)
            await load(driver, ds)
            print(f"Loaded into Neo4j in {time.perf_counter() - start:.1f}s")
            store = SettingsStore(driver)
            await store.save(store.current)  # reset runtime settings to defaults
            print("Rule scoring:", await write_scores(driver, ds, store.current.rules))

        key_path = await seed_users(driver, settings)
        print(f"Users admin / analyst / viewer (password from DEFAULT_ADMIN_PASSWORD); API key in {key_path}")

        if not users_only:
            store = SettingsStore(driver)
            await store.load()
            alerts = AlertService(driver, Hub())
            summary = await propagate_and_alert(driver, store.current, alerts)
            print(f"Propagation: {summary['affected']} accounts affected, "
                  f"{len(summary['pre_emptive'])} pre-emptive detections")
            print("Ring detection:", await detect_rings(driver, store.current, alerts))
            hits, _, _ = await driver.execute_query(
                TOP_RULE_HITS, threshold=store.current.rules.flag_threshold, limit=40
            )
            for h in hits:
                await alerts.raise_alert(
                    AlertType.HIGH_RULE_SCORE,
                    Severity.HIGH if h["score"] >= 80 else Severity.MEDIUM,
                    f"Rule score {h['score']}: " + "; ".join(h["reasons"]),
                    "Transaction",
                    h["id"],
                )
            print(f"Raised {len(hits)} HIGH_RULE_SCORE alerts")
    finally:
        await driver.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.seed", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    for f in fields(GenParams):
        parser.add_argument(f"--{f.name.replace('_', '-')}", type=type(f.default), default=f.default)
    parser.add_argument("--users-only", action="store_true")
    parser.add_argument("--neo4j-uri")
    parser.add_argument("--data-dir")
    args = parser.parse_args(argv)
    settings = get_settings()
    updates = {k: v for k, v in {"neo4j_uri": args.neo4j_uri, "data_dir": args.data_dir}.items() if v}
    settings = settings.model_copy(update=updates)
    params = GenParams(**{f.name: getattr(args, f.name) for f in fields(GenParams)})
    asyncio.run(run(settings, params, args.users_only))


if __name__ == "__main__":
    main()
