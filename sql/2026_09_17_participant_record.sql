-- Phase 1: turn the clinical child record into a study participant record.
--
--   psql -d asd_therapy -f sql/2026_09_17_participant_record.sql
--
-- Safe to run twice: every statement is guarded.
--
-- WHAT THIS DROPS AND WHY
--
-- children.diagnosis_date and children.therapy_goals are removed. They are ASD
-- clinical fields. The study now enrols consenting adult volunteers to practise
-- English pronunciation, and a diagnosis date collected from a healthy
-- volunteer is special-category health data under the Data Protection Act 2019
-- with no purpose that would justify holding it. Keeping an unused column of
-- health data is a liability, not a convenience.
--
-- children.name is NOT dropped, so that rows created before this change still
-- load, but nothing writes to it any more. participant_code is the identifier.
-- The code-to-name link lives on paper with the researcher.
--
-- BEFORE YOU RUN THIS, if the database holds data you care about:
--   \copy (SELECT id, name, diagnosis_date, therapy_goals FROM children)
--         TO 'children_clinical_backup.csv' CSV HEADER
-- then store that file somewhere appropriate or, better, delete it.

BEGIN;

-- --- identity ---------------------------------------------------------------

ALTER TABLE children ADD COLUMN IF NOT EXISTS participant_code VARCHAR(32);

-- Unique so two researchers cannot enrol the same code twice and silently merge
-- two people's sessions into one participant. Partial, so the rows that predate
-- this migration (code NULL) do not all collide with each other.
CREATE UNIQUE INDEX IF NOT EXISTS ix_children_participant_code
    ON children (participant_code)
    WHERE participant_code IS NOT NULL;

-- Was NOT NULL when a name was required at enrolment. New records do not carry
-- one, so the constraint has to go or every insert fails.
ALTER TABLE children ALTER COLUMN name DROP NOT NULL;

ALTER TABLE children ADD COLUMN IF NOT EXISTS gender VARCHAR(40);

-- --- language background ----------------------------------------------------

ALTER TABLE children ADD COLUMN IF NOT EXISTS first_language VARCHAR(60);
ALTER TABLE children ADD COLUMN IF NOT EXISTS other_languages VARCHAR(200);
ALTER TABLE children ADD COLUMN IF NOT EXISTS home_language VARCHAR(60);
ALTER TABLE children ADD COLUMN IF NOT EXISTS region_of_upbringing VARCHAR(80);
ALTER TABLE children ADD COLUMN IF NOT EXISTS english_onset_age INTEGER;
ALTER TABLE children ADD COLUMN IF NOT EXISTS primary_medium_of_instruction VARCHAR(20);
ALTER TABLE children ADD COLUMN IF NOT EXISTS self_rated_english VARCHAR(2);

-- --- controls ---------------------------------------------------------------

ALTER TABLE children ADD COLUMN IF NOT EXISTS voice_assistant_use VARCHAR(10);
ALTER TABLE children ADD COLUMN IF NOT EXISTS hearing_or_speech_difficulty BOOLEAN DEFAULT FALSE;
ALTER TABLE children ADD COLUMN IF NOT EXISTS hearing_or_speech_note VARCHAR(300);

-- --- ethics trail -----------------------------------------------------------
-- Two flags, not one: someone may agree to take part while refusing to have
-- their audio kept afterwards. Scoring needs the audio in the moment; retention
-- for the rater sample does not follow from that.

ALTER TABLE children ADD COLUMN IF NOT EXISTS consent_participation BOOLEAN DEFAULT FALSE;
ALTER TABLE children ADD COLUMN IF NOT EXISTS consent_audio_retention BOOLEAN DEFAULT FALSE;
ALTER TABLE children ADD COLUMN IF NOT EXISTS consent_date DATE;

-- --- remove the clinical fields ---------------------------------------------

ALTER TABLE children DROP COLUMN IF EXISTS diagnosis_date;
ALTER TABLE children DROP COLUMN IF EXISTS therapy_goals;

COMMIT;

-- Verify:
--   SELECT column_name, data_type FROM information_schema.columns
--   WHERE table_name = 'children' ORDER BY ordinal_position;
