-- Phase 6, first item: rater tooling.
--
--   psql -d asd_therapy -f sql/2026_09_25_ratings.sql
--
-- Safe to run twice: every statement is guarded.

BEGIN;

-- researcher | rater. A rater can listen and judge and see nothing else.
ALTER TABLE caregivers ADD COLUMN IF NOT EXISTS role VARCHAR(12) DEFAULT 'researcher';
UPDATE caregivers SET role = 'researcher' WHERE role IS NULL;

-- What is to be rated, per task, built once and served to every rater the
-- same. A tenth of the set is entered twice (repeat_index 1) for
-- within-rater consistency.
CREATE TABLE IF NOT EXISTS rating_sets (
    id            UUID PRIMARY KEY,
    task          VARCHAR(16) NOT NULL,
    attempt_id    UUID NOT NULL REFERENCES session_activities(id),
    stratum       VARCHAR(80),
    repeat_index  INTEGER DEFAULT 0,
    created_at    TIMESTAMP DEFAULT now(),
    UNIQUE (task, attempt_id, repeat_index)
);

-- One person's blind judgement of one recording.
CREATE TABLE IF NOT EXISTS ratings (
    id             UUID PRIMARY KEY,
    task           VARCHAR(16) NOT NULL,
    attempt_id     UUID NOT NULL REFERENCES session_activities(id),
    rater_id       UUID NOT NULL REFERENCES caregivers(id),
    repeat_index   INTEGER DEFAULT 0,
    correct        BOOLEAN,
    accuracy       INTEGER,
    wrong_feature  VARCHAR(32),
    unusable       BOOLEAN DEFAULT FALSE,
    duration_ms    INTEGER,
    created_at     TIMESTAMP DEFAULT now(),
    UNIQUE (task, attempt_id, rater_id, repeat_index)
);
CREATE INDEX IF NOT EXISTS ix_ratings_task_rater ON ratings (task, rater_id);

COMMIT;
