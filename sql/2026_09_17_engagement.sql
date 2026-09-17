-- Phase 4: the engagement layer, and the things it has to record.
--
--   psql -d asd_therapy -f sql/2026_09_17_engagement.sql
--
-- Safe to run twice: every statement is guarded.
--
-- WHAT THIS IS FOR
--
-- Three affordances came straight out of pilot feedback, and each of them
-- changes what an attempt means, so each has to be recorded rather than just
-- offered.
--
-- P18 said "the pacing was a little bit fast" and P6 asked for pauses to
-- process. A replay button answers both, but an item heard four times is not
-- the same trial as an item heard once, and an analysis that cannot tell them
-- apart is comparing different things.
--
-- A skip is not a wrong answer. Without somewhere to say so it would be stored
-- as one, and a participant who could not produce a word would look identical
-- to one who produced it wrongly -- which is the false-rejection failure this
-- system exists to avoid, arriving through the back door.
--
-- P7, P13 and P18 independently named Pepper's movement and its "yay" as what
-- gave them confidence. That is an embodiment effect worth measuring rather
-- than merely keeping, and it cannot be measured if nothing records when it
-- fired.

BEGIN;

-- --- session_activities -----------------------------------------------------

-- The participant asked to hear the prompt again, and how often. Zero, not
-- NULL, is the normal case; NULL means the attempt predates this column.
ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS prompt_replays INTEGER;

-- Replayed at reduced speed at least once. Separate from the count because
-- slowing the model down changes the stimulus, not just the pacing.
ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS slow_replay_used BOOLEAN;

-- The participant declined this item. Excluded from correction-rate
-- denominators exactly as a gated attempt is, but for a different reason, so
-- it is a different column: gated means the recogniser was not confident,
-- skipped means the person chose not to answer.
ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS skipped BOOLEAN;
ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS skip_reason VARCHAR(20);

-- Whether the celebration animation and "yay" actually played for this
-- attempt. Not inferable from is_correct: it does not fire in an assessment,
-- and the robot may have lost focus.
ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS celebration_shown BOOLEAN;

CREATE INDEX IF NOT EXISTS ix_activities_session
    ON session_activities (session_id);

-- --- therapy_sessions -------------------------------------------------------

-- Set when the participant reaches the end of the item list, or when the
-- researcher ends the session early.
--
-- end_time was only ever set by the ad-hoc /activities next-item route. A study
-- session walks a fixed list on the device and never calls it, so every study
-- session had end_time NULL and every session summary reported a duration of
-- zero minutes.
ALTER TABLE therapy_sessions ADD COLUMN IF NOT EXISTS ended_early BOOLEAN;

COMMIT;

-- Sessions still missing an end time after this, which is every study session
-- recorded before today:
--   SELECT id, session_type, start_time FROM therapy_sessions
--   WHERE end_time IS NULL AND session_type IS NOT NULL;
-- The summary now derives a duration from the attempts themselves for those,
-- rather than reporting zero.
