"""Study administration: counterbalancing assignment and block sessions.

The experimenter's surface for running the K-vs-D study. Two things happen
here that must not happen anywhere else:

* a participant is assigned to a counterbalancing group, **once**, and
* a session is created already stamped with the condition and word list that
  the assignment dictates.

Sessions created through the ordinary ``/activities/sessions/`` route have no
condition, and the scoring endpoint would fall back to ``D`` for them. Study
sessions must be created here so the condition is never implicit.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import study_design
from ..utils.auth import get_current_user

router = APIRouter(tags=["study"])


class StartBlockRequest(BaseModel):
    child_id: uuid.UUID
    block: int          # 1 or 2
    current_level: str | None = None


class StartAssessmentRequest(BaseModel):
    child_id: uuid.UUID
    # 'pretest' | 'posttest' | 'delayed'
    phase: str


class ExcludeRequest(BaseModel):
    reason: str


def _active_counts(db: Session) -> dict[int, int]:
    rows = (
        db.query(models.StudyAssignment.group_index)
        .filter(models.StudyAssignment.excluded.is_(False))
        .all()
    )
    counts: dict[int, int] = {g: 0 for g in range(study_design.N_GROUPS)}
    for (group,) in rows:
        counts[group] = counts.get(group, 0) + 1
    return counts


def _serialise(assignment: models.StudyAssignment) -> dict:
    return {
        "child_id": str(assignment.child_id),
        "group_index": assignment.group_index,
        "group": study_design.describe_group(assignment.group_index),
        "blocks": [
            {"block": 1, "condition": assignment.block1_condition,
             "word_list": assignment.block1_list},
            {"block": 2, "condition": assignment.block2_condition,
             "word_list": assignment.block2_list},
        ],
        "excluded": bool(assignment.excluded),
        "exclusion_reason": assignment.exclusion_reason,
        "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None,
    }


@router.post("/participants/{child_id}/assignment")
def assign_participant(
    child_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: models.Caregiver = Depends(get_current_user),
):
    """Assign a participant to a counterbalancing group.

    Idempotent: calling it again returns the existing assignment rather than
    re-rolling. Re-assignment mid-study would break the counterbalance in a way
    that could not be detected afterwards from the session records.
    """
    child = db.query(models.Child).filter(models.Child.id == child_id).first()
    if not child:
        raise HTTPException(404, "Child not found")

    existing = (
        db.query(models.StudyAssignment)
        .filter(models.StudyAssignment.child_id == child_id)
        .first()
    )
    if existing:
        return {"created": False, **_serialise(existing)}

    group_index = study_design.choose_group(_active_counts(db), child_id)
    first, second = study_design.blocks_for(group_index)

    assignment = models.StudyAssignment(
        child_id=child_id,
        group_index=group_index,
        block1_condition=first.condition,
        block1_list=first.word_list,
        block2_condition=second.condition,
        block2_list=second.word_list,
        excluded=False,
        assigned_at=datetime.utcnow(),
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return {"created": True, **_serialise(assignment)}


@router.get("/participants/{child_id}/assignment")
def get_assignment(child_id: uuid.UUID, db: Session = Depends(get_db)):
    assignment = (
        db.query(models.StudyAssignment)
        .filter(models.StudyAssignment.child_id == child_id)
        .first()
    )
    if not assignment:
        raise HTTPException(404, "No assignment for this participant")
    return _serialise(assignment)


@router.post("/participants/{child_id}/exclude")
def exclude_participant(
    child_id: uuid.UUID,
    request: ExcludeRequest,
    db: Session = Depends(get_db),
    current_user: models.Caregiver = Depends(get_current_user),
):
    """Mark a participant excluded, freeing their counterbalancing slot.

    The row is kept -- the record of what happened is part of the data -- but
    it stops counting towards balance, so the next participant fills the gap
    instead of the design staying permanently lopsided.
    """
    assignment = (
        db.query(models.StudyAssignment)
        .filter(models.StudyAssignment.child_id == child_id)
        .first()
    )
    if not assignment:
        raise HTTPException(404, "No assignment for this participant")
    assignment.excluded = True
    assignment.exclusion_reason = request.reason
    db.commit()
    db.refresh(assignment)
    return _serialise(assignment)


@router.post("/sessions")
def start_block_session(
    request: StartBlockRequest,
    db: Session = Depends(get_db),
    current_user: models.Caregiver = Depends(get_current_user),
):
    """Start block 1 or 2 for a participant, stamped with condition and list."""
    if request.block not in (1, 2):
        raise HTTPException(400, "block must be 1 or 2")

    assignment = (
        db.query(models.StudyAssignment)
        .filter(models.StudyAssignment.child_id == request.child_id)
        .first()
    )
    if not assignment:
        raise HTTPException(
            409, "Participant has no counterbalancing assignment; "
                 "POST /study/participants/{child_id}/assignment first")
    if assignment.excluded:
        raise HTTPException(409, "Participant is excluded from the study")

    problems = study_design.validate_lists()
    if problems:
        raise HTTPException(503, "; ".join(problems))

    block = study_design.block_for(assignment.group_index, request.block)
    category_id = study_design.category_id_for_list(block.word_list)

    category = (
        db.query(models.ActivityCategory)
        .filter(models.ActivityCategory.id == category_id)
        .first()
    )
    if not category:
        raise HTTPException(
            503, f"word list {block.word_list} is bound to category "
                 f"{category_id}, which does not exist")

    # Refuse to start the same block twice: a duplicate block would put two
    # sets of attempts on the same items under the same condition, and the
    # item-level models cannot tell them apart afterwards.
    duplicate = (
        db.query(models.TherapySession)
        .filter(
            models.TherapySession.child_id == request.child_id,
            models.TherapySession.category_id == category_id,
            models.TherapySession.condition == block.condition,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            409,
            f"block {request.block} ({block.condition}-{block.word_list}) already "
            f"exists for this participant as session {duplicate.id}")

    session = models.TherapySession(
        child_id=request.child_id,
        caregiver_id=current_user.id,
        category_id=category_id,
        condition=block.condition,
        session_type=study_design.TRAINING,
        block_index=block.index,
        item_order_seed=study_design.new_order_seed(),
        current_level=request.current_level,
        start_time=datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "session_id": str(session.id),
        "child_id": str(request.child_id),
        "session_type": session.session_type,
        "block": block.index,
        "condition": block.condition,
        "word_list": block.word_list,
        "category_id": str(category_id),
        "item_order_seed": session.item_order_seed,
        "gives_feedback": True,
        "group": study_design.describe_group(assignment.group_index),
    }


@router.post("/assessments")
def start_assessment_session(
    request: StartAssessmentRequest,
    db: Session = Depends(get_db),
    current_user: models.Caregiver = Depends(get_current_user),
):
    """Start a pre-test, post-test or delayed post-test.

    An assessment records and scores exactly as a training block does, and says
    nothing about the result. The learning measures come from comparing these
    three, so anything the robot volunteered here would be training, and the
    post-test would then be measuring the test.

    Unlike a training block this carries no condition: it is the same task for
    everyone regardless of which feedback they will receive or have received.
    """
    phase = request.phase.strip().lower()
    if phase not in study_design.ASSESSMENT_PHASES:
        raise HTTPException(
            400, f"phase must be one of {', '.join(study_design.ASSESSMENT_PHASES)}")

    child = db.query(models.Child).filter(models.Child.id == request.child_id).first()
    if not child:
        raise HTTPException(404, "Participant not found")

    # An assessment does not need a counterbalancing group -- it is identical
    # for every group -- but if the participant has been excluded, nothing
    # further should be recorded against them.
    assignment = (
        db.query(models.StudyAssignment)
        .filter(models.StudyAssignment.child_id == request.child_id)
        .first()
    )
    if assignment and assignment.excluded:
        raise HTTPException(409, "Participant is excluded from the study")

    try:
        category_id = study_design.test_category_id()
    except study_design.ListsNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc

    category = (
        db.query(models.ActivityCategory)
        .filter(models.ActivityCategory.id == category_id)
        .first()
    )
    if not category:
        raise HTTPException(
            503, f"STUDY_TEST_CATEGORY_ID points at {category_id}, "
                 f"which does not exist")

    # One assessment per phase. Two pre-tests would give the analysis two
    # baselines for the same participant with no principled way to choose, and
    # the second would already be contaminated by the first.
    duplicate = (
        db.query(models.TherapySession)
        .filter(
            models.TherapySession.child_id == request.child_id,
            models.TherapySession.session_type == phase,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            409, f"{phase} already exists for this participant as session "
                 f"{duplicate.id}")

    session = models.TherapySession(
        child_id=request.child_id,
        caregiver_id=current_user.id,
        category_id=category_id,
        condition=None,
        session_type=phase,
        block_index=None,
        item_order_seed=study_design.new_order_seed(),
        start_time=datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "session_id": str(session.id),
        "child_id": str(request.child_id),
        "session_type": phase,
        "condition": None,
        "category_id": str(category_id),
        "item_order_seed": session.item_order_seed,
        "gives_feedback": False,
    }


@router.get("/sessions/{session_id}/items")
def session_items(session_id: uuid.UUID, db: Session = Depends(get_db)):
    """The items for this session, in the order they should be presented.

    The order is regenerated from the session's stored seed rather than saved,
    so the sequence a participant saw is reproducible from the session row
    alone and cannot drift from what was recorded.

    Presentation order is randomised per session because with fixed lists the
    alternative is that every participant meets the same word last, carrying
    the same fatigue -- a confound identical across participants, which
    therefore does not average out.
    """
    session = (
        db.query(models.TherapySession)
        .filter(models.TherapySession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(404, "Session not found")

    items = (
        db.query(models.ActivityItem)
        .filter(models.ActivityItem.category_id == session.category_id)
        .all()
    )
    by_id = {str(item.id): item for item in items}
    ordered_ids = study_design.order_items(sorted(by_id), session.item_order_seed)

    return {
        "session_id": str(session_id),
        "session_type": session.session_type,
        "condition": session.condition,
        "gives_feedback": not study_design.is_assessment(session.session_type),
        "item_order_seed": session.item_order_seed,
        "items": [
            {
                "id": str(by_id[item_id].id),
                "name": by_id[item_id].name,
                "description": by_id[item_id].description,
                "image_url": by_id[item_id].image_url,
                "audio_url": by_id[item_id].audio_url,
                "difficulty_level": by_id[item_id].difficulty_level,
            }
            for item_id in ordered_ids
        ],
    }


@router.get("/participants/{child_id}/plan")
def participant_plan(child_id: uuid.UUID, db: Session = Depends(get_db)):
    """Everything the app needs to show on the participant's study screen.

    One call rather than four, because the app needs all of it at once and
    deriving any part of it on the device is how a tablet ends up disagreeing
    with the database about which condition someone is in.
    """
    child = db.query(models.Child).filter(models.Child.id == child_id).first()
    if not child:
        raise HTTPException(404, "Participant not found")

    assignment = (
        db.query(models.StudyAssignment)
        .filter(models.StudyAssignment.child_id == child_id)
        .first()
    )
    sessions = (
        db.query(models.TherapySession)
        .filter(models.TherapySession.child_id == child_id)
        .order_by(models.TherapySession.start_time)
        .all()
    )

    def done(**criteria) -> dict | None:
        for s in sessions:
            if all(getattr(s, k) == v for k, v in criteria.items()):
                return {"session_id": str(s.id),
                        "started_at": s.start_time.isoformat() if s.start_time else None,
                        "completed": bool(s.is_completed)}
        return None

    steps: list[dict] = [
        {"step": study_design.PRETEST, "kind": "assessment", "label": "Pre-test",
         "condition": None, "done": done(session_type=study_design.PRETEST)},
    ]
    if assignment:
        for block in study_design.blocks_for(assignment.group_index):
            steps.append({
                "step": f"block{block.index}",
                "kind": "training",
                "label": f"Block {block.index}: {block.condition}-{block.word_list}",
                "block": block.index,
                "condition": block.condition,
                "word_list": block.word_list,
                "done": done(session_type=study_design.TRAINING, block_index=block.index),
            })
    steps += [
        {"step": study_design.POSTTEST, "kind": "assessment", "label": "Post-test",
         "condition": None, "done": done(session_type=study_design.POSTTEST)},
        {"step": study_design.DELAYED, "kind": "assessment", "label": "Delayed post-test",
         "condition": None, "done": done(session_type=study_design.DELAYED)},
    ]

    # Sessions that predate the study plumbing, or were started through the
    # ordinary activities route. Surfaced rather than hidden: they are why
    # every session before 2026-09-17 is unattributable, and a researcher
    # should be able to see one appear immediately.
    unstamped = [str(s.id) for s in sessions if s.session_type is None]

    return {
        "child_id": str(child_id),
        "participant_code": child.participant_code,
        "assignment": _serialise(assignment) if assignment else None,
        "steps": steps,
        "unstamped_sessions": unstamped,
        "list_problems": study_design.validate_lists(),
    }


@router.get("/balance")
def balance(db: Session = Depends(get_db)):
    """Assignment counts per cell, plus the current list binding.

    Worth checking before and during recruitment: an unbalanced design is
    recoverable while participants are still being run, and not afterwards.
    """
    report = study_design.balance_report(_active_counts(db))
    excluded = (
        db.query(models.StudyAssignment)
        .filter(models.StudyAssignment.excluded.is_(True))
        .count()
    )
    return {
        **report,
        "excluded": excluded,
        "word_lists": study_design.configured_lists(),
        "list_problems": study_design.validate_lists(),
    }


@router.get("/design")
def design():
    """The design itself, so the experimenter can check what will be run."""
    return {
        "groups": [
            {"group_index": g, "description": study_design.describe_group(g),
             "blocks": study_design.session_plan(g)}
            for g in range(study_design.N_GROUPS)
        ],
        "word_lists": study_design.configured_lists(),
        "list_problems": study_design.validate_lists(),
    }
