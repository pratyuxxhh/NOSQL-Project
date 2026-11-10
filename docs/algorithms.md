# FraudMesh Algorithms

This document explains every scoring and detection step, with the formulas and worked numbers. Code references point to the implementation.

1. [Deriving SHARED_* edges](#1-deriving-shared_-edges)
2. [Baseline rule scoring](#2-baseline-rule-scoring-the-existing-methodology)
3. [Ring detection: WCC, Louvain, Label Propagation](#3-ring-detection)
4. [Ring suspicion criteria](#4-ring-suspicion-criteria)
5. [Risk propagation](#5-risk-propagation)
6. [Final score and ALLOW / REVIEW / BLOCK](#6-final-score-and-decision)

All thresholds and weights below are defaults. An admin can change them at runtime on the **Admin** page; they are stored in Neo4j (`:Config {id: 'runtime'}`).

---

## 1. Deriving SHARED_* edges

*Code: [derive_shared_edges.cypher](../backend/app/cypher/derive_shared_edges.cypher) (bulk), [derive_shared_edges_for_account.cypher](../backend/app/cypher/derive_shared_edges_for_account.cypher) (per transaction).*

The raw graph says "account A1 uses device D" and "account A2 uses device D". FraudMesh adds a direct edge between the two accounts:

```
(A1)-[:USES_DEVICE]->(D)<-[:USES_DEVICE]-(A2)    =>    (A1)-[:SHARED_DEVICE {device_id: D}]->(A2)
```

| Derived edge | Comes from | Key property |
|---|---|---|
| `SHARED_DEVICE` | Account → Device ← Account | `device_id` |
| `SHARED_CARD` | Account → Card ← Account | `card_hash` |
| `SHARED_ADDRESS` | Account ← User → Address ← User → Account | `address_id` |
| `SHARED_PHONE` | Account ← User → Phone ← User → Account | `number_hash` |

Rules:

- **One edge per shared attribute.** Two accounts sharing two devices get two edges. "Shares at least K devices" is then a count.
- **Direction is fixed:** lower account id → higher account id, so A→B and B→A are never both created. Queries ignore direction.
- **Same owner is excluded.** A person using their own phone for two accounts is normal, so it creates no edge.
- `MERGE` keyed on the attribute makes derivation idempotent: re-running it creates nothing new.

**Example.** A1, A2 and A3 (three different owners) all log in from device D1:

```
A1 -SHARED_DEVICE- A2,  A1 -SHARED_DEVICE- A3,  A2 -SHARED_DEVICE- A3      (a triangle, density 1.0)
```

---

## 2. Baseline rule scoring (the "existing methodology")

*Code: [rules.py](../backend/app/services/rules.py), thresholds in [rules.yaml](../backend/rules.yaml).*

Each transaction is judged **on its own**, the way traditional systems do. Points add up and are capped at 100.

| Rule | Fires when | Points |
|---|---|---|
| High amount | amount ≥ ₹50,000 | 40 |
| Velocity | more than 5 transactions by the account within 10 minutes | 30 |
| New device | first time this account uses this device | 15 |
| Unusual location | transaction country is not India | 25 |
| High-risk merchant | merchant risk tier HIGH (gift cards, crypto, gambling, money transfer) | 30 |

`rule_score ≥ 60` raises a `HIGH_RULE_SCORE` alert and counts as "caught by rules" in the evaluation.

**Example.** ₹90,000 at a crypto exchange abroad: 40 + 25 + 30 = **95**. A ₹3,000 purchase by a mule from an ordinary shop: **0**, even though the account belongs to a ring. That gap is what the graph closes.

---

## 3. Ring detection

*Code: [ring_detection.py](../backend/app/services/ring_detection.py). Runs every 60 s (configurable) and on demand: `POST /api/v1/rings/detect?algorithm=louvain|lpa`.*

### Step 1: projection

All `Account` nodes and the account-to-account relationships `SHARED_DEVICE`, `SHARED_CARD`, `SHARED_ADDRESS`, `SHARED_PHONE` and `TRANSACTED_WITH` are copied into an in-memory GDS graph. The copy is **undirected**, and each relationship gets a weight (the same weights as risk propagation: device/card 0.9, phone 0.8, address 0.6, transfer 0.4). Every run uses its own projection name and drops it in a `finally` block, so no in-memory graph leaks and concurrent runs never collide.

### Step 2: Weakly Connected Components (identity clusters)

WCC runs over the `SHARED_*` relationships only. It groups accounts that are tied together by **identity** (devices, cards, addresses, phones), writing `component_id`. This is fast (linear time) and acts as the pre-filter: most accounts end up alone in a component of size 1.

A component **no larger than `max_ring_size` (30)** is taken as one candidate group directly.

*Why not run Louvain on everything?* Ring members also move money to and from ordinary customers (victims paying mules, a deposit entering a layering chain). When community detection runs on the whole network, those money links pull ring members into communities of 100–150 normal customers, and the ring disappears. This was measured: Louvain alone found 0 of 6 mule rings and 0 of 6 layering chains; with the WCC step all 24 rings are found.

### Step 3: Louvain or Label Propagation (splitting big clusters)

Community detection runs over **all** projected links (identity + money), using the weights, and writes `community_id`. Accounts whose identity component is **bigger** than `max_ring_size` are grouped by their community instead.

| | Louvain | Label Propagation (LPA) |
|---|---|---|
| Idea | Greedily moves nodes between communities to maximise **modularity** (more links inside communities than random chance would give), then merges communities and repeats | Every node starts with its own label and repeatedly adopts the label most common (by weight) among its neighbours, until labels stop changing |
| Result | Hierarchical, stable, usually the better partition | Very fast, near-linear; results can vary between runs |
| Why it suits fraud rings | Rings are small, dense subgraphs: exactly what modularity rewards | Dense clusters converge to one label quickly |
| Parameters | `relationshipWeightProperty: weight`, GDS defaults otherwise | `relationshipWeightProperty: weight`, GDS defaults otherwise |

### Step 4: PageRank (hub account)

Weighted PageRank writes `hub_score`. The member with the highest score is stored as the ring's `hub_account`: the account most central to the ring, often the operator or the collector.

### Step 5: ring metrics

For each candidate group: size, average account risk, number of distinct shared devices / cards / addresses / phones, total transaction volume, **density**, share of new accounts, number of flagged members.

```
density = (pairs of members linked by at least one SHARED_* edge) / (n × (n − 1) / 2)
```

A ring's id is a hash of its sorted member list, so re-detecting the same ring updates it instead of creating a duplicate. Rings an analyst has already reviewed are never overwritten. Unreviewed rings that are not detected again are removed.

---

## 4. Ring suspicion criteria

*Code: `is_suspicious()` in [ring_detection.py](../backend/app/services/ring_detection.py).*

A candidate group becomes a `:Ring` when:

```
size ≥ 3  AND  ( contains ≥ 1 flagged account
                 OR ( density ≥ 0.5  AND  ≥ 50% of accounts opened in the last 90 days ) )
```

The spec's starting point was "size ≥ 3 AND (density above threshold OR contains a flagged account)". Measured on the synthetic data, density alone flagged **141** groups, 117 of them ordinary families sharing an address or a tablet (precision 0.21). Families are dense too, but their accounts are old; fraud rings run on freshly created identities. Adding the new-account condition cut false positives from 414 accounts to 18 while still finding all 24 planted rings.

| Example group | Size | Density | New accounts | Flagged | Ring? |
|---|---|---|---|---|---|
| 5 synthetic identities on one phone | 5 | 1.0 | 100% | 0 | **yes** (dense + new) |
| Family of 4 at one address | 4 | 1.0 | 0% | 0 | no |
| Layering chain of 6 sharing phones pairwise | 6 | 0.33 | 100% | 1 | **yes** (known fraud inside) |
| 2 accounts sharing a card | 2 | 1.0 | 100% | 1 | no (too small) |

---

## 5. Risk propagation

*Code: [propagation.py](../backend/app/services/propagation.py). Triggered when an analyst flags an account (`POST /api/v1/risk/propagate/{id}`), when a ring is confirmed, when a new transaction links an account to known fraud, and on every detection cycle.*

### Formula

Every path of up to **3 hops** from a flagged account, through account-to-account links, carries a contribution:

```
contribution = source_risk × Π(edge weights on the path) × decay^hops
```

| Relationship | Weight |
|---|---|
| `SHARED_DEVICE` | 0.9 |
| `SHARED_CARD` | 0.9 |
| `SHARED_PHONE` | 0.8 |
| `SHARED_ADDRESS` | 0.6 |
| `TRANSACTED_WITH` | 0.4 |

`decay = 0.5`, maximum depth 3. Flagged accounts have `source_risk = 1.0`.

### Aggregation (noisy-OR)

1. For each (source, target) pair only the **strongest** path counts. Three parallel paths from the same fraudster are one piece of evidence, not three.
2. Contributions from **different** sources are combined with noisy-OR:

```
propagated_risk = 1 − Π (1 − cᵢ)          capped at 1.0
```

Noisy-OR treats each source as an independent chance that the account is involved. It grows with more evidence but never exceeds 1, and a single strong link counts for more than several weak ones.

### Worked example (3 hops)

Account A is confirmed fraud (risk 1.0). B shares A's device; C shares B's address; D received money from C.

| Account | Strongest path from A | Calculation | Contribution |
|---|---|---|---|
| B | A -SHARED_DEVICE- B | 1.0 × 0.9 × 0.5¹ | **0.450** |
| C | A -SHARED_DEVICE- B -SHARED_ADDRESS- C | 1.0 × 0.9 × 0.6 × 0.5² | **0.135** |
| D | A -SHARED_DEVICE- B -SHARED_ADDRESS- C -TRANSACTED_WITH- D | 1.0 × 0.9 × 0.6 × 0.4 × 0.5³ | **0.027** |

Now suppose E, a second flagged account, shares a phone with B: 1.0 × 0.8 × 0.5 = 0.40. B's propagated risk:

```
1 − (1 − 0.45)(1 − 0.40) = 1 − 0.55 × 0.60 = 0.67
```

These numbers are checked by `tests/test_propagation.py`.

### Explanations and pre-emptive detection

Each account stores `propagated_risk` and `risk_explanation`, the top 3 contributing paths as text, e.g. `A006878 -SHARED_DEVICE- A006876 (0.45)`. Analysts see *why* an account is risky.

An account with `propagated_risk ≥ 0.3` that is **not flagged** and **never had a transaction with rule_score ≥ 60** is a **pre-emptive detection**: `pre_emptive = true`, a `PROPAGATED_RISK` alert, highlighted on the dashboard. These are accounts the rules would never have caught.

The account's overall risk (used for rankings) is

```
combined_risk = 1 − (1 − risk_score) × (1 − propagated_risk)
```

where `risk_score` is the account's own risk (its worst rule score ÷ 100, or 1.0 if flagged).

---

## 6. Final score and decision

*Code: `final_score()` and `decide()` in [ingestion.py](../backend/app/services/ingestion.py).*

Each transaction gets a final score from 0 to 100, again by noisy-OR:

```
graph_risk  = 1.0 if the account is flagged, else its propagated_risk
final_score = 100 × (1 − (1 − rule_score / 100) × (1 − graph_risk))
```

The account's own rule history is deliberately **not** included, so one rule hit is not counted twice.

| final_score | Decision |
|---|---|
| < 40 | **ALLOW** |
| 40 – 69.99 | **REVIEW** |
| ≥ 70 | **BLOCK** |

**Examples.**

| Transaction | rule_score | graph_risk | final_score | Decision |
|---|---|---|---|---|
| Ordinary purchase, unconnected account | 0 | 0 | 0 | ALLOW |
| Crypto purchase, unconnected account | 30 | 0 | 30 | ALLOW |
| Small purchase by a new account on a ring's device | 0 | 0.45 | 45 | REVIEW |
| Same, plus high-risk merchant | 30 | 0.45 | 61.5 | REVIEW |
| Purchase by a flagged account | any | 1.0 | 100 | BLOCK |
| ₹90,000 at a foreign crypto exchange | 95 | 0 | 95 | BLOCK |
