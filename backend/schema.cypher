// =============================================================================
// FraudMesh graph schema: uniqueness constraints and indexes.
//
// Applied automatically when the backend starts (app/db/schema.py), or manually:
//     cd backend && python -m app.db.schema
//
// Every statement uses IF NOT EXISTS, so re-running this file is harmless.
// Format rules for the loader: statements end with ';' and comments must be on
// their own lines starting with '//'.
//
// Neo4j Community edition supports uniqueness constraints but not existence
// (NOT NULL) or node-key constraints, so required properties are enforced by the
// Pydantic models in app/models/graph.py instead.
// =============================================================================


// -----------------------------------------------------------------------------
// Uniqueness constraints: one per node ID.
// Each also creates a backing index, so MERGE / lookups by ID are fast.
// -----------------------------------------------------------------------------

CREATE CONSTRAINT user_id IF NOT EXISTS
FOR (n:User) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT account_id IF NOT EXISTS
FOR (n:Account) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT account_no IF NOT EXISTS
FOR (n:Account) REQUIRE n.account_no IS UNIQUE;

CREATE CONSTRAINT device_id IF NOT EXISTS
FOR (n:Device) REQUIRE n.device_id IS UNIQUE;

// Cards are identified by a SHA-256 hash; raw card numbers are never stored.
CREATE CONSTRAINT card_hash IF NOT EXISTS
FOR (n:Card) REQUIRE n.card_hash IS UNIQUE;

CREATE CONSTRAINT address_id IF NOT EXISTS
FOR (n:Address) REQUIRE n.id IS UNIQUE;

// Two spellings of the same address normalise to the same hash, so ingestion
// MERGEs on this property to avoid duplicate Address nodes.
CREATE CONSTRAINT address_normalized_hash IF NOT EXISTS
FOR (n:Address) REQUIRE n.normalized_hash IS UNIQUE;

CREATE CONSTRAINT phone_number_hash IF NOT EXISTS
FOR (n:Phone) REQUIRE n.number_hash IS UNIQUE;

CREATE CONSTRAINT merchant_id IF NOT EXISTS
FOR (n:Merchant) REQUIRE n.id IS UNIQUE;

// Also what makes ingestion idempotent: replaying a transaction ID cannot
// create a second Transaction node.
CREATE CONSTRAINT transaction_id IF NOT EXISTS
FOR (n:Transaction) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT fraud_flag_id IF NOT EXISTS
FOR (n:FraudFlag) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT analyst_id IF NOT EXISTS
FOR (n:Analyst) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT analyst_username IF NOT EXISTS
FOR (n:Analyst) REQUIRE n.username IS UNIQUE;

CREATE CONSTRAINT ring_id IF NOT EXISTS
FOR (n:Ring) REQUIRE n.ring_id IS UNIQUE;

CREATE CONSTRAINT alert_id IF NOT EXISTS
FOR (n:Alert) REQUIRE n.id IS UNIQUE;


// -----------------------------------------------------------------------------
// Range indexes on properties used in WHERE / ORDER BY.
// -----------------------------------------------------------------------------

// Time-window queries: velocity rules, "transactions today", live feed.
CREATE INDEX transaction_timestamp IF NOT EXISTS
FOR (n:Transaction) ON (n.timestamp);

CREATE INDEX transaction_final_score IF NOT EXISTS
FOR (n:Transaction) ON (n.final_score);

// Ranking and filtering accounts by risk.
CREATE INDEX account_risk_score IF NOT EXISTS
FOR (n:Account) ON (n.risk_score);

CREATE INDEX account_propagated_risk IF NOT EXISTS
FOR (n:Account) ON (n.propagated_risk);

// Finding known fraud: propagation sources and "linked to fraud" checks.
CREATE INDEX account_is_flagged IF NOT EXISTS
FOR (n:Account) ON (n.is_flagged);

// Looking up all members of a detected community.
CREATE INDEX account_community_id IF NOT EXISTS
FOR (n:Account) ON (n.community_id);

CREATE INDEX merchant_risk_tier IF NOT EXISTS
FOR (n:Merchant) ON (n.risk_tier);

// Ring list page: filter by status, newest first.
CREATE INDEX ring_status IF NOT EXISTS
FOR (n:Ring) ON (n.status);

CREATE INDEX ring_detected_at IF NOT EXISTS
FOR (n:Ring) ON (n.detected_at);

// Alerts page: filter by status / severity, newest first.
CREATE INDEX alert_status IF NOT EXISTS
FOR (n:Alert) ON (n.status);

CREATE INDEX alert_severity IF NOT EXISTS
FOR (n:Alert) ON (n.severity);

CREATE INDEX alert_created_at IF NOT EXISTS
FOR (n:Alert) ON (n.created_at);


// -----------------------------------------------------------------------------
// Platform nodes: API keys, audit log, runtime configuration.
// -----------------------------------------------------------------------------

CREATE CONSTRAINT api_key_id IF NOT EXISTS
FOR (n:ApiKey) REQUIRE n.id IS UNIQUE;

// API keys are looked up by the SHA-256 of the presented key.
CREATE CONSTRAINT api_key_hash IF NOT EXISTS
FOR (n:ApiKey) REQUIRE n.key_hash IS UNIQUE;

CREATE CONSTRAINT audit_log_id IF NOT EXISTS
FOR (n:AuditLog) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT config_id IF NOT EXISTS
FOR (n:Config) REQUIRE n.id IS UNIQUE;

CREATE INDEX audit_log_at IF NOT EXISTS
FOR (n:AuditLog) ON (n.at);

// Rule-only baseline: "which transactions did the rules catch?"
CREATE INDEX transaction_rule_score IF NOT EXISTS
FOR (n:Transaction) ON (n.rule_score);

// Accounts at risk after combining own and propagated risk.
CREATE INDEX account_combined_risk IF NOT EXISTS
FOR (n:Account) ON (n.combined_risk);
