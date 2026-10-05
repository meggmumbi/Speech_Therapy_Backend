"""What to show after a session ends.

Replaces the old analytics overview for study sessions, which was written for
the ASD therapy app and carries three assumptions that are now wrong.

**It scored assessments.** The overview computed an accuracy percentage and
wrote "Excellent progress! Ready for more challenging activities" whatever the
session was. Shown after a pre-test that is feedback, and the whole point of an
assessment is that the participant leaves it knowing nothing about how they
did. The in-session path has guarded this since Phase 2; the summary screen was
still a way around it.

**It reported a duration of zero.** `end_time` was only ever set by the ad-hoc
`/activities/next-item` route. A study session walks a fixed list on the device
and never calls it, so every study session had `end_time` NULL and every
summary said zero minutes.

**It averaged incomparable things.** Gated attempts, which are explicitly
excluded from correction-rate denominators, counted as errors. Perception items
and production items went into one accuracy figure. And nothing was grouped by
target feature, which is the entire reason Phase 3 put a feature on every item.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session, joinedload

from .. import models
from . import exercises, study_design


def _duration_minutes(session: models.TherapySession,
                      activities: list[models.SessionActivity]) -> float | None:
    """How long the session ran.

    Falls back to the span of its attempts when `end_time` was never set, which
    is every study session recorded before the complete endpoint existed.
    Returns None rather than 0.0 when there is nothing to measure: a session
    with one attempt has an unknown duration, not a zero one, and 0.0 would be
    averaged into a mean as though it were observed.
    """
    if session.end_time and session.start_time:
        return round((session.end_time - session.start_time).total_seconds() / 60, 1)
    stamps = [a.created_at for a in activities if a.created_at]
    if len(stamps) < 2:
        return None
    start = session.start_time or min(stamps)
    return round((max(stamps) - start).total_seconds() / 60, 1)


def _scorable(activity: models.SessionActivity) -> bool:
    """Does this attempt belong in a correction-rate denominator?

    A gated attempt is one the recogniser was not confident enough to judge,
    and a skipped one is a person declining. Neither is evidence that the word
    was produced wrongly, and counting either as an error is the false
    rejection this system exists to avoid.
    """
    return not activity.gated and not activity.skipped


def _final_attempts(activities: list[models.SessionActivity]) -> list[models.SessionActivity]:
    """The last attempt at each item.

    Accuracy over every attempt double-counts any item that was retried, and
    retries only happen after an error, so it is biased downwards by exactly
    the items the participant went on to get right.
    """
    latest: dict[Any, models.SessionActivity] = {}
    for activity in activities:
        # A revisit is a later, separate measure of the same item, not the
        # outcome of the main round; see study_design.revisit_item_ids.
        if getattr(activity, "revisit", False):
            continue
        current = latest.get(activity.item_id)
        if current is None or (activity.attempt_number or 0) >= (current.attempt_number or 0):
            latest[activity.item_id] = activity
    return list(latest.values())


def _rate(correct: int, total: int) -> float | None:
    return round(correct / total * 100, 1) if total else None


def build(db: Session, session_id: uuid.UUID) -> dict:
    session = (
        db.query(models.TherapySession)
        .options(
            joinedload(models.TherapySession.child),
            joinedload(models.TherapySession.category),
            joinedload(models.TherapySession.activities)
            .joinedload(models.SessionActivity.item),
        )
        .filter(models.TherapySession.id == session_id)
        .first()
    )
    if not session:
        raise ValueError("Session not found")

    activities = sorted(session.activities, key=lambda a: a.created_at or datetime.min)
    finals = _final_attempts(activities)
    is_assessment = study_design.is_assessment(session.session_type)

    items_seen = len({a.item_id for a in activities})
    total_items = (
        db.query(models.ActivityItem)
        .filter(models.ActivityItem.category_id == session.category_id)
        .count()
    )

    body: dict[str, Any] = {
        "session_id": str(session.id),
        "participant_code": session.child.label if session.child else None,
        # Kept under the old key so the app's existing binding does not break;
        # it has held the pseudonymous code rather than a name since Phase 1.
        "child_name": session.child.label if session.child else None,
        "category_name": session.category.name if session.category else None,
        "start_time": session.start_time.isoformat() if session.start_time else None,
        "session_type": session.session_type,
        "condition": session.condition,
        "block_index": session.block_index,
        "gives_feedback": not is_assessment,
        "is_completed": bool(session.is_completed),
        "ended_early": bool(session.ended_early),
        "duration_minutes": _duration_minutes(session, activities),
        "items_attempted": items_seen,
        "items_total": total_items,
        "total_activities": len(activities),
        "skipped": sum(1 for a in activities if a.skipped),
        "replays": sum(a.prompt_replays or 0 for a in activities),
        "slow_replays": sum(1 for a in activities if a.slow_replay_used),
        "recording_quality": _quality_counts(activities),
        "average_response_time": _average_response(finals),
    }

    if is_assessment:
        # Everything below this line is a verdict, and an assessment gives
        # none. The participant is standing at the tablet when this screen
        # appears; a percentage here would teach them as surely as the robot
        # saying it out loud, and the post-test would then be measuring the
        # pre-test.
        body.update({
            "scored": False,
            "accuracy_percentage": None,
            "correct_answers": None,
            "activities": [_activity_row(a, reveal=False) for a in activities],
            "by_exercise": None,
            "by_feature": None,
            "strengths": [],
            "areas_for_improvement": [],
            "recommendations": [],
            "note": "Assessment sessions are not scored in the app. Results "
                    "come from the recordings during analysis.",
        })
        return body

    scorable = [a for a in finals if _scorable(a)]
    correct = sum(1 for a in scorable if a.is_correct)

    body.update({
        "scored": True,
        "correct_answers": correct,
        "accuracy_percentage": _rate(correct, len(scorable)),
        "excluded_from_accuracy": len(finals) - len(scorable),
        "activities": [_activity_row(a, reveal=True) for a in activities],
        "by_exercise": _grouped(scorable, lambda a: a.exercise_type or "repeat_word"),
        # The reason Phase 3 put a feature on every item: one aggregate number
        # cannot say which contrast improved.
        "by_feature": _grouped(
            [a for a in scorable if a.item and a.item.target_feature],
            lambda a: a.item.target_feature),
        "strengths": _names(scorable, correct=True),
        "areas_for_improvement": _names(scorable, correct=False),
        "recommendations": _recommendations(scorable),
    })
    return body


def _activity_row(activity: models.SessionActivity, reveal: bool) -> dict:
    row: dict[str, Any] = {
        "item_name": activity.item.name if activity.item else None,
        "exercise_type": activity.exercise_type or "repeat_word",
        "target_feature": activity.item.target_feature if activity.item else None,
        "attempt_number": activity.attempt_number,
        "response_time": activity.response_time_seconds,
        "audio_quality": activity.audio_quality,
        "skipped": bool(activity.skipped),
        "replays": activity.prompt_replays or 0,
    }
    if reveal:
        row.update({
            "is_correct": activity.is_correct,
            "verdict": activity.verdict,
            "score": activity.verdict_score,
            "feedback": activity.feedback,
            "gated": bool(activity.gated),
        })
    return row


def _grouped(activities: list[models.SessionActivity], key) -> list[dict]:
    buckets: dict[str, list[models.SessionActivity]] = {}
    for activity in activities:
        buckets.setdefault(key(activity), []).append(activity)
    out = []
    for name, group in sorted(buckets.items()):
        correct = sum(1 for a in group if a.is_correct)
        out.append({
            "key": name,
            "label": _label_for(name),
            "attempted": len(group),
            "correct": correct,
            "accuracy_percentage": _rate(correct, len(group)),
        })
    return out


def _label_for(key: str) -> str:
    if key in exercises.BY_KEY:
        return exercises.BY_KEY[key].label
    if key in exercises.FEATURES_BY_KEY:
        return exercises.FEATURES_BY_KEY[key].label
    return key.replace("_", " ").capitalize()


def _names(activities: list[models.SessionActivity], correct: bool) -> list[str]:
    return sorted({
        a.item.name for a in activities
        if a.item and a.item.name and bool(a.is_correct) is correct
    })


def _average_response(activities: list[models.SessionActivity]) -> float | None:
    times = [a.response_time_seconds for a in activities
             if a.response_time_seconds is not None and not a.skipped]
    return round(sum(times) / len(times), 2) if times else None


def _quality_counts(activities: list[models.SessionActivity]) -> dict[str, int]:
    """How usable the recordings were, for the researcher.

    Surfaced on the summary rather than buried in a column because a session
    whose recordings were mostly unusable is one to re-run, and that decision
    has to be made while the participant is still in the room.
    """
    counts: dict[str, int] = {}
    for activity in activities:
        if activity.audio_quality:
            counts[activity.audio_quality] = counts.get(activity.audio_quality, 0) + 1
    return counts


def _recommendations(activities: list[models.SessionActivity]) -> list[str]:
    """What to do next, or nothing.

    The old version always said something, including "Excellent progress!
    Ready for more challenging activities" after a session with four attempts.
    Advice with no evidence behind it is noise the researcher learns to skip,
    and then misses the one line that mattered.
    """
    out: list[str] = []
    if len(activities) < 5:
        return out

    by_feature: dict[str, list[models.SessionActivity]] = {}
    for activity in activities:
        if activity.item and activity.item.target_feature:
            by_feature.setdefault(activity.item.target_feature, []).append(activity)

    weak = [
        (feature, group) for feature, group in by_feature.items()
        if len(group) >= 2 and sum(1 for a in group if a.is_correct) / len(group) < 0.5
    ]
    for feature, group in sorted(weak, key=lambda pair: len(pair[1]), reverse=True)[:2]:
        out.append(
            f"{_label_for(feature)}: {sum(1 for a in group if a.is_correct)} of "
            f"{len(group)} correct. Worth more practice.")

    unusable = sum(1 for a in activities
                   if a.audio_quality and a.audio_quality != "ok")
    if unusable and unusable / len(activities) > 0.2:
        out.append(
            f"{unusable} of {len(activities)} recordings were not clean. Check "
            f"the microphone distance before the next session.")
    return out
