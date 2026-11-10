"""Command-line entry point.

    python -m app.datagen                    # generate, write data/ground_truth.json
    python -m app.datagen --load --wipe      # ...and replace the Neo4j graph with it
    python -m app.datagen --users 500 --accounts 700 --transactions 5000 --load --wipe

Run `python -m app.datagen --help` for all options.
"""

import argparse
import asyncio
import json
import time
from collections import Counter
from dataclasses import asdict, fields
from pathlib import Path

from app.config import Settings, get_settings
from app.datagen.builder import Dataset
from app.datagen.generator import GenParams, generate
from app.datagen.loader import SEED_ANALYST, graph_counts, load, wipe
from app.db.neo4j import create_driver
from app.db.schema import apply_schema


def ground_truth(ds: Dataset, params: GenParams) -> dict:
    return {
        "seed": params.seed,
        "params": asdict(params),
        "stats": {
            "users": len(ds.users),
            "accounts": len(ds.accounts),
            "merchants": len(ds.merchants),
            "transactions": len(ds.transactions),
            "devices": len(ds.devices),
            "cards": len(ds.cards),
            "addresses": len(ds.addresses),
            "rings": len(ds.rings),
            "ring_accounts": sum(len(r["accounts"]) for r in ds.rings),
            "flagged_accounts": len(ds.flags),
        },
        "rings": ds.rings,
        "fraud_accounts": sorted(a for r in ds.rings for a in r["accounts"]),
        "flagged_accounts": sorted(f["account"] for f in ds.flags),
        "flagged_by": SEED_ANALYST["username"],
    }


async def load_into_neo4j(settings: Settings, ds: Dataset, wipe_first: bool) -> dict[str, int]:
    driver = create_driver(settings)
    try:
        if wipe_first:
            await wipe(driver)
        await apply_schema(driver)
        await load(driver, ds)
        return await graph_counts(driver)
    finally:
        await driver.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.datagen",
        description="Generate synthetic FraudMesh data with planted fraud rings.",
    )
    for f in fields(GenParams):
        parser.add_argument(f"--{f.name.replace('_', '-')}", type=type(f.default), default=f.default)
    parser.add_argument("--out", default="data", help="directory for ground_truth.json")
    parser.add_argument("--load", action="store_true", help="load the data into Neo4j")
    parser.add_argument("--wipe", action="store_true", help="delete everything in Neo4j first")
    parser.add_argument("--neo4j-uri", help="override NEO4J_URI (e.g. bolt://localhost:7687)")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.neo4j_uri:
        settings = settings.model_copy(update={"neo4j_uri": args.neo4j_uri})
    params = GenParams(**{f.name: getattr(args, f.name) for f in fields(GenParams)})

    start = time.perf_counter()
    ds = generate(params, settings.pii_hash_key)
    truth = ground_truth(ds, params)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ground_truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    print(f"Generated in {time.perf_counter() - start:.1f}s: {truth['stats']}")
    print(f"Planted rings by type: {dict(Counter(r['type'] for r in ds.rings))}")
    print(f"Ground truth written to {out / 'ground_truth.json'}")

    if args.load:
        start = time.perf_counter()
        counts = asyncio.run(load_into_neo4j(settings, ds, args.wipe))
        print(f"Loaded into Neo4j ({settings.neo4j_uri}) in {time.perf_counter() - start:.1f}s")
        for name, n in counts.items():
            print(f"  {name:<16}{n:>8}")


if __name__ == "__main__":
    main()
