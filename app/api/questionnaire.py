"""The in-app questionnaire, and the researcher's session note.

Keyed to `session_id` throughout. The pilot's form asked participants to type a
code like "P2" while the database keys everything by UUID, so no rating could
be attributed to a condition with certainty. That single join is the difference
between a subjective measure that supports a claim and one that cannot.

ORDER MATTERS HERE

The questionnaire is served *before* the session summary, not after it. A
participant who has just been told they scored 43 percent is not rating the
tutor any more, they are rating their own result; the correlation between
accuracy and "the tutor was helpful" would then be a property of the screen
order rather than of the feedback. The app enforces this, and this module keeps
the two on separate endpoints so it stays enforceable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import instruments, study_design
from ..utils.auth import get_current_user

router = APIRouter(tags=["questionnaire"])

#: Bumped whenever an item's wording changes. Stored with every response, so a
#: revision cannot silently pool two different questions into one column.
INSTRUMENT_VERSION = "2026-09-17.1"


class QuestionnaireSubmission(BaseModel):
    #: {item_key: 1..7}
    answers: dict[str, int] = Field(default_factory=dict)
    comment: str | None = None
    duration_seconds: int | None = None


class SessionNoteSubmission(BaseModel):
    interrupted: bool = False
    noisy_environment: bool = False
    equipment_problem: bool = False
    participant_unwell: bool = False
    language_help_given: bool = False
    exclude_recommended: bool = False
    note: str | None = None


@router.get("/sessions/{session_id}/questionnaire")
def get_questionnaire(session_id: uuid.UUID, db: Session = Depends(get_db)):
    """The scales to show after this session, or none.

    Assessments get none. There is no tutor behaviour in a pre-test to form an
    impression of -- the robot says only "thank you, here is the next one" --
    so asking would collect ratings of something that did not happen, and
    asking at all would frame the test as a performance worth reflecting on.
    """
    session = (
        db.query(models.TherapySession)
        .filter(models.TherapySession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(404, "Session not found")

    scales = instruments.for_session(session.session_type, session.condition)
    existing = (
        db.query(models.SessionQuestionnaire)
        .filter(models.SessionQuestionnaire.session_id == session_id)
        .first()
    )
    return {
        "session_id": str(session_id),
        "session_type": session.session_type,
        "applicable": bool(scales),
        "already_submitted": existing is not None,
        "instrument_version": INSTRUMENT_VERSION,
        "scale_min": instruments.SCALE_MIN,
        "scale_max": instruments.SCALE_MAX,
        "scales": [instruments.serialise(scale) for scale in scales],
    }


@router.post("/sessions/{session_id}/questionnaire")
def submit_questionnaire(
    session_id: uuid.UUID,
    submission: QuestionnaireSubmission,
    db: Session = Depends(get_db),
):
    """Store the participant's ratings against this session.

    Partial answers are accepted. Refusing to answer an item is a legitimate
    choice for a volunteer, and rejecting the whole form over one blank would
    lose six answered scales to protect one missing number; the stored count of
    answered items says how much of each scale was actually completed.
    """
    session = (
        db.query(models.TherapySession)
        .filter(models.TherapySession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(404, "Session not found")

    scales = instruments.for_session(session.session_type, session.condition)
    if not scales:
        raise HTTPException(
            409,
            f"a {session.session_type or 'ad-hoc'} session is not rated: there "
            f"is no tutor behaviour in it to form an impression of")

    known = {
        item.key
        for scale in scales for item in scale.items
        if item.kind != "single_choice"
    }
    cleaned: dict[str, int] = {}
    for key, value in submission.answers.items():
        if key not in known:
            raise HTTPException(422, f"{key!r} is not an item of this instrument")
        if not instruments.SCALE_MIN <= value <= instruments.SCALE_MAX:
            raise HTTPException(
                422,
                f"{key!r} is {value}, outside "
                f"{instruments.SCALE_MIN}..{instruments.SCALE_MAX}")
        cleaned[key] = value

    scores = {
        scale.key: instruments.score(scale, cleaned)
        for scale in scales
        if any(item.kind != "single_choice" for item in scale.items)
    }

    row = (
        db.query(models.SessionQuestionnaire)
        .filter(models.SessionQuestionnaire.session_id == session_id)
        .first()
    )
    if row is None:
        row = models.SessionQuestionnaire(
            id=uuid.uuid4(),
            session_id=session_id,
            child_id=session.child_id,
            created_at=datetime.utcnow(),
        )
        db.add(row)

    # Denormalised from the session, so a later edit elsewhere cannot rewrite
    # what this rating was a rating of.
    row.session_type = session.session_type
    row.condition = session.condition
    row.block_index = session.block_index
    row.answers = cleaned
    row.scores = scores
    row.comment = (submission.comment or "").strip()[:1000] or None
    row.instrument_version = INSTRUMENT_VERSION
    row.duration_seconds = submission.duration_seconds
    db.commit()
    db.refresh(row)

    return {
        "questionnaire_id": str(row.id),
        "session_id": str(session_id),
        "answered": len(cleaned),
        "scores": scores,
        # Deliberately not returned to the tablet in a form the participant
        # could read as a result. The means are for the analysis; the app shows
        # a thank-you.
        "message": "Thank you. Your answers were recorded.",
    }


@router.put("/sessions/{session_id}/note")
def record_session_note(
    session_id: uuid.UUID,
    submission: SessionNoteSubmission,
    db: Session = Depends(get_db),
    current_user: models.Caregiver = Depends(get_current_user),
):
    """What happened in the room, from the researcher.

    Checkboxes rather than prose. This replaces a star rating and three boxes
    asking for the researcher's view of the participant's progress, which is
    not a measure of anything here -- the recordings are -- and which invites an
    unblinded impression to sit next to the data.

    What the analysis actually needs from the room is the set of reasons a
    session might have to be excluded, and it needs them recorded quickly
    enough that they get recorded at all.
    """
    session = (
        db.query(models.TherapySession)
        .filter(models.TherapySession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(404, "Session not found")

    row = (
        db.query(models.SessionNote)
        .filter(models.SessionNote.session_id == session_id)
        .first()
    )
    if row is None:
        row = models.SessionNote(id=uuid.uuid4(), session_id=session_id,
                                 created_at=datetime.utcnow())
        db.add(row)

    row.interrupted = submission.interrupted
    row.noisy_environment = submission.noisy_environment
    row.equipment_problem = submission.equipment_problem
    row.participant_unwell = submission.participant_unwell
    row.language_help_given = submission.language_help_given
    row.exclude_recommended = submission.exclude_recommended
    row.note = (submission.note or "").strip()[:1000] or None
    row.recorded_by = current_user.id
    db.commit()
    db.refresh(row)
    return {"session_id": str(session_id), "recorded": True,
            "exclude_recommended": bool(row.exclude_recommended)}


@router.get("/sessions/{session_id}/note")
def get_session_note(session_id: uuid.UUID, db: Session = Depends(get_db)):
    row = (
        db.query(models.SessionNote)
        .filter(models.SessionNote.session_id == session_id)
        .first()
    )
    if not row:
        return {"session_id": str(session_id), "recorded": False}
    return {
        "session_id": str(session_id),
        "recorded": True,
        "interrupted": bool(row.interrupted),
        "noisy_environment": bool(row.noisy_environment),
        "equipment_problem": bool(row.equipment_problem),
        "participant_unwell": bool(row.participant_unwell),
        "language_help_given": bool(row.language_help_given),
        "exclude_recommended": bool(row.exclude_recommended),
        "note": row.note,
    }


class HelpfulnessRequest(BaseModel):
    rating: int = Field(ge=1, le=5)


@router.post("/attempts/{attempt_id}/helpfulness")
def rate_feedback(
    attempt_id: uuid.UUID,
    request: HelpfulnessRequest,
    db: Session = Depends(get_db),
):
    """Was that one correction any good?

    Asked on a sampled subset of corrections rather than all of them. A tap
    after every item would turn the session into a survey and fatigue would
    make the later answers worse than none.

    This is the measure the pilot got closest to and at the wrong grain: one
    rating per session cannot distinguish a session with one bad correction
    from one with six, and item-level variance is exactly what a K-versus-D
    contrast needs to detect a difference in how corrections land.
    """
    attempt = (
        db.query(models.SessionActivity)
        .filter(models.SessionActivity.id == attempt_id)
        .first()
    )
    if not attempt:
        raise HTTPException(404, "Attempt not found")

    session = (
        db.query(models.TherapySession)
        .filter(models.TherapySession.id == attempt.session_id)
        .first()
    )
    if session and study_design.is_assessment(session.session_type):
        raise HTTPException(
            409,
            "no feedback was given in an assessment, so there is nothing to "
            "rate; asking would also tell the participant a verdict existed")

    attempt.feedback_helpful = request.rating
    db.commit()
    return {"attempt_id": str(attempt_id), "rating": request.rating}


@router.get("/participants/{child_id}/questionnaires")
def participant_questionnaires(child_id: uuid.UUID, db: Session = Depends(get_db)):
    """Everything this participant has rated, by condition.

    The shape the analysis wants: one row per block, each carrying the
    condition that produced it.
    """
    rows = (
        db.query(models.SessionQuestionnaire)
        .filter(models.SessionQuestionnaire.child_id == child_id)
        .order_by(models.SessionQuestionnaire.created_at)
        .all()
    )
    return {
        "child_id": str(child_id),
        "responses": [
            {
                "session_id": str(row.session_id),
                "condition": row.condition,
                "block": row.block_index,
                "scores": row.scores,
                "answered": len(row.answers or {}),
                "duration_seconds": row.duration_seconds,
                "instrument_version": row.instrument_version,
                "comment": row.comment,
            }
            for row in rows
        ],
    }
