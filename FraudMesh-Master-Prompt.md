# MASTER PROMPT — Build "FraudMesh"

> Copy everything below this line and paste it into your AI coding assistant (Claude Code, Cursor, Copilot Chat, etc.).

---

## 0. Your role and how to work

You are a senior full-stack engineer and graph-database specialist. Build **FraudMesh – Graph-Based Real-Time Fraud Ring Detection and Risk Propagation System** from scratch, as a complete, runnable, well-documented academic project for the course **CSAEC59: AEC-NoSQL** (Ramaiah Institute of Technology, Dept. of CSE, Aug–Dec 2026).

- **Team:** Nimesh Rusia (1MS24CS115), Pratyush Parashar (1MS24CS131)
- **Guide:** Akshatha Kamath
- **Core database:** Neo4j (native graph database) + Neo4j Graph Data Science (GDS) library

Working rules:
1. Build in the phases listed in Section 9. Finish and test each phase before starting the next.
2. After every phase, **update `README.md` and `CHANGELOG.md`** (see Section 10). This is mandatory, not optional.
3. Every feature listed in Section 3 must exist, work end to end, and appear in the README's Feature Traceability table.
4. Never hard-code secrets. Use `.env` files and commit only `.env.example`.
5. All Cypher must be parameterized (no string concatenation of user input into queries).
6. Write clean, commented, typed code. Prefer clarity over cleverness — this project will be presented and explained in a viva.
7. If a decision is not specified here, choose the simplest reasonable option and record it in the README under "Design Decisions".

---

## 1. Problem being solved (keep this framing in the README)

Fraudsters rarely act alone. They operate as **connected rings** that share devices, phone numbers, addresses, or payment cards across many seemingly unrelated accounts. A transaction that looks normal in isolation becomes suspicious only when viewed with its multi-hop network of shared attributes and prior fraud flags.

Existing systems fail because they use:
- **Relational, attribute-based scoring** — amount/location/frequency checked against static thresholds; entities stored as separate table rows, not as a network.
- **JOIN-chain relationship discovery** — multi-hop relationships require chained JOINs that get slower and more complex with depth.
- **No automated pattern surfacing** — a device reused across "unrelated" accounts is found only if an analyst explicitly queries for it.
- **Isolated, per-account evaluation** — each account scored independently of its neighbours, so detection is reactive at ring level.
- **Poor scalability at depth** — performance degrades sharply as investigation depth increases.

FraudMesh fixes this by modelling fraud detection as a **graph problem** in Neo4j.

---

## 2. Tech stack (use exactly this unless impossible)

| Layer | Technology |
|---|---|
| Graph DB | Neo4j 5.x Community/Enterprise (Docker) with **GDS plugin** and **APOC** |
| Backend / Ingestion / Detection API | Python 3.11+, **FastAPI**, official `neo4j` Python driver, Pydantic v2 |
| Real-time push | WebSockets (FastAPI) for live alerts and transaction feed |
| Background work | `asyncio` worker queue (or Redis Streams if you need persistence) for ingestion and scheduled GDS jobs (APScheduler) |
| Frontend dashboard | **React + Vite + TypeScript**, Tailwind CSS, graph visualisation with **Cytoscape.js** (or `react-force-graph`), charts with Recharts |
| Auth & security | JWT (access + refresh), bcrypt password hashing, role-based access control, API keys for ingestion clients |
| Relational baseline (for comparison only) | PostgreSQL (Docker) with the same data, used for the JOIN-vs-graph benchmark |
| Testing | pytest + testcontainers (or a test Neo4j container), Vitest/React Testing Library for frontend |
| Packaging | Docker Compose — one command brings up everything |

---

## 3. Complete feature list (every item must be implemented)

### F1. Graph Data Model in Neo4j
Model all entities as **nodes**:
- `User` (id, name, email, phone, created_at, kyc_status)
- `Account` (id, account_no, type, status, opened_at, risk_score, propagated_risk, is_flagged, community_id)
- `Device` (device_id, fingerprint, os, ip_last_seen)
- `Card` (card_hash, bin, issuer, type) — never store raw card numbers; store a SHA-256 hash + last 4 digits
- `Address` (id, line, city, pincode, normalized_hash)
- `Phone` (number_hash)
- `Merchant` (id, name, category/MCC, country, risk_tier)
- `Transaction` (id, amount, currency, timestamp, channel, location, status, rule_score, final_score)
- `FraudFlag` / `Analyst` (who/what flagged an entity, reason, timestamp, confidence)
- `Ring` (ring_id, algorithm, size, avg_risk, detected_at, status)

