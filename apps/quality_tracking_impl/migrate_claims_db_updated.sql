-- Database Migration: Add Quality Tracking to Claims Table
-- Location: Run against panda_system_docs/shared_state/claims.db
-- Date: 2025-11-09
-- Note: Works with existing schema from orchestrator/shared_state/claims.py

-- Add quality tracking columns (only if they don't exist)
-- SQLite doesn't support IF NOT EXISTS for ALTER TABLE ADD COLUMN,
-- so we'll catch errors if columns already exist

-- Add matched_intent column
ALTER TABLE claims ADD COLUMN matched_intent TEXT DEFAULT NULL;

-- Add intent_alignment column
ALTER TABLE claims ADD COLUMN intent_alignment REAL DEFAULT 0.5;

-- Add result_type column
ALTER TABLE claims ADD COLUMN result_type TEXT DEFAULT NULL;

-- Add evidence_strength column
ALTER TABLE claims ADD COLUMN evidence_strength REAL DEFAULT 0.5;

-- Add user_feedback_score column
ALTER TABLE claims ADD COLUMN user_feedback_score REAL DEFAULT NULL;

-- Add times_reused column
ALTER TABLE claims ADD COLUMN times_reused INTEGER DEFAULT 0;

-- Add times_helpful column
ALTER TABLE claims ADD COLUMN times_helpful INTEGER DEFAULT 0;

-- Add last_used_at column
ALTER TABLE claims ADD COLUMN last_used_at TEXT DEFAULT NULL;

-- Add deprecated column
ALTER TABLE claims ADD COLUMN deprecated BOOLEAN DEFAULT 0;

-- Add deprecation_reason column
ALTER TABLE claims ADD COLUMN deprecation_reason TEXT DEFAULT NULL;

-- Create views for quality_score calculation (can't use GENERATED ALWAYS with ALTER)
-- We'll calculate this in code instead

-- Create indexes for efficient filtering
CREATE INDEX IF NOT EXISTS idx_claims_quality ON claims(intent_alignment, evidence_strength);
CREATE INDEX IF NOT EXISTS idx_claims_intent ON claims(matched_intent);
CREATE INDEX IF NOT EXISTS idx_claims_result_type ON claims(result_type);
CREATE INDEX IF NOT EXISTS idx_claims_deprecated ON claims(deprecated) WHERE deprecated = 0;
CREATE INDEX IF NOT EXISTS idx_claims_expires ON claims(expires_at);

-- Update existing claims to have safe defaults
UPDATE claims
SET
    intent_alignment = 0.5,
    evidence_strength = 0.5,
    matched_intent = NULL
WHERE intent_alignment IS NULL;

-- Verify migration
SELECT
    COUNT(*) as total_claims,
    COUNT(CASE WHEN deprecated = 0 THEN 1 END) as active_claims,
    COUNT(CASE WHEN deprecated = 1 THEN 1 END) as deprecated_claims,
    AVG(COALESCE(intent_alignment, 0.5) * 0.4 +
        COALESCE(evidence_strength, 0.5) * 0.3 +
        COALESCE(user_feedback_score, 0.5) * 0.3) as avg_quality_score
FROM claims;
