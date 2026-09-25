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

import random
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..schemas import exercise_spec
from ..services import exercises, study_design
from ..services.pronunciation.feedback import (assessment_acknowledgement,
                                               perception_feedback)
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

    problems = study_design.validate_lists(db)
    if problems:
        raise HTTPException(503, "; ".join(problems))

    block = study_design.block_for(assignment.group_index, request.block)
    category_id = study_design.category_id_for_list(block.word_list, db)

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
        category_id = study_design.test_category_id(db)
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
            _present(by_id[item_id], session.item_order_seed,
                     teaching=not study_design.is_assessment(session.session_type))
            for item_id in ordered_ids
        ],
    }


def _present(item: models.ActivityItem, seed: int | None,
             teaching: bool = True) -> dict:
    """One item as the tablet should see it.

    The answer key is removed. For a tap-answer item the options go to the
    device and the key does not: grading happens here, so the correct answer is
    never sitting in a payload on a tablet a participant is holding. Option
    order is shuffled from the session's seed as well, so the key's position
    cannot be inferred from a fixed layout and the shuffle is still
    reproducible from the session row.
    """
    exercise_type = item.effective_type
    spec_body = dict(item.spec or {})

    # `name` is derived from the spec, and for a choice item that means it *is*
    # the answer. Sending it would put the key on the tablet through the back
    # door, and the screen would render it as the item's title. The syllable
    # types are safe: their answer is an index, not the word.
    reveals_answer = not exercises.needs_asr(exercise_type) and "answer" in spec_body

    body: dict = {
        "id": str(item.id),
        "name": "" if reveals_answer else item.name,
        "description": item.description,
        "image_url": item.image_url,
        "audio_url": item.audio_url,
        "difficulty_level": item.difficulty_level,
        "exercise_type": exercise_type,
        # Named on screen only where naming it is allowed; see below.
        "target_feature": item.target_feature if teaching else None,
        "target_feature_label": (
            exercises.FEATURES_BY_KEY[item.target_feature].label
            if teaching and item.target_feature in exercises.FEATURES_BY_KEY else None
        ),
        "needs_speech": exercises.needs_asr(exercise_type),
        "presentation": {},
    }

    # Which letters to tint, for the tablet. Offered in training blocks and
    # withheld from assessments: pointing at the vowel that matters is
    # instruction, and an assessment measures what the participant brings to it
    # rather than what the screen just told them.
    if teaching:
        word = spec_body.get("word") or spec_body.get("target_word") or ""
        span = exercises.highlight_span(word, item.target_feature)
        if span:
            body["highlight"] = {"text": word, "start": span[0], "end": span[1]}

    spec_body.pop("answer", None)
    spec_body.pop("answer_index", None)
    spec_body.pop("answer_indices", None)
    if "options" in spec_body:
        options = list(spec_body["options"])
        if seed is not None:
            # Per item, not per session: one shuffle for the whole session
            # would put every key in the same slot, and a participant who
            # noticed would be answering position rather than sound.
            random.Random((seed ^ (hash(str(item.id)) & 0x7FFFFFFF))).shuffle(options)
        spec_body["options"] = options
    body["presentation"] = spec_body
    return body


class AnswerRequest(BaseModel):
    item_id: uuid.UUID
    #: A tapped option, or the syllable indices chosen. Shape follows the
    #: exercise type.
    answer: str | int | list[int] | None = None
    response_time_seconds: float | None = None
    #: Replays before answering. On a perception item this matters more than
    #: anywhere else: the stimulus *is* the question, so how many times it was
    #: heard is part of what the trial measured.
    prompt_replays: int = 0
    slow_replay_used: bool = False


