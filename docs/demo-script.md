# 5-Minute Viva Demo Script

**Before the viva** (once, about 3 minutes): `docker compose up --build -d`, wait until `curl http://localhost:8000/ready` says `"ready"`, then `make seed` (or `docker compose exec backend python -m app.seed`). Open http://localhost:5173 and log in as `analyst` / `ChangeMe123!` (or your `DEFAULT_ADMIN_PASSWORD`). Keep a terminal ready.

The account IDs below are examples; take real ones from the screens as you go.

---

### 0:00 – 0:30 · The problem

> "Fraudsters work in rings that share phones, cards and addresses. Each transaction looks normal on its own, so rule engines miss them. FraudMesh stores everything as a graph in Neo4j and finds the rings from the connections."

Show **Overview**: 50,000 transactions, rings already detected, pre-emptive detections.

### 0:30 – 1:15 · Stream live transactions

In the terminal:

```bash
docker compose exec backend python -m app.simulator --rate 10 --fraud-every 15
```

> "This is a payment service sending 10 transactions a second through the ingestion API with an API key."

On **Overview** the live feed scrolls and the transaction counter rises. Point at latency p50/p95 under *System metrics* (well under one second).

### 1:15 – 2:00 · A ring appears

Every 15 seconds the simulator opens a brand-new account on a device used by a planted ring. Open **Alerts**: a `LINKED_TO_FRAUD` and a `PROPAGATED_RISK` alert arrive live for `SIMACC000x`.

> "The transaction itself was ₹2,000 at an ordinary shop: rule score 0. The graph saw that the phone it came from belongs to a ring with a confirmed fraudster."

Open **Rings**, click a ring with *Known fraud = 0* and high density. Show the graph: accounts (blue) tied by red SHARED edges to one device; members are all a few weeks old; hub account from PageRank.

### 2:00 – 2:45 · Analyst confirms the ring → risk propagates

On the ring page: **Confirm fraud** → confirm. The message shows how many accounts were flagged, how many the risk reached and how many pre-emptive detections it produced.

Open **Risk Propagation**, click one of the newly flagged accounts. The graph animates hop by hop; the table lists each reached account with its score and the exact path, e.g. `A006878 -SHARED_DEVICE- A006876 (0.45)`.

> "Risk = source × link weight × 0.5 per hop; several sources combine with noisy-OR."

### 2:45 – 3:30 · Pre-emptive detection

Still on Risk Propagation, the *Pre-emptive detections* table: accounts with propagated risk ≥ 0.3 and **no rule ever fired**.

> "These accounts would never have been caught by the rules. The graph flags them before they commit fraud."

### 3:30 – 4:05 · Explain a link

**Path Finder**: enter the first and last account of a layering chain (or `SIMACC0001` and a ring member). The answer reads like a sentence:

`SIMACC0001 -[USES_DEVICE]- Device D006531 -[USES_DEVICE]- Account A006877`

### 4:05 – 4:40 · Rules vs Graph

**Rules vs Graph** page: accounts caught by rules only / graph only / both, and the evaluation against ground truth:

| | Precision | Recall | F1 |
|---|---|---|---|
| Rules only | 0.67 | 0.06 | 0.10 |
| Graph | 0.86 | 1.00 | 0.92 |

> "All 24 planted rings found; the rule engine catches 6 of 108 hidden fraud accounts."

### 4:40 – 5:00 · Benchmark

**Performance** page: Neo4j vs PostgreSQL for depth 1–6.

> "At this data size PostgreSQL's recursive query is faster in absolute terms; it's a well-indexed small table. Neo4j's cost is dominated by a fixed per-call overhead and grows more slowly as the reachable set grows ~90× from depth 1 to 6. The bigger win of the graph is expressiveness: ring detection, propagation and path explanations are a few lines of Cypher and GDS calls."

Stop the simulator with Ctrl+C.
