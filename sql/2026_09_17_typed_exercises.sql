-- Phase 3: turn the activity item into a typed exercise.
--
--   psql -d asd_therapy -f sql/2026_09_17_typed_exercises.sql
--
-- Safe to run twice: every statement is guarded.
--
-- WHAT THIS IS FOR
--
-- Until now every item was the same exercise: Pepper says a word, the
-- participant repeats it, the recogniser scores it. `name` served as the word,
-- the prompt and the answer key at once.
--
-- Phase 3 adds eight more types. Six are answered by tapping and never reach
-- the recogniser, which matters beyond tidiness: six of twenty pilot
-- participants complained unprompted that the robot could not hear Kenyan
-- English, and an exercise that cannot invoke the recogniser cannot
-- false-reject anyone.
--
-- Nothing here is destructive. Existing items keep exercise_type NULL, which
-- resolves to repeat_word, so every stored item and every attempt recorded
-- against it keeps meaning exactly what it meant.
--
-- See docs/PHASE3_ITEM_MODEL.md.

BEGIN;

-- --- activity_items ---------------------------------------------------------

-- repeat_word | read_sentence | picture_describe | minimal_pair_id |
-- odd_one_out | same_sound_match | syllable_count | schwa_spot | stress_place
-- NULL = repeat_word, the behaviour that predates typing.
ALTER TABLE activity_items ADD COLUMN IF NOT EXISTS exercise_type VARCHAR(24);

-- Options, answer keys, syllable breakdowns: shape determined by
-- exercise_type and validated at the API boundary. A column per type would be
-- roughly thirty mostly-null columns and a migration per new type.
ALTER TABLE activity_items ADD COLUMN IF NOT EXISTS spec JSON;

-- The Kenyan English transfer feature the item tests. The analysis is
-- per-feature; without this there is one aggregate number and no way to say
-- which contrast improved.
ALTER TABLE activity_items ADD COLUMN IF NOT EXISTS target_feature VARCHAR(32);

-- Ties an item to its counterpart in the other training list and to the
-- untrained test item for the same feature. This is what makes
-- "difficulty-matched lists" checkable instead of asserted.
ALTER TABLE activity_items ADD COLUMN IF NOT EXISTS match_key VARCHAR(32);

-- Authoring order only. Presentation order is regenerated per session from the
-- session's own seed and never comes from here.
ALTER TABLE activity_items ADD COLUMN IF NOT EXISTS position INTEGER;

CREATE INDEX IF NOT EXISTS ix_items_target_feature
    ON activity_items (target_feature);
CREATE INDEX IF NOT EXISTS ix_items_match_key
    ON activity_items (match_key);

-- --- activity_categories ----------------------------------------------------

-- list_a | list_b | test, or NULL for an ordinary practice category.
--
-- Replaces STUDY_LIST_A_CATEGORY_ID, STUDY_LIST_B_CATEGORY_ID and
-- STUDY_TEST_CATEGORY_ID. Those are three UUIDs in a .env that is not in
-- version control and, as of today, is not set -- which is what is blocking a
-- study run. The environment variables still work as a fallback so nothing
-- breaks mid-study, but the database is now preferred.
ALTER TABLE activity_categories ADD COLUMN IF NOT EXISTS study_role VARCHAR(12);

-- Two categories both claiming to be list A is not a state the design can be
-- run from, and it is not detectable afterwards from the session records.
CREATE UNIQUE INDEX IF NOT EXISTS ix_categories_study_role
    ON activity_categories (study_role)
    WHERE study_role IS NOT NULL;

-- --- session_activities -----------------------------------------------------

-- What the attempt was run as, copied from the item at the time. Denormalised
-- for the same reason condition and block_index are: retyping an item next
-- month must not move its recorded history into a different result table.
ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS exercise_type VARCHAR(24);

-- The option tapped, or the syllable indices chosen. NULL for spoken items,
-- where the answer is the recording.
ALTER TABLE session_activities ADD COLUMN IF NOT EXISTS selected_answer JSON;

COMMIT;

-- Binding the study lists after this runs, from the app or from SQL:
--
--   UPDATE activity_categories SET study_role = 'list_a' WHERE name = '...';
--   UPDATE activity_categories SET study_role = 'list_b' WHERE name = '...';
--   UPDATE activity_categories SET study_role = 'test'   WHERE name = '...';
--
-- Then GET /study/balance reports list_problems empty, and a training block
-- can be started.
