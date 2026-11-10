// Derive SHARED_* edges for ONE account after a new transaction (incremental
// version of derive_shared_edges.cypher; same conventions). The pair is ordered
// so the edge always runs from the lower account id to the higher one.

// SHARED_DEVICE
MATCH (a:Account {id: $account_id})-[:USES_DEVICE]->(d:Device)<-[:USES_DEVICE]-(o:Account)
WHERE NOT EXISTS { (a)<-[:OWNS]-(:User)-[:OWNS]->(o) }
WITH d, CASE WHEN a.id < o.id THEN [a, o] ELSE [o, a] END AS pair
WITH d, pair[0] AS x, pair[1] AS y
MERGE (x)-[r:SHARED_DEVICE {device_id: d.device_id}]->(y)
  ON CREATE SET r.since = datetime();

// SHARED_CARD
MATCH (a:Account {id: $account_id})-[:USES_CARD]->(c:Card)<-[:USES_CARD]-(o:Account)
WHERE NOT EXISTS { (a)<-[:OWNS]-(:User)-[:OWNS]->(o) }
WITH c, CASE WHEN a.id < o.id THEN [a, o] ELSE [o, a] END AS pair
WITH c, pair[0] AS x, pair[1] AS y
MERGE (x)-[r:SHARED_CARD {card_hash: c.card_hash}]->(y)
  ON CREATE SET r.since = datetime();

// SHARED_ADDRESS
MATCH (a:Account {id: $account_id})<-[:OWNS]-(u1:User)-[:LIVES_AT]->(ad:Address)<-[:LIVES_AT]-(u2:User)-[:OWNS]->(o:Account)
WHERE u1 <> u2
WITH ad, CASE WHEN a.id < o.id THEN [a, o] ELSE [o, a] END AS pair
WITH ad, pair[0] AS x, pair[1] AS y
MERGE (x)-[r:SHARED_ADDRESS {address_id: ad.id}]->(y)
  ON CREATE SET r.since = datetime();

// SHARED_PHONE
MATCH (a:Account {id: $account_id})<-[:OWNS]-(u1:User)-[:HAS_PHONE]->(p:Phone)<-[:HAS_PHONE]-(u2:User)-[:OWNS]->(o:Account)
WHERE u1 <> u2
WITH p, CASE WHEN a.id < o.id THEN [a, o] ELSE [o, a] END AS pair
WITH p, pair[0] AS x, pair[1] AS y
MERGE (x)-[r:SHARED_PHONE {number_hash: p.number_hash}]->(y)
  ON CREATE SET r.since = datetime();
