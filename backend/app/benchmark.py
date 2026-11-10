"""Graph vs relational benchmark (F11).

Question asked at every depth 1..6: "how many accounts are connected to this
account within N hops?", on two workloads:

- shared_attributes: SHARED_* links only (the identity graph; small clusters)
- full_network: SHARED_* plus TRANSACTED_WITH between accounts (one large
  connected network, so the reachable set grows quickly with depth)

- Neo4j: breadth-first expansion over SHARED_* relationships (APOC
  subgraphNodes), following stored pointers between nodes (index-free adjacency).
- PostgreSQL: the same links in a normalised, indexed table
  shared_link(a, b, kind), queried with a recursive CTE, i.e. one self-JOIN per hop.

Both databases hold exactly the same links (exported from Neo4j) and must
return the same counts; the benchmark checks that before timing anything.

    python -m app.benchmark            # writes data/benchmark.json and data/benchmark.png
"""

import asyncio
import json
import random
import statistics
import time
from pathlib import Path

import psycopg

from app.config import Settings, get_settings
from app.db.neo4j import create_driver

DEPTHS = range(1, 7)
SHARED = ["SHARED_DEVICE", "SHARED_CARD", "SHARED_ADDRESS", "SHARED_PHONE"]
WORKLOADS = {
    "shared_attributes": SHARED,
    "full_network": SHARED + ["TRANSACTED_WITH"],
}

EXPORT = """
MATCH (a:Account)-[r:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE|TRANSACTED_WITH]->(b:Account)
RETURN a.id AS a, b.id AS b, type(r) AS kind
"""
NEO4J_REACH = """
MATCH (a:Account {id: $id})
CALL apoc.path.subgraphNodes(a, {relationshipFilter: $filter, labelFilter: '+Account', maxLevel: $depth}) YIELD node
RETURN count(node) - 1 AS reached
"""
SQL_SETUP = """
DROP TABLE IF EXISTS shared_link;
CREATE TABLE shared_link (a text NOT NULL, b text NOT NULL, kind text NOT NULL);
"""
SQL_INDEX = "CREATE INDEX shared_link_a ON shared_link (a, kind); ANALYZE shared_link;"
SQL_REACH = """
WITH RECURSIVE reach(id, depth) AS (
    SELECT %(id)s::text, 0
  UNION
    SELECT l.b, r.depth + 1
    FROM reach r JOIN shared_link l ON l.a = r.id
    WHERE r.depth < %(depth)s AND l.kind = ANY(%(kinds)s)
)
SELECT count(DISTINCT id) - 1 FROM reach
"""


def _timed(fn, repeats: int) -> tuple[float, int]:
    times, result = [], None
    for _ in range(repeats):
        start = time.perf_counter()
        result = fn()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times), result


