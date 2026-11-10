// =============================================================================
// Derive account-to-account SHARED_* edges from shared attribute nodes.
//
// "A1 uses device D" + "A2 uses device D"  =>  (A1)-[:SHARED_DEVICE]->(A2)
//
// Conventions (see docs/data-model.md):
// - One edge per shared attribute, keyed by that attribute's ID, so MERGE makes
//   re-running this file harmless and "shares >= K devices" is a simple count.
// - Stored from the lower account id to the higher one; always queried undirected.
// - Accounts of the SAME owner are not linked: one person using their own phone
//   for two accounts is not a fraud signal.
//
// This file derives edges for the whole graph (used after a bulk load).
// =============================================================================

// SHARED_DEVICE: two accounts of different owners logged in from the same device.
MATCH (a1:Account)-[:USES_DEVICE]->(d:Device)<-[:USES_DEVICE]-(a2:Account)
WHERE a1.id < a2.id
  AND NOT EXISTS { (a1)<-[:OWNS]-(:User)-[:OWNS]->(a2) }
MERGE (a1)-[r:SHARED_DEVICE {device_id: d.device_id}]->(a2)
  ON CREATE SET r.since = datetime();

// SHARED_CARD: two accounts of different owners used the same card.
MATCH (a1:Account)-[:USES_CARD]->(c:Card)<-[:USES_CARD]-(a2:Account)
WHERE a1.id < a2.id
  AND NOT EXISTS { (a1)<-[:OWNS]-(:User)-[:OWNS]->(a2) }
MERGE (a1)-[r:SHARED_CARD {card_hash: c.card_hash}]->(a2)
  ON CREATE SET r.since = datetime();

// SHARED_ADDRESS: the owners of two accounts live at the same address.
// Address hangs off the User, so the pattern looks through OWNS.
MATCH (a1:Account)<-[:OWNS]-(u1:User)-[:LIVES_AT]->(ad:Address)<-[:LIVES_AT]-(u2:User)-[:OWNS]->(a2:Account)
WHERE a1.id < a2.id AND u1 <> u2
MERGE (a1)-[r:SHARED_ADDRESS {address_id: ad.id}]->(a2)
  ON CREATE SET r.since = datetime();

// SHARED_PHONE: the owners of two accounts registered the same phone number.
MATCH (a1:Account)<-[:OWNS]-(u1:User)-[:HAS_PHONE]->(p:Phone)<-[:HAS_PHONE]-(u2:User)-[:OWNS]->(a2:Account)
WHERE a1.id < a2.id AND u1 <> u2
MERGE (a1)-[r:SHARED_PHONE {number_hash: p.number_hash}]->(a2)
  ON CREATE SET r.since = datetime();