@router.post("/sessions/{session_id}/answers")
def record_answer(
    session_id: uuid.UUID,
    request: AnswerRequest,
    db: Session = Depends(get_db),
    current_user: models.Caregiver = Depends(get_current_user),
):
    """Record a tapped answer, graded here rather than on the tablet.

    The other half of the fork that `/pronunciation/.../attempts` handles. A
    perception item never touches the acoustic model, which is the point: six
    of twenty pilot participants said the robot could not hear Kenyan English,
    and an exercise with no recogniser in it cannot false-reject anyone.

    Grading is server-side because the answer key is deliberately not sent to
    the device. It is also exact, never fuzzy: the participant tapped one of
    the strings this item supplied, so anything else means the client sent
    something that was not offered.
    """
    session = (
        db.query(models.TherapySession)
        .filter(models.TherapySession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(404, "Session not found")

    item = (
        db.query(models.ActivityItem)
        .filter(models.ActivityItem.id == request.item_id)
        .first()
    )
    if not item:
        raise HTTPException(404, "Item not found")
    if item.category_id != session.category_id:
        raise HTTPException(
            400, "That item does not belong to this session's word list")

    exercise_type = item.effective_type
    if exercises.needs_asr(exercise_type):
        raise HTTPException(
            400,
            f"{exercise_type} is answered by speaking. Send the recording to "
            f"/pronunciation/sessions/{session_id}/attempts instead.")

    # Same refusal the scoring endpoint makes: an unstamped session belonging
    # to an enrolled participant produces rows that cannot be attributed to a
    # condition afterwards.
    if session.session_type is None:
        assigned = (
            db.query(models.StudyAssignment)
            .filter(models.StudyAssignment.child_id == session.child_id)
            .first()
        )
        if assigned and not assigned.excluded:
            raise HTTPException(
                409,
                f"session {session_id} was not created as a study session, but "
                f"this participant is enrolled. Start it from the study plan.")

    try:
        correct = exercise_spec.is_correct(exercise_type, item.spec or {}, request.answer)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, f"could not grade this answer: {exc}") from exc

    is_assessment = study_design.is_assessment(session.session_type)
    attempt_number = 1 + (
        db.query(models.SessionActivity)
        .filter(models.SessionActivity.session_id == session_id,
                models.SessionActivity.item_id == request.item_id)
        .count()
    )

    activity = models.SessionActivity(
        session_id=session_id,
        item_id=request.item_id,
        attempt_number=attempt_number,
        is_correct=correct,
        response_type="select",
        exercise_type=exercise_type,
        selected_answer=request.answer,
        response_time_seconds=request.response_time_seconds,
        prompt_replays=max(0, request.prompt_replays),
        slow_replay_used=bool(request.slow_replay_used),
        skipped=False,
        condition=None if is_assessment else session.condition,
        verdict="correct" if correct else "incorrect",
        created_at=datetime.utcnow(),
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)

    condition = None if is_assessment else session.condition
    reveal = None if (is_assessment or correct) else _reveal(exercise_type, item.spec or {})
    if is_assessment:
        feedback = assessment_acknowledgement(attempt_index=attempt_number - 1)
    else:
        feedback = perception_feedback(correct, attempt_index=attempt_number - 1,
                                       condition=condition,
                                       reveal=reveal["speech"] if reveal else None)

    return {
        "attempt_id": str(activity.id),
        "attempt_number": attempt_number,
        "session_type": session.session_type,
        "exercise_type": exercise_type,
        # Tapped items carry the condition now. In D a wrong tap is followed by
        # the answer, in K it is not, so the manipulation touches these rows.
        "condition": condition,
        "gives_feedback": not is_assessment,
        "is_correct": correct,
        "feedback": {
            "speech": feedback.speech,
            "display": feedback.display,
            "kind": feedback.kind,
        },
        # Only in D, only after a wrong answer: what to highlight on the
        # tablet. The key never travels otherwise.
        "reveal": reveal if condition == "D" else None,
    }


_ORDINAL_WORDS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth")


def _reveal(exercise_type: str, spec: dict) -> dict | None:
    """The correct answer, in the shape the tablet highlights and the words
    the robot says. Diagnostic feedback for a tap item is exactly this: not a
    phone to fix, but which one was right."""
    if exercise_type == exercises.STRESS_PLACE:
        syllables = list(spec.get("syllables", []))
        index = spec.get("answer_index")
        if index is None or index >= len(syllables):
            return None
        return {"index": index,
                "speech": f"The strongest syllable is {syllables[index]}, "
                          f"the {_ORDINAL_WORDS[index]} one."}
    if exercise_type == exercises.SCHWA_SPOT:
        syllables = list(spec.get("syllables", []))
        indices = sorted(spec.get("answer_indices", []))
        if not indices or any(i >= len(syllables) for i in indices):
            return None
        names = [syllables[i] for i in indices]
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        plural = "syllable is" if len(names) == 1 else "syllables are"
        return {"indices": indices, "speech": f"The weak {plural} {joined}."}
    answer = spec.get("answer")
    if not answer:
        return None
    if exercise_type == exercises.MINIMAL_PAIR_ID:
        speech = f"The word you heard was {answer}."
    elif exercise_type == exercises.SAME_SOUND_MATCH:
        speech = f"The one with the same sound is {answer}."
    else:
        speech = f"The answer is {answer}."
    return {"option": answer, "speech": speech}


class SkipRequest(BaseModel):
    item_id: uuid.UUID
    #: cant_say | cant_hear | other. Why, not whether: "could not hear the
    #: model" and "would rather not attempt this word" mean different things
    #: for the item and only one of them is about the participant.
    reason: str = "other"
    prompt_replays: int = 0
    slow_replay_used: bool = False


@router.post("/sessions/{session_id}/skip")
def skip_item(
    session_id: uuid.UUID,
    request: SkipRequest,
    db: Session = Depends(get_db),
    current_user: models.Caregiver = Depends(get_current_user),
):
    """The participant declined this item.

    Recorded, and recorded as a skip rather than an error. A person who could
    not produce a word and a person who produced it wrongly are different
    observations, and storing the first as the second is the false rejection
    this system exists to avoid, arriving by another route.

    It exists because a stuck item otherwise ends the session. That was a real
    failure in the pilot: an item the recogniser would not accept had no way
    out except abandoning everything after it.
    """
    session = (
        db.query(models.TherapySession)
        .filter(models.TherapySession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(404, "Session not found")
    item = (
        db.query(models.ActivityItem)
        .filter(models.ActivityItem.id == request.item_id)
        .first()
    )
    if not item:
        raise HTTPException(404, "Item not found")

    reason = request.reason if request.reason in SKIP_REASONS else "other"
    attempt_number = 1 + (
        db.query(models.SessionActivity)
        .filter(models.SessionActivity.session_id == session_id,
                models.SessionActivity.item_id == request.item_id)
        .count()
    )
    activity = models.SessionActivity(
        session_id=session_id,
        item_id=request.item_id,
        attempt_number=attempt_number,
        is_correct=None,
        exercise_type=item.effective_type,
        skipped=True,
        skip_reason=reason,
        verdict="skipped",
        prompt_replays=request.prompt_replays,
        slow_replay_used=request.slow_replay_used,
        condition=None if study_design.is_assessment(session.session_type) else session.condition,
        created_at=datetime.utcnow(),
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return {
        "attempt_id": str(activity.id),
        "item_id": str(request.item_id),
        "skipped": True,
        "reason": reason,
        # Nothing to say about it. Under either condition and in an assessment,
        # a skip is acknowledged and the session moves on.
        "feedback": {"speech": "That's alright. Here is the next one.",
                     "display": "Skipped", "kind": "assessment"},
    }


SKIP_REASONS = ("cant_say", "cant_hear", "other")


class CompleteRequest(BaseModel):
    ended_early: bool = False


@router.post("/sessions/{session_id}/complete")
def complete_session(
    session_id: uuid.UUID,
    request: CompleteRequest,
    db: Session = Depends(get_db),
    current_user: models.Caregiver = Depends(get_current_user),
):
    """Mark a session finished and stamp its end time.

    `end_time` was only ever set by the ad-hoc `/activities/next-item` route. A
    study session walks a fixed list on the device and never calls it, so every
    study session had `end_time` NULL and every summary reported a duration of
    zero minutes.

    `ended_early` is kept separately because a session with fifteen of
    twenty-one items is not a short session, it is an incomplete one, and
    averaging the two would understate how long the protocol takes.
    """
    session = (
        db.query(models.TherapySession)
        .filter(models.TherapySession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(404, "Session not found")

    if session.end_time is None:
        session.end_time = datetime.utcnow()
    session.is_completed = True
    session.ended_early = bool(request.ended_early)
    db.commit()
    db.refresh(session)
    return {
        "session_id": str(session.id),
        "is_completed": True,
        "ended_early": bool(session.ended_early),
        "end_time": session.end_time.isoformat(),
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
        "list_problems": study_design.validate_lists(db),
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
        "word_lists": study_design.configured_lists(db),
        "list_problems": study_design.validate_lists(db),
    }


@router.get("/dashboard")
def dashboard(target: int | None = None, db: Session = Depends(get_db)):
    """One pass over the tables the console's dashboard reads. See
    services/dashboard.py for what each number means and why."""
    from ..services import dashboard as dash
    return dash.build(db, recruitment_target=target)


@router.get("/design")
def design(db: Session = Depends(get_db)):
    """The design itself, so the experimenter can check what will be run."""
    return {
        "groups": [
            {"group_index": g, "description": study_design.describe_group(g),
             "blocks": study_design.session_plan(g)}
            for g in range(study_design.N_GROUPS)
        ],
        "word_lists": study_design.configured_lists(db),
        "list_problems": study_design.validate_lists(db),
    }
