"""Everything the dashboard shows, in one pass over tables that already exist.

Read-only. Every number here is a query the analysis will also make, so the
definitions must match what the summaries and the paper use: accuracy is over
final attempts with gated and skipped ones excluded, training only; the
questionnaire means are the stored per-scale means, split by the condition the
block was run under.

Nothing is forecast and nothing is a target the code invents. The recruitment
target is a parameter the researcher sets; until they do it is null and the
tile says so.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from . import exercises, study_design

#: The five steps, in protocol order. Ordered here so the funnel is ordinal.
STEPS: tuple[tuple[str, str], ...] = (
    ("pretest", "Pre-test"), ("block1", "Block 1"), ("block2", "Block 2"),
    ("posttest", "Post-test"), ("delayed", "Delayed"),
)

#: Recording verdicts folded onto the four status meanings a reader can act on.
#: ok is clean; quiet is fixable by moving the microphone; clipped is fixable
#: by moving it the other way; the rest were lost and cannot be recovered.
QUALITY_FOLD: dict[str, str] = {
    "ok": "clean", "quiet": "quiet", "clipped": "clipped",
    "short": "lost", "long": "lost", "silent": "lost",
}


def _step_of(session: models.TherapySession) -> str | None:
    if session.session_type == study_design.TRAINING:
        return f"block{session.block_index}" if session.block_index in (1, 2) else None
    if session.session_type in study_design.ASSESSMENT_PHASES:
        return session.session_type
    return None


def _final_attempts(rows: list[models.SessionActivity]) -> list[models.SessionActivity]:
    latest: dict[Any, models.SessionActivity] = {}
    for a in rows:
        # The revisit round is its own measure, not the item's outcome.
        if getattr(a, "revisit", False):
            continue
        key = (a.session_id, a.item_id)
        cur = latest.get(key)
        if cur is None or (a.attempt_number or 0) >= (cur.attempt_number or 0):
            latest[key] = a
    return list(latest.values())


def _rate(num: int, den: int) -> float | None:
    return round(num / den * 100, 1) if den else None


def build(db: Session, recruitment_target: int | None = None) -> dict:
    children = db.query(models.Child).all()
    assignments = {a.child_id: a for a in db.query(models.StudyAssignment).all()}
    sessions = db.query(models.TherapySession).filter(
        models.TherapySession.session_type.isnot(None)).all()
    session_ids = [s.id for s in sessions]
    attempts = (db.query(models.SessionActivity)
                .filter(models.SessionActivity.session_id.in_(session_ids)).all()
                if session_ids else [])
    questionnaires = db.query(models.SessionQuestionnaire).all()
    notes = {n.session_id: n for n in db.query(models.SessionNote).all()}

    # --- participants -------------------------------------------------------
    consented = [c for c in children if c.consent_participation]
    steps_done: dict[Any, set[str]] = defaultdict(set)
    for s in sessions:
        step = _step_of(s)
        if step:
            steps_done[s.child_id].add(step)
    complete = sum(1 for c in children if len(steps_done.get(c.id, ())) == len(STEPS))
    started = sum(1 for c in children if steps_done.get(c.id))
    excluded = sum(1 for a in assignments.values() if a.excluded)

    participants = {
        "enrolled": len(children),
        "consented": len(consented),
        "needs_code": sum(1 for c in children if not c.participant_code),
        "assigned": sum(1 for a in assignments.values() if not a.excluded),
        "started": started,
        "complete": complete,
        "excluded": excluded,
        "target": recruitment_target,
    }

    # --- cells --------------------------------------------------------------
    cells: dict[str, int] = {study_design.describe_group(g): 0 for g in range(study_design.N_GROUPS)}
    for a in assignments.values():
        if not a.excluded:
            cells[study_design.describe_group(a.group_index)] += 1

    # --- protocol funnel ----------------------------------------------------
    per_step = {key: {"started": 0, "completed": 0} for key, _ in STEPS}
    for s in sessions:
        step = _step_of(s)
        if step in per_step:
            per_step[step]["started"] += 1
            if s.is_completed:
                per_step[step]["completed"] += 1
    funnel = [{"step": key, "label": label, **per_step[key]} for key, label in STEPS]

    # --- accuracy by condition, training only ------------------------------
    by_session = {s.id: s for s in sessions}
    training = [a for a in attempts
                if by_session.get(a.session_id) and by_session[a.session_id].session_type == study_design.TRAINING]
    finals = _final_attempts(training)
    scorable = [a for a in finals if not a.gated and not a.skipped]
    accuracy = []
    for condition in ("K", "D"):
        rows = [a for a in scorable if by_session[a.session_id].condition == condition]
        spoken = [a for a in rows if exercises.needs_asr(a.exercise_type)]
        tapped = [a for a in rows if not exercises.needs_asr(a.exercise_type)]
        accuracy.append({
            "condition": condition,
            "attempts": len(rows),
            "accuracy": _rate(sum(1 for a in rows if a.is_correct), len(rows)),
            "spoken_accuracy": _rate(sum(1 for a in spoken if a.is_correct), len(spoken)),
            "tapped_accuracy": _rate(sum(1 for a in tapped if a.is_correct), len(tapped)),
            "participants": len({by_session[a.session_id].child_id for a in rows}),
        })

    # --- what happened around the attempts ----------------------------------
    engagement = {
        "attempts": len(attempts),
        "gated": sum(1 for a in attempts if a.gated),
        "skipped": sum(1 for a in attempts if a.skipped),
        "replays": sum(a.prompt_replays or 0 for a in attempts),
        "slow_replays": sum(1 for a in attempts if a.slow_replay_used),
        "helpfulness_ratings": sum(1 for a in attempts if a.feedback_helpful is not None),
        "helpfulness_mean": (round(sum(a.feedback_helpful for a in attempts if a.feedback_helpful is not None)
                                   / max(1, sum(1 for a in attempts if a.feedback_helpful is not None)), 2)
                             if any(a.feedback_helpful is not None for a in attempts) else None),
    }

    # --- questionnaire means by condition -----------------------------------
    scales = ("godspeed", "motivation", "feedback_trust")
    ratings = []
    for condition in ("K", "D"):
        rows = [q for q in questionnaires if q.condition == condition and q.scores]
        entry: dict[str, Any] = {"condition": condition, "n": len(rows)}
        for scale in scales:
            vals = [q.scores[scale]["mean"] for q in rows
                    if q.scores.get(scale) and q.scores[scale].get("mean") is not None]
            entry[scale] = round(sum(vals) / len(vals), 2) if vals else None
        ratings.append(entry)

    # --- recording quality per day ------------------------------------------
    per_day: dict[str, dict[str, int]] = defaultdict(lambda: {"clean": 0, "quiet": 0, "clipped": 0, "lost": 0})
    for a in attempts:
        if a.audio_quality and a.created_at:
            per_day[a.created_at.date().isoformat()][QUALITY_FOLD.get(a.audio_quality, "lost")] += 1
    quality = [{"day": day, **counts} for day, counts in sorted(per_day.items())][-30:]

    # --- recent sessions -----------------------------------------------------
    code_of = {c.id: (c.participant_code or f"participant {str(c.id)[:8]}") for c in children}
    recent = []
    for s in sorted(sessions, key=lambda x: x.start_time or datetime.min, reverse=True)[:12]:
        rows = [a for a in attempts if a.session_id == s.id]
        note = notes.get(s.id)
        recent.append({
            "session_id": str(s.id),
            "participant": code_of.get(s.child_id, "?"),
            "step": _step_of(s),
            "condition": s.condition,
            "started_at": s.start_time.isoformat() if s.start_time else None,
            "completed": bool(s.is_completed),
            "ended_early": bool(s.ended_early),
            "attempts": len(rows),
            "unusable_recordings": sum(1 for a in rows if a.audio_quality and a.audio_quality != "ok"),
            "flagged": bool(note and (note.exclude_recommended or note.equipment_problem or note.interrupted)),
        })

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "participants": participants,
        "cells": [{"group": g, "count": n} for g, n in cells.items()],
        "funnel": funnel,
        "accuracy": accuracy,
        "engagement": engagement,
        "ratings": ratings,
        "quality": quality,
        "recent": recent,
        # Phase 6 supplies this from the rater sample. Reported as null rather
        # than omitted, so the tile exists and says "not yet" instead of the
        # reader wondering whether it was forgotten.
        "false_correction_rate": None,
        "list_problems": study_design.validate_lists(db),
    }
