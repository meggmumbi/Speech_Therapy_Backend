"""Export the study's analysis tables from the database, one CSV per unit.

    python scripts/analysis/export_analysis.py              # writes analysis/*.csv
    python scripts/analysis/export_analysis.py --out /path

Four files, one row per unit the analysis uses:

    participants.csv    one per participant: code, group, covariates, consent
    sessions.csv        one per stamped session: type, condition, block, list
    attempts.csv        one per attempt in a stamped session, spoken or tapped
    questionnaires.csv  one per training block: the three scale means

Every column is either a stored value or a derivation stated in this file.
No name, no email, no free text that could identify someone leaves the
database: participant_code is the only identifier, and the researcher's
notes are reduced to their flags.

The definitions match app/services/dashboard.py and study_summary.py:
gated and skipped attempts are kept in the file but flagged, so that the
analysis script, not this one, decides the denominators.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="analysis", help="directory for the CSVs")
    args = parser.parse_args()
    os.environ.setdefault("DATABASE_URL", "postgresql://postgres:12345@localhost/asd_therapy")

    from app.database import SessionLocal
    from app.models import ActivityCategory, ActivityItem, Child, SessionActivity, TherapySession
    from app.models.session_questionnaire import SessionNote, SessionQuestionnaire
    from app.models.study_assignment import StudyAssignment
    from app.services import exercises

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()

    children = {c.id: c for c in db.query(Child).all()}
    assignments = {a.child_id: a for a in db.query(StudyAssignment).all()}
    categories = {c.id: c for c in db.query(ActivityCategory).all()}
    items = {i.id: i for i in db.query(ActivityItem).all()}
    sessions = (db.query(TherapySession).filter(TherapySession.session_type.isnot(None))
                .order_by(TherapySession.start_time).all())
    notes = {n.session_id: n for n in db.query(SessionNote).all()}

    # --- participants --------------------------------------------------------
    with (out / "participants.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["participant", "group", "block1", "block2", "excluded", "age", "gender", "first_language",
                    "home_language", "other_languages", "region", "english_onset_age", "medium_of_instruction",
                    "self_rated_english", "voice_assistant_use", "hearing_or_speech_difficulty",
                    "consent_participation", "consent_audio_retention"])
        for c in children.values():
            a = assignments.get(c.id)
            w.writerow([c.participant_code, a.group_index if a else None,
                        f"{a.block1_condition}-{a.block1_list}" if a else None,
                        f"{a.block2_condition}-{a.block2_list}" if a else None,
                        a.excluded if a else None, c.age, c.gender, c.first_language, c.home_language,
                        c.other_languages, c.region_of_upbringing, c.english_onset_age,
                        c.primary_medium_of_instruction, c.self_rated_english, c.voice_assistant_use,
                        c.hearing_or_speech_difficulty, c.consent_participation, c.consent_audio_retention])

    # --- sessions -------------------------------------------------------------
    def list_of(s: TherapySession) -> str | None:
        c = categories.get(s.category_id)
        return c.study_role if c else None

    with (out / "sessions.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["session", "participant", "session_type", "condition", "block", "list", "started", "ended",
                    "minutes", "completed", "ended_early", "note_interrupted", "note_noisy", "note_equipment",
                    "note_unwell", "note_language_help", "note_exclude_recommended"])
        for s in sessions:
            c = children.get(s.child_id)
            n = notes.get(s.id)
            minutes = round((s.end_time - s.start_time).total_seconds() / 60, 2) if s.end_time and s.start_time else None
            w.writerow([s.id, c.participant_code if c else None, s.session_type, s.condition, s.block_index,
                        list_of(s), s.start_time, s.end_time, minutes, s.is_completed, s.ended_early,
                        *(getattr(n, k) if n else False for k in
                          ("interrupted", "noisy_environment", "equipment_problem", "participant_unwell",
                           "language_help_given", "exclude_recommended"))])

    # --- attempts -------------------------------------------------------------
    session_by_id = {s.id: s for s in sessions}
    attempts = (db.query(SessionActivity)
                .filter(SessionActivity.session_id.in_(list(session_by_id)))
                .order_by(SessionActivity.created_at).all()) if sessions else []
    # Final attempt per (session, item): the one the item's outcome is read from.
    latest: dict[tuple, SessionActivity] = {}
    for a in attempts:
        key = (a.session_id, a.item_id)
        if key not in latest or (a.attempt_number or 0) >= (latest[key].attempt_number or 0):
            latest[key] = a
    first: dict[tuple, SessionActivity] = {}
    for a in attempts:
        key = (a.session_id, a.item_id)
        if key not in first or (a.attempt_number or 0) < (first[key].attempt_number or 0):
            first[key] = a

    with (out / "attempts.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["attempt", "participant", "session", "session_type", "condition", "block", "list",
                    "item", "item_name", "exercise_type", "spoken", "target_feature", "match_key",
                    "attempt_number", "is_first", "is_final", "correct", "verdict", "verdict_score",
                    "graded_score", "confidence", "gated", "skipped", "skip_reason", "transcript_matches",
                    "response_time_s", "prompt_replays", "slow_replay", "celebration", "feedback_words",
                    "named_phone", "audio_quality", "audio_peak", "audio_rms_dbfs", "config_hash", "recorded_at"])
        for a in attempts:
            s = session_by_id[a.session_id]
            c = children.get(s.child_id)
            it = items.get(a.item_id)
            etype = a.exercise_type or (it.effective_type if it else None)
            key = (a.session_id, a.item_id)
            w.writerow([a.id, c.participant_code if c else None, s.id, s.session_type, s.condition, s.block_index,
                        list_of(s), a.item_id, it.name if it else None, etype, exercises.needs_asr(etype),
                        it.target_feature if it else None, it.match_key if it else None,
                        a.attempt_number, first[key] is a, latest[key] is a,
                        None if (a.gated or a.skipped) else bool(a.is_correct), a.verdict, a.verdict_score,
                        a.pronunciation_score, a.confidence, bool(a.gated), bool(a.skipped), a.skip_reason,
                        a.transcript_matches, a.response_time_seconds, a.prompt_replays, a.slow_replay_used,
                        a.celebration_shown, a.feedback_word_count, a.named_phone, a.audio_quality,
                        a.audio_peak, a.audio_rms_dbfs, a.config_hash, a.created_at])

    # --- questionnaires ----------------------------------------------------------
    with (out / "questionnaires.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["session", "participant", "condition", "block", "godspeed", "motivation", "feedback_trust",
                    "duration_seconds", "instrument_version"])
        for q in db.query(SessionQuestionnaire).all():
            c = children.get(q.child_id)
            sc = q.scores or {}
            w.writerow([q.session_id, c.participant_code if c else None, q.condition, q.block_index,
                        (sc.get("godspeed") or {}).get("mean"), (sc.get("motivation") or {}).get("mean"),
                        (sc.get("feedback_trust") or {}).get("mean"), q.duration_seconds, q.instrument_version])

    print(f"{len(children)} participants, {len(sessions)} sessions, {len(attempts)} attempts -> {out}/")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
