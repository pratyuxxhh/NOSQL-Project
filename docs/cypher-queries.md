# Key Cypher Queries

Every query FraudMesh relies on, with what it does and why it is written that way. The query files live in [backend/app/cypher/](../backend/app/cypher/); service code that embeds Cypher is linked per query.

**Rules followed everywhere:** user input is always a `$parameter`. Labels, relationship types and path-length bounds cannot be parameters in Cypher, so they come from whitelists in code (e.g. `depth` must be 1–6) before being placed in the query text.

---

## 1. Derive SHARED_DEVICE edges

[derive_shared_edges.cypher](../backend/app/cypher/derive_shared_edges.cypher)

```cypher
MATCH (a1:Account)-[:USES_DEVICE]->(d:Device)<-[:USES_DEVICE]-(a2:Account)
WHERE a1.id < a2.id
  AND NOT EXISTS { (a1)<-[:OWNS]-(:User)-[:OWNS]->(a2) }
MERGE (a1)-[r:SHARED_DEVICE {device_id: d.device_id}]->(a2)
  ON CREATE SET r.since = datetime();
```

Turns the 2-hop pattern account → device ← account into a direct 1-hop edge. `a1.id < a2.id` fixes the direction so each pair is stored once; the `NOT EXISTS` subquery skips accounts of the same owner; `MERGE` on `device_id` makes re-running harmless. The same pattern exists for cards, addresses and phones (the last two look through `OWNS` because they belong to the User).

## 2. Neighbourhood: everything within N hops

[neighbourhood.cypher](../backend/app/cypher/neighbourhood.cypher)

```cypher
MATCH (start:Account {id: $key})
CALL apoc.path.subgraphAll(start, {maxLevel: $depth, relationshipFilter: $rel_filter, limit: $limit})
YIELD nodes, relationships
RETURN start, nodes, relationships
```

The textbook version is `MATCH p = (a)-[*1..6]-(x)`, but that enumerates every *path*, and inside a dense ring the number of paths explodes (a 6-account ring with parallel card edges has millions of 6-hop paths). APOC's `subgraphAll` does a breadth-first search that visits each node once, so cost grows with the number of nodes reached, not paths.

## 3. Shortest path: how are two accounts linked?

[shortest_path.cypher](../backend/app/cypher/shortest_path.cypher)

```cypher
MATCH (a:Account {id: $from}), (b:Account {id: $to})
MATCH p = shortestPath((a)-[:OWNS|USES_DEVICE|USES_CARD|LIVES_AT|HAS_PHONE|TRANSACTED_WITH*..10]-(b))
WHERE none(n IN nodes(p) WHERE n:Merchant)
RETURN p LIMIT 5
```

Follows the **raw** attribute links rather than derived `SHARED_*` edges, so the answer names the thing they share: `A2 -[USES_DEVICE]- Device D1 -[USES_DEVICE]- A3`. Merchants are excluded because almost everyone shops somewhere; a path through a supermarket explains nothing. `allShortestPaths` is used when the caller asks for all paths.

## 4. Accounts sharing at least K attributes

[shared_attributes.cypher](../backend/app/cypher/shared_attributes.cypher)

```cypher
MATCH (a:Account {id: $id})-[r:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE]-(o:Account)
WITH o, count(r) AS shared, collect(DISTINCT type(r)) AS kinds
WHERE shared >= $min_shared
RETURN o.id AS account, shared, kinds
ORDER BY shared DESC
```

Because there is one derived edge per shared attribute, "how many attributes do they share?" is just `count(r)`.

## 5. Is this account linked to known fraud?

[linked_to_fraud.cypher](../backend/app/cypher/linked_to_fraud.cypher)

```cypher
MATCH (a:Account {id: $id})
MATCH (f:Account {is_flagged: true}) WHERE f <> a
MATCH p = shortestPath((a)-[:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE|TRANSACTED_WITH*..3]-(f))
RETURN f.id AS flagged_account, length(p) AS hops, p
ORDER BY hops LIMIT 5
```

Uses the `is_flagged` index to find the (few) flagged accounts, then a bidirectional shortest-path search to each.

## 6. Risk propagation paths

[propagation.py](../backend/app/services/propagation.py)

```cypher
MATCH (s:Account {is_flagged: true})
MATCH p = (s)-[:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE|TRANSACTED_WITH*1..3]-(t:Account)
WHERE t <> s AND all(n IN nodes(p) WHERE n:Account)
RETURN s.id AS source, s.risk_score AS risk, t.id AS target,
       [r IN relationships(p) | type(r)] AS types, [n IN nodes(p) | n.id] AS ids
```

Here every path *is* wanted (the strongest one per source is chosen in Python), and depth is capped at 3, which keeps the count small. The relationship types on each path give the weights; the node ids become the human-readable explanation.

## 7. GDS projection for ring detection

[ring_detection.py](../backend/app/services/ring_detection.py)

```cypher
MATCH (a:Account)-[r:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE|TRANSACTED_WITH]->(b:Account)
WITH gds.graph.project($name, a, b,
       {relationshipType: type(r), relationshipProperties: {weight: coalesce($weights[type(r)], 0.1)}},
       {undirectedRelationshipTypes: ['*']}) AS g
RETURN g.nodeCount, g.relationshipCount
```

A Cypher projection: the `MATCH` decides what goes into the in-memory graph, `type(r)` keeps relationship types (so WCC can use identity links only) and `$weights[type(r)]` attaches a weight to each. Followed by:

```cypher
CALL gds.wcc.write($name, {writeProperty: 'component_id', relationshipTypes: $shared_types})
CALL gds.louvain.write($name, {writeProperty: 'community_id', relationshipWeightProperty: 'weight'})
CALL gds.pageRank.write($name, {writeProperty: 'hub_score', relationshipWeightProperty: 'weight'})
CALL gds.graph.drop($name, false)
```

## 8. Idempotent ingestion

[ingestion.py](../backend/app/services/ingestion.py)

```cypher
MATCH (a:Account {id: $account_id})
MERGE (dst:Merchant {id: $target_id}) ON CREATE SET dst += $target_props
MERGE (t:Transaction {id: $tx.id})
SET t += $tx
MERGE (a)-[:INITIATED]->(t)
MERGE (t)-[:PAID_TO]->(dst)
MERGE (a)-[w:TRANSACTED_WITH]->(dst)
ON CREATE SET w.count = 0, w.total_amount = 0.0
SET w.count = w.count + 1, w.total_amount = w.total_amount + $tx.amount
```

`MERGE` against the `Transaction.id` uniqueness constraint means a replayed event cannot create a second node; the pipeline also checks for the ID first so totals are not double-counted.

## 9. Benchmark: reachability at depth N

[benchmark.py](../backend/app/benchmark.py)

```cypher
MATCH (a:Account {id: $id})
CALL apoc.path.subgraphNodes(a, {relationshipFilter: $filter, labelFilter: '+Account', maxLevel: $depth})
YIELD node
RETURN count(node) - 1 AS reached
```

and the PostgreSQL equivalent:

```sql
WITH RECURSIVE reach(id, depth) AS (
    SELECT %(id)s::text, 0
  UNION
    SELECT l.b, r.depth + 1
    FROM reach r JOIN shared_link l ON l.a = r.id
    WHERE r.depth < %(depth)s AND l.kind = ANY(%(kinds)s)
)
SELECT count(DISTINCT id) - 1 FROM reach;
```

The benchmark asserts both return the same count for every start account and depth before reporting any timing.
