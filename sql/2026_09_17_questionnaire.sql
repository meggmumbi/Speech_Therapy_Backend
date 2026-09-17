-- Phase 5: measurement instruments.
--
--   psql -d asd_therapy -f sql/2026_09_17_questionnaire.sql
--
-- Safe to run twice: every statement is guarded.
--
-- WHAT THIS IS FOR
--
-- The pilot's subjective measures came from a Google Form that asked the
-- participant to type a code like "P2" while the database keys everything by
-- UUID. No rating can be attributed to a condition with certainty, so every
-- subjective measure from that round is unusable for the K-versus-D
-- comparison, however good the items were. Keying the questionnaire to
-- session_id is the whole fix.
--
-- Two of the form's items were also broken on the page -- "The tutor caught my"
-- and "The tutor was likable attention" are one line split in the wrong place,
-- and "likable" appears twice -- so those columns cannot be scored at all.
--
-- And the scales ceilinged. Pleasant, kind, friendly and likable all sat at
-- strongly-agree, enjoyment at 14 of 20. A measure everyone maxes out cannot
-- show a difference between conditions.

BEGIN;

-- --- what the participant said ----------------------------------------------

CREATE TABLE IF NOT EXISTS session_questionnaires (
    id                  UUID PRIMARY KEY,
    -- One questionnaire per session. A second submission is an edit of the
    -- first, not another observation.
    session_id          UUID UNIQUE REFERENCES therapy_sessions(id),
    child_id            UUID REFERENCES children(id),

    -- Copied from the session at submission, for the same reason condition and
    -- block_index are copied onto sessions and attempts: a later edit
    -- elsewhere must not be able to rewrite what this rating was a rating of.
    session_type        VARCHAR(12),
    condition           VARCHAR(1),
    block_index         INTEGER,

    answers             JSON,      -- {item_key: 1..7}
    scores              JSON,      -- {scale_key: mean}, computed at submission
    comment             VARCHAR(1000),

    -- Which wording was on screen. Without it, revising an item would silently
    -- pool two different questions into one column.
    instrument_version  VARCHAR(20),

    -- A questionnaire finished in eleven seconds is straight-lining, and the
    -- analysis should be able to see that rather than infer it from
    -- suspiciously round means.
    duration_seconds    INTEGER,

    created_at          TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_questionnaires_child
    ON session_questionnaires (child_id);
CREATE INDEX IF NOT EXISTS ix_questionnaires_condition
    ON session_questionnaires (condition);

-- --- what the researcher observed -------------------------------------------
--
-- Replaces the caregiver feedback dialog: a star rating plus three boxes of
-- clinical prose, inherited from the ASD therapy app. In a pronunciation study
-- the researcher's opinion of a participant's progress is not a measure of
-- anything -- the recordings are -- and asking for it invites an unblinded
-- impression to sit next to the data.
--
-- What is worth recording is what would make a session unusable, and that is a
-- handful of checkboxes, because it has to be quick enough to fill in between
-- participants.

CREATE TABLE IF NOT EXISTS session_notes (
    id                    UUID PRIMARY KEY,
    session_id            UUID UNIQUE REFERENCES therapy_sessions(id),

    interrupted           BOOLEAN DEFAULT FALSE,
    noisy_environment     BOOLEAN DEFAULT FALSE,
    equipment_problem     BOOLEAN DEFAULT FALSE,
    participant_unwell    BOOLEAN DEFAULT FALSE,
    language_help_given   BOOLEAN DEFAULT FALSE,

    exclude_recommended   BOOLEAN DEFAULT FALSE,
    note                  VARCHAR(1000),

    recorded_by           UUID REFERENCES caregivers(id),
    created_at            TIMESTAMP DEFAULT now()
);

-- --- per-event feedback rating ----------------------------------------------
--
-- One rating per session was the most useful item in the pilot data (16 of 20
-- said the feedback was "accurate and specific") and it is measured at the
-- wrong grain: it cannot distinguish a session with one bad correction from
-- one with six, and it is exactly the contrast between K and D that needs
-- item-level variance to detect.
--
-- Asked on a sampled subset of attempts rather than all of them. Asking after
-- every correction would add a tap to every item and turn the session into a
-- survey, and fatigue would make the later answers worse than no answers.

ALTER TABLE session_activities
    ADD COLUMN IF NOT EXISTS feedback_helpful INTEGER;   -- 1..5, NULL = not asked

COMMIT;
