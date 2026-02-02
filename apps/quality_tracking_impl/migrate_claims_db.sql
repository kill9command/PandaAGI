-- Database Migration: Add Quality Tracking to Claims Table
-- Location: Run against panda_system_docs/shared_state/claims.db
-- Date: 2025-11-09

-- Add quality tracking columns
ALTER TABLE claims ADD COLUMN intent_alignment REAL DEFAULT 0.5;
ALTER TABLE claims ADD COLUMN result_type TEXT DEFAULT NULL;
ALTER TABLE claims ADD COLUMN evidence_strength REAL DEFAULT 0.5;
ALTER TABLE claims ADD COLUMN user_feedback_score REAL DEFAULT NULL;
ALTER TABLE claims ADD COLUMN times_reused INTEGER DEFAULT 0;
ALTER TABLE claims ADD COLUMN times_helpful INTEGER DEFAULT 0;
ALTER TABLE claims ADD COLUMN created_at TEXT DEFAULT (datetime('now'));
ALTER TABLE claims ADD COLUMN last_used_at TEXT DEFAULT NULL;
ALTER TABLE claims ADD COLUMN quality_score REAL GENERATED ALWAYS AS (
    (intent_alignment * 0.4) +
    (evidence_strength * 0.3) +
    (COALESCE(user_feedback_score, 0.5) * 0.3)
) STORED;

-- Add TTL column (calculated based on quality)
ALTER TABLE claims ADD COLUMN ttl_hours INTEGER DEFAULT 168;  -- 7 days default
ALTER TABLE claims ADD COLUMN expires_at TEXT;

-- Add deprecation tracking
ALTER TABLE claims ADD COLUMN deprecated BOOLEAN DEFAULT 0;
ALTER TABLE claims ADD COLUMN deprecation_reason TEXT DEFAULT NULL;

-- Create index on quality_score for efficient filtering
CREATE INDEX IF NOT EXISTS idx_claims_quality ON claims(quality_score);

-- Create index on intent for filtering
CREATE INDEX IF NOT EXISTS idx_claims_intent ON claims(matched_intent);

-- Create index on result_type for compatibility checks
CREATE INDEX IF NOT EXISTS idx_claims_result_type ON claims(result_type);

-- Create index on expires_at for cleanup
CREATE INDEX IF NOT EXISTS idx_claims_expires ON claims(expires_at);

-- Create index on deprecated for filtering
CREATE INDEX IF NOT EXISTS idx_claims_deprecated ON claims(deprecated) WHERE deprecated = 0;

-- Update existing claims to have safe defaults
UPDATE claims
SET
    intent_alignment = 0.5,
    evidence_strength = 0.5,
    ttl_hours = 168,
    created_at = COALESCE(timestamp, datetime('now')),
    expires_at = datetime(COALESCE(timestamp, datetime('now')), '+168 hours')
WHERE intent_alignment IS NULL;

-- Mark claims with NULL matched_intent as deprecated
UPDATE claims
SET
    deprecated = 1,
    deprecation_reason = 'Missing intent metadata - pre-quality-tracking claim'
WHERE matched_intent IS NULL;

-- Verify migration
SELECT
    COUNT(*) as total_claims,
    COUNT(CASE WHEN deprecated = 0 THEN 1 END) as active_claims,
    COUNT(CASE WHEN deprecated = 1 THEN 1 END) as deprecated_claims,
    AVG(quality_score) as avg_quality,
    MIN(quality_score) as min_quality,
    MAX(quality_score) as max_quality
FROM claims;
