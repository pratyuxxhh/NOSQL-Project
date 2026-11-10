// How are two accounts connected? (F4, Path Finder)
// Walks the raw attribute links (account -> device <- account, user -> address <- user ...)
// rather than derived SHARED_* edges, so the answer names the shared device/card/address.
// Merchants are excluded: almost everyone shops somewhere, so a path through a merchant explains nothing.
MATCH (a:Account {{id: $from}}), (b:Account {{id: $to}})
MATCH p = {function}((a)-[:OWNS|USES_DEVICE|USES_CARD|LIVES_AT|HAS_PHONE|TRANSACTED_WITH*..{max_hops}]-(b))
WHERE none(n IN nodes(p) WHERE n:Merchant)
RETURN p
LIMIT 5
