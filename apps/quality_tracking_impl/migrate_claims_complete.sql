-- Complete Database Setup: Claims Table with Quality Tracking
-- Location: Run against panda_system_docs/shared_state/claims.db
-- Date: 2025-11-09

-- Create base claims table (matching orchestrator/shared_state/claims.py schema)
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    statement TEXT NOT NULL,
    evidence TEXT NOT NULL,
    confidence TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    last_verified TEXT NOT NULL,
    ttl_seconds INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    metadata TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_turn_id TEXT,
    -- Quality tracking columns (new)
    matched_intent TEXT DEFAULT NULL,
    intent_alignment REAL DEFAULT 0.5,
    result_type TEXT DEFAULT NULL,
    evidence_strength REAL DEFAULT 0.5,
    user_feedback_score REAL DEFAULT NULL,
    times_reused INTEGER DEFAULT 0,
    times_helpful INTEGER DEFAULT 0,
    last_used_at TEXT DEFAULT NULL,
    deprecated BOOLEAN DEFAULT 0,
    deprecation_reason TEXT DEFAULT NULL
);

-- Create artifacts_seen table
CREATE TABLE IF NOT EXISTS artifacts_seen (
    session_id TEXT NOT NULL,
    blob_id TEXT NOT NULL,
    first_seen REAL NOT NULL,
    PRIMARY KEY (session_id, blob_id)
);

-- Create indexes (existing)
CREATE INDEX IF NOT EXISTS idx_claims_session ON claims(session_id);
CREATE INDEX IF NOT EXISTS idx_claims_ticket ON claims(ticket_id);

-- Create indexes (new for quality tracking)
CREATE INDEX IF NOT EXISTS idx_claims_quality ON claims(intent_alignment, evidence_strength);
CREATE INDEX IF NOT EXISTS idx_claims_intent ON claims(matched_intent);
CREATE INDEX IF NOT EXISTS idx_claims_result_type ON claims(result_type);
CREATE INDEX IF NOT EXISTS idx_claims_deprecated ON claims(deprecated) WHERE deprecated = 0;
CREATE INDEX IF NOT EXISTS idx_claims_expires ON claims(expires_at);

-- Verify schema
SELECT 'Migration complete. Schema ready for quality tracking.' AS status;
