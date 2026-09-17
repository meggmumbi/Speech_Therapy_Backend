-- Phase 2: make a session attributable to what it actually was.
--
--   psql -d asd_therapy -f sql/2026_09_17_study_integrity.sql
--
-- Safe to run twice: every statement is guarded.
--
-- THE PROBLEM THIS FIXES
--
-- Every session recorded before today has condition NULL and no record of
-- whether it was a training block or a test. The scoring endpoint quietly
-- defaulted to condition 'D' and logged a warning nobody read, so the stored
-- rows look like study data and are not: none of them can be attributed to a
-- condition, and none can be told apart from an ad-hoc therapy session.
--
-- session_type is the fix. Training blocks give feedback under K or D;
-- assessments (pretest / posttest / delayed) give none, and are what every
-- learning measure is computed from. NULL means an ad-hoc session that was
-- never part of the study, which is still allowed for ordinary therapy use --
-- but the scoring endpoint now refuses to write into one for a participant who
-- holds a counterbalancing assignment.

BEGIN;

-- --- therapy_sessions -------------------------------------------------------

-- training | pretest | posttest | delayed. NULL = ad-hoc, not part of the study.
ALTER TABLE therapy_sessions ADD COLUMN IF NOT EXISTS session_type VARCHAR(12);

-- 1 or 2 for a training block, NULL for an assessment. Denormalised from the
-- assignment so a later change to the design cannot rewrite what a stored
-- session actually was.
ALTER TABLE therapy_sessions ADD COLUMN IF NOT EXISTS block_index INTEGER;

-- Seed for the presentation order. The order itself is not stored: it is
-- regenerated from the seed, so the sequence a participant saw is reproducible
-- from the session row rather than trusted to a log.
ALTER TABLE therapy_sessions ADD COLUMN IF NOT EXISTS item_order_seed INTEGER;

-- One assessment per participant per phase. Two pre-tests would give the
-- analysis two baselines with no principled way to choose between them, and
-- the second would already be contaminated by the first. Enforced here as well
-- as in the endpoint, because a race between two tablets would slip past an
-- application-level check.
CREATE UNIQUE INDEX IF NOT EXISTS ix_sessions_one_assessment_per_phase
    ON therapy_sessions (child_id, session_type)
    WHERE session_type IN ('pretest', 'posttest', 'delayed');

CREATE INDEX IF NOT EXISTS ix_sessions_child_type
    ON therapy_sessions (child_id, session_type);

-- --- session_activities: device-side timing ---------------------------------
-- The response-time DV is prompt-end to speech-onset. Both instants happen on
-- the tablet, so both are timed there; measuring them on arrival would fold in
-- upload latency and make the DV a property of the room's wifi.
--
-- Stored as the raw instants, not only the difference: a long gap because the
-- participant hesitated is indistinguishable from one because the recorder
-- started late, unless both ends were kept.

ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS prompt_ended_at TIMESTAMP;
ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS speech_started_at TIMESTAMP;
ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS speech_ended_at TIMESTAMP;

-- --- session_activities: recording quality ----------------------------------
-- About the recording, not the recognition. `confidence` already says how sure
-- the acoustic model was; it cannot distinguish "said it oddly" from
-- "microphone was across the room". The 2026-09-15 batch holds a two-second
-- clip of clucking and one of a bystander's conversation, and nothing in the
-- stored row said so.

ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS audio_peak DOUBLE PRECISION;
ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS audio_rms_dbfs DOUBLE PRECISION;
ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS audio_clipped_fraction DOUBLE PRECISION;
-- ok | quiet | clipped | short | long | silent
ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS audio_quality VARCHAR(12);

COMMIT;

-- What the pre-existing data looks like afterwards:
--   SELECT session_type, condition, count(*)
--   FROM therapy_sessions GROUP BY 1, 2 ORDER BY 1, 2;
-- Every row with session_type NULL is unattributable and should be excluded
-- from analysis. That is the point of recording it.
