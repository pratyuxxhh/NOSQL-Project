# FraudMesh API

Interactive documentation (generated from the code): **http://localhost:8000/docs** (Swagger UI) and http://localhost:8000/redoc.

## Authentication

| Caller | How | Used for |
|---|---|---|
| People (dashboard) | `POST /api/v1/auth/login` → `Authorization: Bearer <access_token>`; refresh with `POST /api/v1/auth/refresh` | Everything except ingestion |
| Services | `X-API-Key: fm_...` (created on the Admin page or by `make seed`) | `/ingest/*`, `/score` |

Roles: `ADMIN` > `ANALYST` > `VIEWER`. An endpoint needing ANALYST also admits ADMIN.

Access tokens last 15 minutes, refresh tokens 7 days. Login is limited to 10 attempts per minute per IP.

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | public | Liveness |
| GET | `/ready` | public | Neo4j, GDS, APOC and schema all present (503 otherwise) |
| POST | `/api/v1/auth/login` | public | Username + password → tokens and user |
| POST | `/api/v1/auth/refresh` | refresh token | New tokens (picks up role changes) |
| GET | `/api/v1/auth/me` | VIEWER | Current user |
| POST | `/api/v1/ingest/transaction` | API key | Queue one event (202) |
| POST | `/api/v1/ingest/batch` | API key | Queue up to 1,000 events (202); each event counts against the key's limit |
| POST | `/api/v1/score` | API key | Process now; returns `ALLOW` / `REVIEW` / `BLOCK` with reasons |
| GET | `/api/v1/graph/search?q=` | VIEWER | Find accounts, devices, people, merchants, cards (last 4), addresses, rings |
| GET | `/api/v1/graph/neighbourhood/{key}?label=Account&depth=1..6&types=...` | VIEWER | Everything within N hops |
| GET | `/api/v1/graph/shortest-path?from=A&to=B&all=false` | VIEWER | How two accounts are linked, as graph + text |
| GET | `/api/v1/graph/shared/{account_id}?min_shared=K` | VIEWER | Accounts sharing ≥ K attributes |
| GET | `/api/v1/graph/linked-to-fraud/{account_id}?depth=N` | VIEWER | Closest flagged accounts within N hops, with paths |
| POST | `/api/v1/rings/detect?algorithm=louvain\|lpa` | ANALYST | Run detection now |
| GET | `/api/v1/rings?status=&min_size=&min_risk=&page=&page_size=` | VIEWER | List rings |
| GET | `/api/v1/rings/{ring_id}` | VIEWER | Ring, members, subgraph for visualisation |
| PATCH | `/api/v1/rings/{ring_id}/status` | ANALYST | `NEW → UNDER_REVIEW → CONFIRMED_FRAUD \| FALSE_POSITIVE`; confirming flags members and propagates |
| POST | `/api/v1/risk/propagate/{node_id}` | ANALYST | Flag an account and propagate its risk |
| POST | `/api/v1/risk/recompute` | ANALYST | Recompute propagation for the whole graph |
| GET | `/api/v1/risk/accounts?min_risk=&pre_emptive=` | VIEWER | Accounts by combined risk |
| GET | `/api/v1/risk/spread/{account_id}` | VIEWER | Accounts reached from this source, by hop, with explanations |
| GET | `/api/v1/alerts?status=&type=&severity=&page=` | VIEWER | List alerts |
| PATCH | `/api/v1/alerts/{id}` | ANALYST | Change status (`OPEN/ACK/RESOLVED`), assign, add a note |
| GET | `/api/v1/stats/overview` | VIEWER | KPIs, charts, recent transactions, metrics |
| GET | `/api/v1/stats/comparison` | VIEWER | Rules-only vs graph-only vs both, plus evaluation |
| GET | `/api/v1/stats/benchmark` | VIEWER | Last benchmark results |
| GET | `/api/v1/stats/metrics` | VIEWER | Ingestion rate, latency, queue depth, detection time |
| GET/POST | `/api/v1/admin/users` | ADMIN | List / create users |
| PATCH | `/api/v1/admin/users/{username}` | ADMIN | Change role, enable/disable, reset password |
| GET/POST | `/api/v1/admin/api-keys` | ADMIN | List / create keys (the full key is returned once) |
| DELETE | `/api/v1/admin/api-keys/{id}` | ADMIN | Revoke a key |
| GET/PUT | `/api/v1/admin/settings` | ADMIN | Rule thresholds, propagation weights/decay/depth, detection, decision thresholds |
| GET | `/api/v1/admin/audit?actor=&action=&page=` | ADMIN | Audit log |
| WS | `/ws?token=<access_token>` | VIEWER | Live events: `transaction`, `alert`, `alert_updated`, `ring` |

## Transaction event

```json
{
  "transaction_id": "PAY-0001",
  "timestamp": "2026-11-10T10:15:00Z",
  "amount": 2500.0,
  "currency": "INR",
  "channel": "CARD",
  "location": "Bengaluru, IN",
  "account": {"id": "A000123", "type": "SAVINGS"},
  "user": {
    "id": "U000123", "name": "Asha Rao", "email": "asha@example.com", "phone": "+919845012345",
    "address": {"line": "12, M.G. Road", "city": "Bengaluru", "pincode": "560001"}
  },
  "device": {"device_id": "D-7f3a", "os": "Android 14", "ip": "203.0.113.7"},
  "card": {"number": "4854 9812 3456 7890", "issuer": "HDFC Bank", "type": "DEBIT"},
  "merchant": {"id": "M00011", "name": "Gift Hub", "category": "Gift cards", "mcc": "5947", "country": "IN", "risk_tier": "HIGH"}
}
```

- Pay **either** a `merchant` **or** another account (`"counterparty_account_id": "A000456"`).
- `user` is needed the first time an account is seen; afterwards `account.id` is enough. `device`, `card` and `merchant` details are optional for known entities.
- The card number and phone number are hashed on arrival and never stored.
- `location` is `"City, CC"` (ISO country code).

## Score result

```json
{
  "transaction_id": "PAY-0001",
  "account_id": "SIMACC0001",
  "decision": "REVIEW",
  "final_score": 45.0,
  "rule_score": 0,
  "rule_reasons": [],
  "account_risk": 0.45,
  "propagated_risk": 0.45,
  "risk_explanation": ["A006878 -SHARED_DEVICE- SIMACC0001 (0.45)"],
  "linked_to_fraud": true,
  "ring_ids": [],
  "duplicate": false,
  "latency_ms": 312.4
}
```

`account_risk` is the account's graph risk: 1.0 if flagged, else its propagated risk. See [algorithms.md](algorithms.md#6-final-score-and-decision).
