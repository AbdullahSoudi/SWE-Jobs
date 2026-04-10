-- =============================================================================
-- SWE-Jobs v2: Applications tracking, streaks, and blacklist
-- =============================================================================

-- =============================================================================
-- TABLE: user_applications
-- Tracks which jobs a user has applied to, with timestamps for streak calc.
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_applications (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    applied_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, job_id)
);

CREATE INDEX IF NOT EXISTS user_applications_user_id_idx ON user_applications (user_id);
CREATE INDEX IF NOT EXISTS user_applications_applied_at_idx ON user_applications (user_id, applied_at);

ALTER TABLE user_applications ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- Add blacklist column to users (JSONB: {"companies": [...], "keywords": [...]})
-- =============================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS blacklist JSONB DEFAULT '{}';