async def run(settings: Settings, starts: int = 20, repeats: int = 3, seed: int = 1) -> dict:
    driver = create_driver(settings)
    try:
        links, _, _ = await driver.execute_query(EXPORT)
        rows = [(r["a"], r["b"], r["kind"]) for r in links]
        # Start accounts: ring members (the interesting, connected ones) + random linked accounts.
        linked = sorted({a for a, _, _ in rows} | {b for _, b, _ in rows})
        rng = random.Random(seed)
        truth_path = Path(settings.data_dir) / "ground_truth.json"
        ring_accounts = json.loads(truth_path.read_text())["fraud_accounts"] if truth_path.exists() else []
        sample = rng.sample(ring_accounts, min(starts // 2, len(ring_accounts)))
        sample += rng.sample(linked, min(starts - len(sample), len(linked)))

        with psycopg.connect(settings.postgres_dsn, autocommit=True) as pg:
            pg.execute(SQL_SETUP)
            with pg.cursor().copy("COPY shared_link (a, b, kind) FROM STDIN") as copy:
                for a, b, kind in rows:  # store both directions: links are undirected
                    copy.write_row((a, b, kind))
                    copy.write_row((b, a, kind))
            pg.execute(SQL_INDEX)

            workloads = {}
            for workload, kinds in WORKLOADS.items():
                rel_filter = "|".join(kinds)
                results = []
                for depth in DEPTHS:
                    neo_ms, pg_ms, neo_srv, pg_srv, reached = [], [], [], [], []
                    for account in sample:
                        params = {"id": account, "depth": depth, "filter": rel_filter}
                        await driver.execute_query(NEO4J_REACH, **params)  # warm-up (plan cache)
                        times, server = [], []
                        for _ in range(repeats):
                            t0 = time.perf_counter()
                            recs, summary, _ = await driver.execute_query(NEO4J_REACH, **params)
                            times.append((time.perf_counter() - t0) * 1000)
                            server.append(summary.result_available_after + summary.result_consumed_after)
                        n_neo = recs[0]["reached"]
                        neo_ms.append(statistics.median(times))
                        neo_srv.append(statistics.median(server))
                        sql_params = {"id": account, "depth": depth, "kinds": kinds}
                        pg.execute(SQL_REACH, sql_params)  # warm-up
                        ms, n_pg = _timed(lambda: pg.execute(SQL_REACH, sql_params).fetchone()[0], repeats)
                        pg_ms.append(ms)
                        plan = pg.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + SQL_REACH, sql_params).fetchone()[0]
                        pg_srv.append(plan[0]["Execution Time"])
                        if n_neo != n_pg:
                            raise AssertionError(
                                f"{workload}: mismatch for {account} at depth {depth}: {n_neo} vs {n_pg}")
                        reached.append(n_neo)
                    results.append({
                        "depth": depth,
                        "neo4j_ms": round(statistics.mean(neo_ms), 2),
                        "postgres_ms": round(statistics.mean(pg_ms), 2),
                        "neo4j_server_ms": round(statistics.mean(neo_srv), 2),
                        "postgres_server_ms": round(statistics.mean(pg_srv), 2),
                        "avg_accounts_reached": round(statistics.mean(reached), 1),
                    })
                workloads[workload] = results
    finally:
        await driver.close()
    return {
        "available": True,
        "links": len(rows),
        "start_accounts": len(sample),
        "repeats": repeats,
        "method": {
            "neo4j": "APOC subgraphNodes BFS over SHARED_* relationships",
            "postgres": "recursive CTE over indexed shared_link(a, b) table (both directions)",
        },
        "note": ("*_ms are measured from the Python client and include one network round trip; "
                 "*_server_ms are the databases' own execution times (Neo4j result summary, "
                 "PostgreSQL EXPLAIN ANALYZE)."),
        "workloads": workloads,
    }


def plot(result: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    titles = {"shared_attributes": "Shared attributes only", "full_network": "Shared attributes + money transfers"}
    fig, axes = plt.subplots(1, len(result["workloads"]), figsize=(11, 4), dpi=120)
    for ax, (name, rows) in zip(axes, result["workloads"].items()):
        depths = [r["depth"] for r in rows]
        ax.plot(depths, [r["neo4j_ms"] for r in rows], marker="o", color="#2563eb", label="Neo4j (graph traversal)")
        ax.plot(depths, [r["postgres_ms"] for r in rows], marker="s", color="#d97706", label="PostgreSQL (recursive CTE)")
        ax.set_xlabel("Traversal depth (hops)")
        ax.set_ylabel("Mean query time (ms)")
        ax.set_title(titles.get(name, name))
        ax.grid(alpha=0.3)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    axes[0].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path)


def main() -> None:
    settings = get_settings()
    result = asyncio.run(run(settings))
    data = Path(settings.data_dir)
    (data / "benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    plot(result, data / "benchmark.png")
    for name, rows in result["workloads"].items():
        print(name)
        print(f"{'depth':>5}{'neo4j ms':>10}{'pg ms':>8}{'neo4j srv':>11}{'pg srv':>8}{'reached':>9}")
        for r in rows:
            print(f"{r['depth']:>5}{r['neo4j_ms']:>10}{r['postgres_ms']:>8}{r['neo4j_server_ms']:>11}"
                  f"{r['postgres_server_ms']:>8}{r['avg_accounts_reached']:>9}")
    print(f"Wrote {data / 'benchmark.json'} and {data / 'benchmark.png'}")


if __name__ == "__main__":
    main()
