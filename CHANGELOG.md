# Changelog

All notable changes to FraudMesh are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [1.0.0] - 2026-11-11 — Phases 3–13: complete system

Built in one pass at the team's request, instead of phase by phase.

### Added
- **Synthetic data (F10):** `app/datagen/` generates customers, accounts, devices, cards, merchants and transactions (Faker `en_IN`, seeded and deterministic), plants 4 ring types (shared-device, shared-address mule, card-testing, layering chain) with ground truth in `data/ground_truth.json`, and bulk-loads everything into Neo4j with `UNWIND`/`MERGE`. Benign sharing (families, shared tablets) is generated deliberately.
- **PII protection:** `app/security/pii.py`: HMAC-SHA256 hashing of card and phone numbers and normalised addresses (`PII_HASH_KEY`), phone masking.
- **Real-time ingestion (F2):** `POST /api/v1/ingest/transaction` and `/ingest/batch` (API key), `asyncio` queue and worker, one-transaction graph writes, per-account `SHARED_*` derivation, idempotency on transaction ID, latency metrics.
- **Rule baseline (F3):** `rules.yaml` and `app/services/rules.py` (high amount, velocity, new device, foreign location, high-risk merchant); bulk scoring of seeded history.
- **Multi-hop queries (F4):** commented `.cypher` files for neighbourhood (APOC BFS, depth 1–6), shortest path, shared-attribute finder, link-to-fraud; search endpoint.
- **Ring detection (F5):** GDS Cypher projection, WCC on identity links, Louvain or Label Propagation, PageRank hub, ring metrics, suspicion criteria, `:Ring` + `MEMBER_OF`, scheduled every 60 s and on demand.
- **Ring management (F6):** list/detail/subgraph endpoints, review workflow; confirming flags members and propagates risk.
- **Risk propagation (F7):** weighted, decayed, noisy-OR propagation with explanation paths, combined risk and pre-emptive detections.
- **Alerts (F8):** `:Alert` nodes with dedupe, four alert types, WebSocket push, acknowledge/assign/note/resolve.
- **Dashboard (F9):** 11 pages (Login, Overview, Rings, Graph Explorer, Path Finder, Risk Propagation, Alerts, Rules vs Graph, Performance, Admin, Audit Log), Cytoscape graphs, Recharts charts, dark-mode toggle, responsive layout, live updates.
- **Simulator and evaluation (F10):** `app/simulator.py` streams transactions with periodic ring activity; `app/evaluation.py` reports precision/recall/F1 for rules vs graph vs graph + propagation.
- **Benchmark (F11):** `app/benchmark.py` loads the same links into PostgreSQL and times recursive CTEs vs Neo4j traversal at depths 1–6 on two workloads, checking both return identical results; writes `data/benchmark.json` and the chart.
- **Security (F12):** JWT access/refresh, bcrypt, RBAC (ADMIN/ANALYST/VIEWER), hashed API keys with per-key rate limits, login rate limiting, security headers, audit log.
- **Reusable API (F13):** synchronous `POST /api/v1/score` returning ALLOW/REVIEW/BLOCK with reasons; `examples/payment_service_client.py`.
- **Observability (F14):** `/api/v1/stats/metrics` (ingestion rate, latency p50/p95, queue depth, detection time) shown on the dashboard.
- `app/seed.py` one-command demo setup; host wrapper scripts in `scripts/`; `make seed/simulate/evaluate/benchmark/test`.
- Docs: `architecture.md`, `algorithms.md`, `api.md`, `cypher-queries.md`, `demo-script.md`, `benchmark.png`, 13 screenshots.
- Tests: 103 backend (87 unit, 16 integration on real Neo4j with GDS + APOC), 12 frontend smoke tests; backend coverage 73%.

### Changed
- Schema: 19 constraints and 15 indexes (added `ApiKey`, `AuditLog`, `Config`, rule-score and combined-risk indexes).
- Account model gains `combined_risk`, `pre_emptive`, `component_id`, `hub_score`; Analyst gains `role`, `active`, password hash.
- Status panel page replaced by the full dashboard.

### Fixed during the build
- Ring detection initially found 0/6 mule rings and 0/6 layering chains, because Louvain on all links merged them into communities of normal customers; now WCC on identity links runs first (24/24 found).
- Ordinary families were reported as rings (precision 0.21); the suspicion criteria now also require mostly new accounts (precision 0.86).
- A transaction's rule score was counted twice in its final score; the final score now combines the rule score with graph risk only.

## [0.2.0] - 2026-11-10 — Phase 2: Data model

### Added
- `backend/schema.cypher`: 15 uniqueness constraints (one per node identifier) and 12 range indexes (transaction timestamp, account risk / flag / community, ring and alert filters).
- `app/db/schema.py`: loads and applies the schema on backend startup (with retry), or manually via `python -m app.db.schema`.
- `app/models/graph.py`: node labels, relationship types, allowed values and Pydantic models for all 12 node types.
- `docs/data-model.md`: full data-model explanation, conventions, constraints, and a tested worked example; `docs/data-model.svg` diagram (source `docs/data-model.mmd`).
- Integration tests against a real Neo4j container (testcontainers), plus unit tests for the schema loader and models. 23 tests, 94% backend coverage.

### Changed
- `/ready` now also checks that every constraint and index in `schema.cypher` exists in the database.
- Dashboard status panel shows the graph schema check.
- README: Graph Data Model section, Feature Traceability (F1 ✅), Testing, Project Structure and Design Decisions updated.

## [0.1.0] - 2026-11-10 — Phase 1: Setup

### Added
- Docker Compose stack: Neo4j 5.26 (Community) with the APOC and Graph Data Science plugins, PostgreSQL 16, FastAPI backend and React dashboard.
- `.env.example` with all configuration; secrets are read only from environment variables.
- FastAPI backend skeleton: settings via `pydantic-settings`, async Neo4j driver, CORS restricted to the dashboard origin, structured JSON logging with per-request latency.
- `GET /health` (liveness) and `GET /ready` (checks Neo4j connectivity, GDS and APOC; returns 503 if any are missing).
- Backend unit tests for the health endpoints (4 tests, 92% coverage).
- React + Vite + TypeScript + Tailwind dashboard skeleton showing live system status, with dark mode.
- `Makefile` shortcuts (`up`, `down`, `logs`, `ps`, `test`, `clean`).
- README with project overview, Getting Started, and Feature Traceability table.
