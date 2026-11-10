// Is this account within N hops of any flagged account? Returns the closest ones with the path (F4).
// The hop limit must be a literal in shortestPath, so it is validated (1-6) and inlined.
MATCH (a:Account {{id: $id}})
MATCH (f:Account {{is_flagged: true}}) WHERE f <> a
MATCH p = shortestPath((a)-[:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE|TRANSACTED_WITH*..{depth}]-(f))
RETURN f.id AS flagged_account, length(p) AS hops, p
ORDER BY hops, flagged_account
LIMIT 5