Model interactions as **relationships**, and you MUST include the four named in the synopsis:
- `TRANSACTED_WITH` (Account→Account or Account→Merchant; properties: count, total_amount, last_at)
- `SHARED_DEVICE` (Account–Account, derived; properties: device_id, since)
- `SHARED_ADDRESS` (Account–Account, derived; properties: address_id, since)
- `FLAGGED_BY` (Account/Transaction→FraudFlag or Analyst; properties: reason, at, confidence)

Plus supporting relationships:
- `OWNS` (User→Account), `USES_DEVICE` (Account→Device), `USES_CARD` (Account→Card), `LIVES_AT` (User→Address), `HAS_PHONE` (User→Phone), `INITIATED` (Account→Transaction), `PAID_TO` (Transaction→Merchant/Account), `MEMBER_OF` (Account→Ring)
- Also derive `SHARED_CARD` and `SHARED_PHONE` (Account–Account) the same way as SHARED_DEVICE.

Requirements:
- Uniqueness constraints on every node ID; indexes on frequently filtered properties (timestamp, risk_score, is_flagged).
- A `schema.cypher` file that creates all constraints and indexes, run automatically on startup.
- A diagram of the graph model (Mermaid in README + PNG/SVG in `docs/`).

### F2. Real-Time Transaction Ingestion Layer
- `POST /api/v1/ingest/transaction` accepts a transaction event (JSON) authenticated by **API key** (so multiple transaction-processing services can use FraudMesh).
- `POST /api/v1/ingest/batch` for bulk events.
- Each event is validated (Pydantic), queued, and processed by a worker that uses `MERGE` to **create or update** User, Account, Device, Card, Address, Phone, Merchant and Transaction nodes and their relationships — keeping the graph reflective of current activity.
- After each write, automatically derive/refresh `SHARED_DEVICE`, `SHARED_ADDRESS`, `SHARED_CARD`, `SHARED_PHONE` edges for affected accounts.
- Idempotency: replaying the same transaction ID must not duplicate data.
- After ingestion, immediately trigger: rule scoring (F3) → local ring check (F5) → risk propagation if needed (F7) → alerting (F8).
- Target: ingestion-to-alert latency under ~1 second for a single event on a laptop; measure and report it.

### F3. Baseline Rule-Based Scoring (represents the "Existing Methodology")
- Implement simple per-transaction rules: high amount threshold, velocity (N txns in T minutes), new device, unusual location/country, high-risk merchant category.
- Produces `rule_score` (0–100) for each transaction, evaluated **in isolation**.
- Purpose: to show in the dashboard and report what per-account rules **miss** compared to graph detection. Keep it configurable via a YAML/JSON rules file.

