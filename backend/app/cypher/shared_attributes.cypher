// Accounts that share at least K devices / cards / addresses / phones with an account (F4).
// Counts derived SHARED_* edges: there is one edge per shared attribute.
MATCH (a:Account {id: $id})-[r:SHARED_DEVICE|SHARED_CARD|SHARED_ADDRESS|SHARED_PHONE]-(o:Account)
WITH o, count(r) AS shared, collect(DISTINCT type(r)) AS kinds
WHERE shared >= $min_shared
RETURN o.id AS account, shared, kinds, coalesce(o.is_flagged, false) AS is_flagged,
       coalesce(o.combined_risk, 0.0) AS combined_risk
ORDER BY shared DESC, account
LIMIT 100