### F4. Multi-Hop Relationship Discovery (Cypher)
Provide API endpoints backed by Cypher:
- **Variable-length path traversal** — `GET /api/v1/graph/neighbourhood/{account_id}?depth=1..6` returns all entities within N hops (e.g. `MATCH p=(a:Account {id:$id})-[*1..$depth]-(x)`; implement depth safely since Cypher doesn't allow parameterized bounds — validate and whitelist depth 1–6).
- **Shortest path** — `GET /api/v1/graph/shortest-path?from=A&to=B` using `shortestPath` / `allShortestPaths`, explaining *how* two accounts are linked (e.g. A → Device D1 → B → Address X → C).
- **Shared-attribute finder** — accounts that share ≥ K devices/cards/addresses/phones with a given account.
- **Connection to known fraud** — "is this account within N hops of any flagged account?" with the path returned.
- Store all important queries in `backend/app/cypher/*.cypher` files, each with a comment explaining what it does (useful for the viva).

### F5. Automated Fraud Ring Detection (Neo4j GDS)
- Create a GDS **graph projection** of Account nodes and SHARED_* / TRANSACTED_WITH relationships, with relationship weights.
- Run **Louvain community detection** AND **Label Propagation** (both, selectable). Also run **Weakly Connected Components** as a quick pre-filter.
- Optional extras for ranking inside a ring: Degree Centrality / PageRank to identify the "hub" account.
- Write results back (`community_id`) and create `Ring` nodes with `MEMBER_OF` edges for communities that meet suspicion criteria (e.g. size ≥ 3 AND shared-attribute density above threshold OR contains ≥ 1 flagged account).
- Compute ring metrics: size, average risk, number of shared devices/cards/addresses, total transaction volume, density.
- Run on a schedule (e.g. every 60 s, configurable) and on demand via `POST /api/v1/rings/detect?algorithm=louvain|lpa`.
- Drop and recreate projections cleanly; never leak in-memory graphs.

### F6. Ring Management
- `GET /api/v1/rings` (list, filter by status/size/risk, paginate), `GET /api/v1/rings/{id}` (members, shared attributes, subgraph JSON for visualisation).
- Ring status workflow: `NEW → UNDER_REVIEW → CONFIRMED_FRAUD | FALSE_POSITIVE`. Confirming a ring flags all members and triggers risk propagation.

### F7. Risk Propagation Engine
When a node is newly flagged (by analyst or by ring confirmation), its risk spreads outward through the graph:
- **Weighted by relationship type** — configurable weights, e.g. SHARED_DEVICE 0.9, SHARED_CARD 0.9, SHARED_PHONE 0.8, SHARED_ADDRESS 0.6, TRANSACTED_WITH 0.4.
- **Decayed with distance** — `contribution = source_risk × Π(edge weights on path) × decay^hops` (e.g. decay = 0.5), up to a max depth (default 3).
- **Aggregation** when a node receives risk from multiple sources: use noisy-OR, `1 − Π(1 − c_i)`, capped at 1.0 (document this choice).
- Store `propagated_risk` on each Account plus a `risk_explanation` (top contributing paths) so analysts can see *why* an account is risky.
- Final account score = combination of own rule score and propagated risk (document the formula).
- Accounts whose propagated risk crosses a threshold are **surfaced for review even if they never triggered any rule** — highlight these specially in the dashboard ("Pre-emptive detections").
- Implement in Cypher (and/or GDS Pregel/personalised PageRank as an alternative), with an endpoint `POST /api/v1/risk/propagate/{node_id}` and automatic triggering.

### F8. Alerts & Risk Scores
- Alert node / table with: id, type (`HIGH_RULE_SCORE`, `RING_DETECTED`, `PROPAGATED_RISK`, `LINKED_TO_FRAUD`), severity (LOW/MEDIUM/HIGH/CRITICAL), entity, explanation, created_at, status (OPEN/ACK/RESOLVED), assigned analyst.
- Pushed live to the dashboard over **WebSocket**.
- Endpoints to list, filter, acknowledge, assign, resolve alerts, with notes.

### F9. Analyst / Administration Dashboard (React)
Pages:
1. **Login** (JWT).
2. **Overview** — KPI cards (transactions today, open alerts, active rings, accounts at risk, pre-emptive detections), live transaction feed, alerts-over-time chart, risk score distribution chart.
3. **Rings** — table of detected rings + an interactive **graph visualisation** of each ring (nodes coloured by type, sized by risk, flagged nodes highlighted, edges labelled by relationship type).
4. **Graph Explorer** — search any account/device/card/address, expand neighbours hop by hop, choose depth, filter by relationship type.
5. **Path Finder** — pick two accounts, show the shortest path visually and in words.
6. **Risk Propagation view** — select a flagged node, animate/visualise how risk spread, list affected accounts with score and explanation paths.
7. **Alerts** — real-time list with filters, acknowledge/resolve workflow.
8. **Rule vs Graph comparison** — side-by-side: accounts caught by rules only, by graph only, by both (proves the expected outcome).
9. **Performance / Benchmark** page — charts from F11.
10. **Admin settings** — manage users/roles, API keys, rule thresholds, propagation weights/decay/depth, detection schedule (ADMIN only).
11. **Audit Log** viewer (ADMIN only).

UI must be clean, responsive, and support dark mode.

### F10. Synthetic Data Generator & Live Simulator
- Script `scripts/generate_data.py` that creates realistic data (use Faker): e.g. 5,000 users, 7,000 accounts, 300 merchants, 50,000 transactions — size configurable.
- **Plant known fraud rings** of various shapes (shared-device ring, shared-address mule ring, card-testing ring, chain/layering pattern) with ground-truth labels saved to `data/ground_truth.json`.
- `scripts/simulate_stream.py` that streams transactions to the ingestion API at a configurable rate (e.g. 10–100 tx/s), with occasional fraud-ring activity, so the dashboard can be demoed live.
- Evaluation script that compares detected rings with ground truth and reports **precision, recall, F1** for: rule-only baseline vs graph detection vs graph + propagation. Include results in the README.

### F11. Graph vs Relational Benchmark (proves "Native Graph Performance" & index-free adjacency)
- Load the same dataset into PostgreSQL with normalised tables.
- Run equivalent queries for "find all accounts connected within depth 1…6 via shared attributes" — recursive CTE / chained JOINs in SQL vs variable-length paths in Cypher.
- Record execution time at each depth and dataset size; produce a chart (`docs/benchmark.png`) and a results table in the README.
- Script: `scripts/benchmark.py`.

### F12. Backend Security
- JWT authentication (short-lived access token + refresh token), bcrypt password hashing.
- **RBAC** roles: `ADMIN`, `ANALYST`, `VIEWER` — enforced on every endpoint.
- API-key authentication (hashed in DB) for ingestion clients, with per-key rate limiting.
- Parameterised Cypher everywhere (Cypher-injection safe); input validation with Pydantic.
- CORS restricted to the dashboard origin; security headers.
- Rate limiting on login and ingestion endpoints (e.g. `slowapi`).
- PII protection: hash card numbers and phone numbers, mask in UI.
- Separate least-privilege Neo4j user for the app (where edition allows).
- **Audit log** of every analyst action (flag, confirm ring, resolve alert, change settings).
- Secrets only via environment variables.

### F13. Reusable, Decoupled Architecture
- Fraud-detection logic lives entirely in the graph layer/service, **separate from transaction-processing logic**, so any number of transaction-handling services can call it.
- Expose a clean versioned REST API (`/api/v1`) with auto-generated **OpenAPI/Swagger docs**.
- Include a tiny example "client service" (`examples/payment_service_client.py`) that sends transactions and receives a risk decision — demonstrating reuse.
- `POST /api/v1/score` — synchronous endpoint returning a risk decision (`ALLOW / REVIEW / BLOCK`) plus explanation for a transaction.

### F14. Observability & Health
- `/health` and `/ready` endpoints (checks Neo4j connectivity and GDS availability).
- Structured JSON logging; basic metrics (ingestion rate, latency, queue depth, detection run time) shown on the dashboard.

---

## 4. Required end-to-end flow (must work exactly like this)

```
Transaction Event → FraudMesh Ingestion Layer → Neo4j Graph Store
   → Ring Detection & Risk Propagation (Cypher / GDS) → Alert & Risk Score → Analyst Dashboard
```

Draw this as a Mermaid diagram in the README and a full architecture diagram in `docs/architecture.md`.

---

## 5. Project structure

```
fraudmesh/
├── README.md
├── CHANGELOG.md
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db/            (neo4j driver, postgres for benchmark)
│   │   ├── cypher/        (all .cypher files, commented)
│   │   ├── models/        (Pydantic schemas)
│   │   ├── api/v1/        (ingest, graph, rings, risk, alerts, auth, admin, score)
│   │   ├── services/      (ingestion, rules, ring_detection, propagation, alerting)
│   │   ├── security/      (jwt, rbac, api_keys, rate_limit, audit)
│   │   ├── workers/       (queue consumer, scheduler)
│   │   └── websocket/
│   ├── schema.cypher
│   ├── rules.yaml
│   ├── tests/
│   └── Dockerfile
├── frontend/
│   ├── src/ (pages, components, hooks, api, graph)
│   └── Dockerfile
├── scripts/ (generate_data.py, simulate_stream.py, evaluate.py, benchmark.py, seed_admin.py)
├── examples/ (payment_service_client.py)
├── data/ (ground_truth.json — generated)
└── docs/ (architecture.md, data-model.md, api.md, cypher-queries.md, algorithms.md, screenshots/, benchmark.png)
```

---

## 6. Algorithm documentation (write in `docs/algorithms.md`)
Explain, with formulas and small worked examples:
- How SHARED_* edges are derived.
- Louvain vs Label Propagation — how they work, why they suit fraud rings, chosen parameters.
- Ring suspicion criteria.
- Risk propagation formula, weights, decay, depth limit, aggregation (noisy-OR), and a worked numeric example across 3 hops.
- Final score formula and ALLOW/REVIEW/BLOCK thresholds.

---

## 7. Testing requirements
- Unit tests for rules, propagation math, ring criteria, security (RBAC, JWT expiry, API keys).
- Integration tests against a real Neo4j test container: ingestion creates the right nodes/edges, idempotency, shortest path, ring detection finds a planted ring, propagation reaches expected neighbours with expected scores.
- Frontend: smoke tests for main pages.
- `make test` (or a script) runs everything. Target ≥ 70% backend coverage; report it in README.

---

## 8. Running the project
- `docker compose up --build` must start Neo4j (with GDS + APOC), PostgreSQL, backend, and frontend.
- `make seed` (or script) generates data and creates a default admin user.
- `make simulate` starts the live stream.
- Default URLs: dashboard `http://localhost:5173`, API docs `http://localhost:8000/docs`, Neo4j Browser `http://localhost:7474`.

---

## 9. Build phases (do them in order; update README + CHANGELOG after each)

1. **Setup** — repo structure, Docker Compose, Neo4j + GDS + APOC, FastAPI skeleton, health checks, README skeleton.
2. **Data model** — schema.cypher, constraints, indexes, model docs and diagram.
3. **Data generator** — synthetic data with planted rings + ground truth.
4. **Ingestion layer** — API-key auth, queue, MERGE writes, SHARED_* derivation, idempotency.
5. **Rule baseline** — rules.yaml, rule scoring.
6. **Multi-hop Cypher queries** — neighbourhood, shortest path, shared attributes, link-to-fraud.
7. **Ring detection** — GDS projection, Louvain, LPA, WCC, Ring nodes, scheduler.
8. **Risk propagation** — engine, explanations, pre-emptive detection.
9. **Alerts + WebSocket**.
10. **Security** — JWT, RBAC, rate limits, audit log, hardening.
11. **Dashboard** — all pages in F9.
12. **Simulator, evaluation (precision/recall/F1), benchmark vs PostgreSQL**.
13. **Tests, polish, screenshots, final documentation.**

---

## 10. README.md — mandatory maintenance rules

Create `README.md` in Phase 1 and **keep it accurate after every phase and every significant change**. The README is a deliverable that will be evaluated. It must always contain these sections, in this order:

1. **Title, one-line description, badges** (tech stack, license).
2. **Academic details** — institute, department, course code CSAEC59: AEC-NoSQL, team members with USNs, guide, semester (Aug–Dec 2026).
3. **Problem Statement** (short).
4. **Existing Methodology & its limitations** (short bullets).
5. **Proposed Solution** — how FraudMesh uses Neo4j.
6. **Novelty / Key Contributions** — relationship-centric modelling, multi-hop ring detection, automated community detection, risk propagation, real-time graph updates, native graph performance.
7. **Architecture** — Mermaid diagram of the flow in Section 4 + component diagram.
8. **Graph Data Model** — Mermaid diagram of nodes/relationships + table of node labels, properties, and relationship types.
9. **Feature Traceability table** — every synopsis feature (F1–F14) mapped to: implementation file(s), API endpoint(s), dashboard page, and status (✅ Done / 🚧 In progress / ⏳ Planned). Update the status column after every phase.
10. **Tech Stack** table.
11. **Getting Started** — prerequisites, clone, `.env` setup, `docker compose up`, seeding data, default login, URLs. Every command must be copy-paste runnable and tested.
12. **Usage guide** — how to run the simulator, view rings, use Path Finder, confirm a ring, watch risk propagate.
13. **API Reference summary** — endpoint table (method, path, role required, description) + link to Swagger.
14. **Key Cypher Queries** — the most important queries with explanation.
15. **Algorithms** — short summary + link to `docs/algorithms.md`.
16. **Security** — summary of all measures in F12.
17. **Results** — detection precision/recall/F1 (rules vs graph vs graph + propagation), latency numbers, graph-vs-relational benchmark table and chart.
18. **Screenshots** of every dashboard page (`docs/screenshots/`).
19. **Testing** — how to run tests, coverage %.
20. **Project Structure** tree.
21. **Design Decisions & Assumptions**.
22. **Limitations & Future Work**.
23. **Troubleshooting** (common Docker/Neo4j/GDS issues).
24. **References** (Neo4j docs, GDS docs, Louvain/LPA papers).
25. **License & Acknowledgements**.

README rules:
- Never leave a section describing something that doesn't exist yet as if it does — mark it ⏳ Planned.
- When code changes a command, endpoint, env variable, or folder, update the README in the same step.
- Also maintain `CHANGELOG.md` (Keep-a-Changelog format) with an entry for every phase.
- At the end of each phase, print a short summary: what was built, what was tested, what README sections changed.

---

## 11. Definition of done
- [ ] `docker compose up` brings up the whole system without manual fixes.
- [ ] All features F1–F14 work and are ✅ in the README traceability table.
- [ ] Planted fraud rings are detected and shown visually; graph detection clearly beats the rule-only baseline in the evaluation.
- [ ] Risk propagation surfaces at least some accounts that no rule flagged.
- [ ] Benchmark shows Neo4j vs PostgreSQL timing across depths 1–6.
- [ ] Tests pass; coverage reported.
- [ ] README complete, accurate, with screenshots and results; CHANGELOG up to date.
- [ ] A 5-minute demo script (`docs/demo-script.md`) exists for the viva: start system → stream transactions → ring appears → analyst confirms ring → risk propagates → pre-emptive alert on a connected account → show shortest path explaining the link → show benchmark.

Start with Phase 1 now. Before writing code, show me a brief plan for Phase 1 and the initial README skeleton.
