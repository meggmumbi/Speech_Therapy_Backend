"""Listening and judging: the pilot labels, and the study's human ratings.

One screen, three tasks. `pilot_label` is one person, binary, over the 78
pilot recordings, and it exists to refit the verdict threshold on labels the
pipeline did not influence. `study_rating` is several raters, a richer scale,
over a stratified sample of the study's recordings, and it is where the
false-correction rate and the inter-rater statistics come from. `review` is
the researcher alone, over the attempts the pipeline was least sure about:
the ones the ASR transcript rescued, the ones it called close, and the ones
it rejected although the transcript contained the target. Its report
(`/audit`) counts the two failures that matter, false rejections and false
acceptances, so a threshold is moved on evidence rather than on one clip.

BLIND BY CONSTRUCTION

The queue sends the target and the clip and nothing else. No verdict, no
score, no transcript, no condition, no participant, no session. The old
labelling CSV put all of those in the columns beside the label, so a label
made from it was made after reading the pipeline's opinion -- which is the
one thing a label used to tune the pipeline must not be.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import random
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import agreement, exercises, study_design
from ..utils.auth import get_current_user, require_researcher

router = APIRouter(tags=["ratings"])

PILOT = "pilot_label"
STUDY = "study_rating"
REVIEW = "review"
TASKS = (PILOT, STUDY, REVIEW)
PILOT_CSV = Path("benchmarks/pilot_to_label.csv")


# --- the sample -------------------------------------------------------------

class SampleRequest(BaseModel):
    task: str
    #: study_rating: clips per stratum (session type x condition x feature).
    per_stratum: int = Field(default=4, ge=1, le=50)
    #: Share of the set entered a second time for within-rater consistency.
    repeat_fraction: float = Field(default=0.1, ge=0.0, le=0.5)
    seed: int = 2026


def _task(value: str, user: models.Caregiver | None = None) -> str:
    if value not in TASKS:
        raise HTTPException(400, f"task must be one of {', '.join(TASKS)}")
    # The review set is chosen by the pipeline's own uncertainty, and its
    # report puts verdicts beside labels. It is the researcher's tool, not a
    # rater's: an external rater must never be handed a set defined by what
    # the model thought.
    if value == REVIEW and user is not None and (user.role or "researcher") == "rater":
        raise HTTPException(403, "the review task is for researchers")
    return value


@router.post("/sample", dependencies=[Depends(require_researcher)])
def build_sample(request: SampleRequest, db: Session = Depends(get_db)):
    """Choose what will be rated, once, for everyone.

    Refused if anyone has already rated this task: replacing the set under
    existing ratings would leave two raters having judged different samples,
    and no agreement statistic survives that.
    """
    task = _task(request.task)
    # The review set may be rebuilt at any time: it is one person's audit,
    # not an agreement study, and a judgement already made keeps its attempt
    # id whether or not that attempt is still in the queue.
    if task != REVIEW and db.query(models.Rating).filter(models.Rating.task == task).first():
        raise HTTPException(409, f"{task} already has ratings; the set cannot be rebuilt under them")

    rng = random.Random(request.seed)
    chosen: list[tuple[uuid.UUID, str]] = []

    if task == PILOT:
        if not PILOT_CSV.exists():
            raise HTTPException(404, f"{PILOT_CSV} not found")
        with PILOT_CSV.open(encoding="utf-8") as fh:
            paths = [row["audio"] for row in csv.DictReader(fh)]
        rows = (db.query(models.SessionActivity)
                .filter(models.SessionActivity.audio_ref.in_(paths)).all())
        by_path = {a.audio_ref: a for a in rows}
        missing = [p for p in paths if p not in by_path]
        for p in paths:
            if p in by_path:
                chosen.append((by_path[p].id, "pilot"))
        note = f"{len(missing)} CSV rows have no stored attempt" if missing else None
    elif task == REVIEW:
        candidates = _review_candidates(db)
        reasons: dict[str, int] = defaultdict(int)
        for a, reason in candidates:
            chosen.append((a.id, reason))
            reasons[reason] += 1
        note = ", ".join(f"{n} {r}" for r, n in sorted(reasons.items())) or None
    else:
        candidates = _study_candidates(db)
        by_stratum: dict[str, list[models.SessionActivity]] = defaultdict(list)
        for a, stratum in candidates:
            by_stratum[stratum].append(a)
        for stratum in sorted(by_stratum):
            pool = by_stratum[stratum]
            rng.shuffle(pool)
            chosen.extend((a.id, stratum) for a in pool[:request.per_stratum])
        note = f"{len(by_stratum)} strata from {len(candidates)} eligible recordings"

    if not chosen:
        raise HTTPException(409, "nothing eligible to rate")

    db.query(models.RatingSet).filter(models.RatingSet.task == task).delete()
    for attempt_id, stratum in chosen:
        db.add(models.RatingSet(id=uuid.uuid4(), task=task, attempt_id=attempt_id,
                                stratum=stratum, repeat_index=0))
    repeats = rng.sample(chosen, k=int(round(len(chosen) * request.repeat_fraction)))
    for attempt_id, stratum in repeats:
        db.add(models.RatingSet(id=uuid.uuid4(), task=task, attempt_id=attempt_id,
                                stratum=stratum, repeat_index=1))
    db.commit()
    return {"task": task, "clips": len(chosen), "repeats": len(repeats), "note": note}


def _study_candidates(db: Session) -> list[tuple[models.SessionActivity, str]]:
    """Spoken attempts from stamped sessions, with a usable recording, from
    participants who consented to their audio being kept."""
    rows = (db.query(models.SessionActivity, models.TherapySession, models.ActivityItem, models.Child)
            .join(models.TherapySession, models.SessionActivity.session_id == models.TherapySession.id)
            .join(models.ActivityItem, models.SessionActivity.item_id == models.ActivityItem.id)
            .join(models.Child, models.TherapySession.child_id == models.Child.id)
            .filter(models.TherapySession.session_type.isnot(None),
                    models.SessionActivity.audio_ref.isnot(None),
                    models.Child.consent_audio_retention.is_(True))
            .all())
    out = []
    for a, s, item, _child in rows:
        if a.skipped or a.gated:
            continue
        if not exercises.needs_asr(a.exercise_type or item.effective_type):
            continue
        if a.audio_quality and a.audio_quality != "ok":
            continue
        if not os.path.exists(a.audio_ref):
            continue
        stratum = f"{s.session_type}/{s.condition or '-'}/{item.target_feature or 'none'}"
        out.append((a, stratum))
    return out


def _review_candidates(db: Session) -> list[tuple[models.SessionActivity, str]]:
    """The attempts whose verdict rested on the least evidence, each tagged
    with why it is here. Everything spoken and stored, the researcher's own
    test sessions included, because those are where the model is exercised
    between participants.

    rescued: the acoustics said wrong, the transcript said the target was
        heard, and the rescue rule made it correct. This is the only path to
        a false acceptance the scorer has, so every one of them is listed.
    heard_but_rejected: the transcript contained the target and the verdict
        was still incorrect or close. Either the transcript was generous or
        the verdict was a false rejection, and only an ear can say which.
    close: the verdict itself says the evidence was marginal.
    borderline: correct on the acoustics alone but within 0.05 of the line.
    """
    from ..services.pronunciation.runtime import get_config
    from ..services.pronunciation.scoring import normalize_text, transcript_matches_target
    t = get_config().thresholds
    rows = (db.query(models.SessionActivity, models.ActivityItem)
            .join(models.ActivityItem, models.SessionActivity.item_id == models.ActivityItem.id)
            .filter(models.SessionActivity.audio_ref.isnot(None),
                    models.SessionActivity.verdict.isnot(None))
            .all())
    out = []
    for a, item in rows:
        if a.skipped or a.gated or a.verdict in ("gated", "unscorable"):
            continue
        if not exercises.needs_asr(a.exercise_type or item.effective_type):
            continue
        if not os.path.exists(a.audio_ref):
            continue
        spec = item.spec or {}
        target = str(spec.get("target_word") or spec.get("word") or item.name)
        score = a.verdict_score if a.verdict_score is not None else 0.0
        heard = bool(a.transcript_matches) or bool(transcript_matches_target(a.transcript, normalize_text(target), None))
        if a.verdict == "correct" and heard and score < t.correct:
            reason = "rescued"
        elif a.verdict in ("incorrect", "close", "stress_error") and heard:
            reason = "heard_but_rejected"
        elif a.verdict == "close":
            reason = "close"
        elif a.verdict == "correct" and score < t.correct + 0.05:
            reason = "borderline"
        else:
            continue
        out.append((a, reason))
    return out


# --- the queue --------------------------------------------------------------

def _rater_order(rater_id: uuid.UUID, task: str, key: str) -> int:
    """A stable per-rater shuffle: the same rater always sees the same order,
    two raters see different orders, and neither is presentation order."""
    digest = hashlib.sha256(f"{rater_id}:{task}:{key}".encode()).hexdigest()
    return int(digest[:12], 16)


@router.get("/queue")
def queue(task: str, limit: int = 20, db: Session = Depends(get_db),
          user: models.Caregiver = Depends(get_current_user)):
    """The next clips for this rater, blind.

    What is sent: the target text, the exercise type, the list of features a
    rater may name as wrong, and where to fetch the audio. What is not sent
    is the point of the endpoint.
    """
    task = _task(task, user)
    done = {(r.attempt_id, r.repeat_index) for r in
            db.query(models.Rating).filter(models.Rating.task == task,
                                           models.Rating.rater_id == user.id)}
    entries = (db.query(models.RatingSet, models.SessionActivity, models.ActivityItem)
               .join(models.SessionActivity, models.RatingSet.attempt_id == models.SessionActivity.id)
               .join(models.ActivityItem, models.SessionActivity.item_id == models.ActivityItem.id)
               .filter(models.RatingSet.task == task).all())
    total = len(entries)
    pending = [(e, a, item) for e, a, item in entries if (e.attempt_id, e.repeat_index) not in done]
    # Repeats are pushed towards the end of the order so a repeat is never
    # heard right after its original.
    pending.sort(key=lambda t: (t[0].repeat_index, _rater_order(user.id, task, f"{t[0].attempt_id}:{t[0].repeat_index}")))

    def target_of(item: models.ActivityItem) -> dict:
        spec = item.spec or {}
        return {
            "exercise_type": item.effective_type,
            "word": spec.get("target_word") or spec.get("word") or item.name,
            "sentence": spec.get("sentence"),
            "target_feature": item.target_feature,
        }

    return {
        "task": task,
        "total": total,
        "remaining": len(pending),
        "features": [{"key": f.key, "label": f.label} for f in exercises.FEATURES],
        "clips": [
            {
                "attempt_id": str(a.id),
                "repeat_index": e.repeat_index,
                "audio_url": f"ratings/clips/{a.id}/audio",
                **target_of(item),
            }
            for e, a, item in pending[:limit]
        ],
    }


@router.get("/progress")
def progress(task: str, db: Session = Depends(get_db),
             user: models.Caregiver = Depends(get_current_user)):
    task = _task(task, user)
    total = db.query(models.RatingSet).filter(models.RatingSet.task == task).count()
    mine = db.query(models.Rating).filter(models.Rating.task == task,
                                          models.Rating.rater_id == user.id).count()
    return {"task": task, "total": total, "rated": mine}


# --- a rating ---------------------------------------------------------------

class RatingSubmission(BaseModel):
    task: str
    attempt_id: uuid.UUID
    repeat_index: int = 0
    correct: bool | None = None
    accuracy: int | None = Field(default=None, ge=1, le=5)
    wrong_feature: str | None = None
    unusable: bool = False
    duration_ms: int | None = None


@router.post("/")
def submit(body: RatingSubmission, db: Session = Depends(get_db),
           user: models.Caregiver = Depends(get_current_user)):
    task = _task(body.task, user)
    in_set = (db.query(models.RatingSet)
              .filter(models.RatingSet.task == task,
                      models.RatingSet.attempt_id == body.attempt_id,
                      models.RatingSet.repeat_index == body.repeat_index).first())
    if not in_set:
        raise HTTPException(404, "that clip is not in this task's rating set")
    if not body.unusable and body.correct is None:
        raise HTTPException(422, "say whether it was correct, or mark the recording unusable")
    if task == STUDY and not body.unusable and body.accuracy is None:
        raise HTTPException(422, "a study rating needs the 1-5 accuracy as well")
    if body.wrong_feature and body.wrong_feature not in exercises.TARGET_FEATURES and body.wrong_feature != "other":
        raise HTTPException(422, f"{body.wrong_feature!r} is not a known feature")

    row = (db.query(models.Rating)
           .filter(models.Rating.task == task, models.Rating.attempt_id == body.attempt_id,
                   models.Rating.rater_id == user.id, models.Rating.repeat_index == body.repeat_index)
           .first())
    if row is None:
        row = models.Rating(id=uuid.uuid4(), task=task, attempt_id=body.attempt_id,
                            rater_id=user.id, repeat_index=body.repeat_index,
                            created_at=datetime.utcnow())
        db.add(row)
    row.correct = None if body.unusable else body.correct
    row.accuracy = None if body.unusable else body.accuracy
    row.wrong_feature = None if (body.unusable or body.correct) else body.wrong_feature
    row.unusable = body.unusable
    row.duration_ms = body.duration_ms
    db.commit()
    return {"rating_id": str(row.id), "recorded": True}


# --- the audio --------------------------------------------------------------

@router.get("/clips/{attempt_id}/audio")
def clip_audio(attempt_id: uuid.UUID, db: Session = Depends(get_db),
               user: models.Caregiver = Depends(get_current_user)):
    """A participant's recording. Signed in, and only what the sample holds.

    Participant audio is sensitive in a way stimulus audio is not. A rater
    can fetch a clip only if it is in a rating set, and a clip from a
    participant who did not consent to retention is never served to a rater;
    the pilot recordings predate that flag and are served to researchers only.
    """
    attempt = db.query(models.SessionActivity).filter(models.SessionActivity.id == attempt_id).first()
    if not attempt or not attempt.audio_ref:
        raise HTTPException(404, "No recording")
    in_set = db.query(models.RatingSet).filter(models.RatingSet.attempt_id == attempt_id).first()
    is_researcher = (user.role or "researcher") != "rater"
    if not in_set and not is_researcher:
        raise HTTPException(403, "not in a rating set")
    session = db.query(models.TherapySession).filter(models.TherapySession.id == attempt.session_id).first()
    child = db.query(models.Child).filter(models.Child.id == session.child_id).first() if session else None
    consented = bool(child and child.consent_audio_retention)
    if not consented and not is_researcher:
        raise HTTPException(403, "this participant did not consent to audio retention")
    if not os.path.exists(attempt.audio_ref):
        raise HTTPException(404, "recording file is missing")
    return FileResponse(attempt.audio_ref, media_type="audio/wav")


# --- agreement and export ---------------------------------------------------

@router.get("/agreement", dependencies=[Depends(require_researcher)])
def agreement_report(task: str, db: Session = Depends(get_db)):
    task = _task(task)
    ratings = db.query(models.Rating).filter(models.Rating.task == task).all()
    raters = {r.rater_id for r in ratings}
    names = {c.id: c.username for c in db.query(models.Caregiver).filter(models.Caregiver.id.in_(raters))} if raters else {}
    by_clip: dict[uuid.UUID, dict[uuid.UUID, models.Rating]] = defaultdict(dict)
    repeats: dict[tuple[uuid.UUID, uuid.UUID], dict[int, models.Rating]] = defaultdict(dict)
    for r in ratings:
        if r.unusable:
            continue
        if r.repeat_index == 0:
            by_clip[r.attempt_id][r.rater_id] = r
        repeats[(r.attempt_id, r.rater_id)][r.repeat_index] = r

    rater_list = sorted(raters, key=lambda x: names.get(x, ""))
    full = [c for c, rs in by_clip.items() if set(rs) == set(rater_list)] if len(rater_list) >= 2 else []
    fleiss = agreement.fleiss_kappa([[by_clip[c][r].correct for r in rater_list] for c in full]) if full else None

    pairs = []
    for i, a in enumerate(rater_list):
        for b in rater_list[i + 1:]:
            shared = [c for c, rs in by_clip.items() if a in rs and b in rs]
            xa = [by_clip[c][a].correct for c in shared]
            xb = [by_clip[c][b].correct for c in shared]
            pairs.append({
                "raters": [names.get(a), names.get(b)], "clips": len(shared),
                "percent_agreement": agreement.percent_agreement(xa, xb),
                "kappa": agreement.cohen_kappa(xa, xb),
                "kappa_band": agreement.describe_kappa(agreement.cohen_kappa(xa, xb)),
                "accuracy_mean_abs_diff": agreement.mean_absolute_difference(
                    [by_clip[c][a].accuracy for c in shared], [by_clip[c][b].accuracy for c in shared]),
            })

    within = []
    for rater in rater_list:
        firsts, seconds = [], []
        for (attempt_id, rid), idx in repeats.items():
            if rid == rater and 0 in idx and 1 in idx:
                firsts.append(idx[0].correct); seconds.append(idx[1].correct)
        within.append({"rater": names.get(rater), "repeats": len(firsts),
                       "percent_agreement": agreement.percent_agreement(firsts, seconds)})

    disagreements = []
    items = {i.id: i for i in db.query(models.ActivityItem).all()}
    attempts = {a.id: a for a in db.query(models.SessionActivity).filter(
        models.SessionActivity.id.in_(list(by_clip))).all()} if by_clip else {}
    for c, rs in by_clip.items():
        votes = {r.correct for r in rs.values()}
        if len(rs) >= 2 and len(votes) > 1:
            a = attempts.get(c)
            item = items.get(a.item_id) if a else None
            disagreements.append({
                "attempt_id": str(c), "target": item.name if item else "?",
                "votes": {names.get(rid): r.correct for rid, r in rs.items()},
                "pipeline_said": a.verdict if a else None,
            })

    return {
        "task": task, "raters": [names.get(r) for r in rater_list],
        "clips_rated": len(by_clip), "clips_by_everyone": len(full),
        "fleiss_kappa": fleiss, "fleiss_band": agreement.describe_kappa(fleiss),
        "pairs": pairs, "within_rater": within, "disagreements": disagreements,
        "unusable": sum(1 for r in ratings if r.unusable),
    }


@router.get("/audit", dependencies=[Depends(require_researcher)])
def audit(task: str, db: Session = Depends(get_db)):
    """The pipeline against the people, on whichever task has been rated.

    One row per rated attempt: what the majority of raters said, what the
    pipeline wrote at the time, and why the clip was in the set. The totals
    are the two failure rates. A verdict is shown here only after a label
    exists for it, so the label was made blind.
    """
    task = _task(task)
    ratings = db.query(models.Rating).filter(models.Rating.task == task).all()
    votes: dict[uuid.UUID, list[bool]] = defaultdict(list)
    for r in ratings:
        if r.repeat_index == 0 and not r.unusable and r.correct is not None:
            votes[r.attempt_id].append(r.correct)
    if not votes:
        return {"task": task, "totals": agreement.confusion([], []), "by_reason": {}, "rows": []}
    reason_of = {e.attempt_id: e.stratum for e in
                 db.query(models.RatingSet).filter(models.RatingSet.task == task, models.RatingSet.repeat_index == 0)}
    attempts = (db.query(models.SessionActivity, models.ActivityItem)
                .join(models.ActivityItem, models.SessionActivity.item_id == models.ActivityItem.id)
                .filter(models.SessionActivity.id.in_(list(votes))).all())
    rows, humans, pipes = [], [], []
    by_reason: dict[str, tuple[list, list]] = defaultdict(lambda: ([], []))
    for a, item in sorted(attempts, key=lambda t: t[0].created_at or datetime.min):
        v = votes[a.id]
        human = sum(v) * 2 >= len(v)
        pipeline = None if a.verdict in (None, "gated", "unscorable") else a.verdict == "correct"
        reason = reason_of.get(a.id, "-")
        humans.append(human); pipes.append(pipeline)
        by_reason[reason][0].append(human); by_reason[reason][1].append(pipeline)
        spec = item.spec or {}
        rows.append({
            "attempt_id": str(a.id), "target": str(spec.get("target_word") or spec.get("word") or item.name),
            "sentence": spec.get("sentence"), "exercise_type": a.exercise_type or item.effective_type,
            "target_feature": item.target_feature, "reason": reason,
            "human_correct": human, "votes": len(v),
            "pipeline_verdict": a.verdict, "pipeline_score": a.verdict_score, "transcript": a.transcript,
            "disagree": pipeline is not None and human != pipeline,
            "recorded_at": a.created_at.isoformat() if a.created_at else None,
        })
    return {
        "task": task,
        "totals": agreement.confusion(humans, pipes),
        "by_reason": {r: agreement.confusion(h, p) for r, (h, p) in sorted(by_reason.items())},
        "rows": rows,
    }


@router.get("/export", dependencies=[Depends(require_researcher)])
def export(task: str, db: Session = Depends(get_db)):
    """pilot_label: write human_label back into the CSV the refit script
    reads. study_rating: one row per rating, for the mixed model."""
    task = _task(task)
    ratings = db.query(models.Rating).filter(models.Rating.task == task).all()
    if task == PILOT:
        # The researcher's own label; where several people labelled, majority.
        votes: dict[uuid.UUID, list[bool]] = defaultdict(list)
        for r in ratings:
            if r.repeat_index == 0 and not r.unusable and r.correct is not None:
                votes[r.attempt_id].append(r.correct)
        attempts = {a.audio_ref: a for a in db.query(models.SessionActivity).filter(
            models.SessionActivity.id.in_(list(votes))).all()} if votes else {}
        with PILOT_CSV.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            rows = list(reader)
        written = 0
        for row in rows:
            a = attempts.get(row["audio"])
            if a and votes.get(a.id):
                v = votes[a.id]
                row["human_label"] = "1" if sum(v) * 2 >= len(v) else "0"
                written += 1
        with PILOT_CSV.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)
        return {"task": task, "labelled": written, "rows": len(rows), "path": str(PILOT_CSV),
                "next": "python scripts/refit_on_labels.py"}

    names = {c.id: c.username for c in db.query(models.Caregiver).all()}
    attempts = {a.id: a for a in db.query(models.SessionActivity).all()}
    sessions = {s.id: s for s in db.query(models.TherapySession).all()}
    items = {i.id: i for i in db.query(models.ActivityItem).all()}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rating_id", "attempt_id", "rater", "repeat", "session_type", "condition", "block",
                "participant_id", "item", "exercise_type", "target_feature", "correct", "accuracy",
                "wrong_feature", "unusable", "duration_ms", "pipeline_verdict", "pipeline_score"])
    for r in ratings:
        a = attempts.get(r.attempt_id); s = sessions.get(a.session_id) if a else None
        item = items.get(a.item_id) if a else None
        w.writerow([r.id, r.attempt_id, names.get(r.rater_id), r.repeat_index,
                    s.session_type if s else None, s.condition if s else None, s.block_index if s else None,
                    s.child_id if s else None, item.name if item else None,
                    a.exercise_type if a else None, item.target_feature if item else None,
                    r.correct, r.accuracy, r.wrong_feature, r.unusable, r.duration_ms,
                    a.verdict if a else None, a.verdict_score if a else None])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="study_ratings.csv"'})


# --- rater accounts ---------------------------------------------------------

class RaterCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6)


@router.post("/raters", dependencies=[Depends(require_researcher)])
def create_rater(body: RaterCreate, db: Session = Depends(get_db)):
    """An account that can rate and nothing else: no participants, no
    dashboard, no stimuli. Raters are external people and must see none of
    the study apart from the clips they are judging."""
    from ..utils.auth import get_password_hash
    name = body.username.strip().lower()
    if db.query(models.Caregiver).filter(models.Caregiver.username == name).first():
        raise HTTPException(409, f"an account named {name!r} already exists")
    rater = models.Caregiver(id=uuid.uuid4(), username=name, email=f"{name}@raters.local",
                             hashed_password=get_password_hash(body.password), role="rater")
    db.add(rater)
    db.commit()
    return {"username": name, "role": "rater"}


@router.get("/raters", dependencies=[Depends(require_researcher)])
def list_raters(db: Session = Depends(get_db)):
    raters = db.query(models.Caregiver).filter(models.Caregiver.role == "rater").all()
    counts = defaultdict(int)
    for r in db.query(models.Rating).all():
        counts[(r.rater_id, r.task)] += 1
    return [{"username": r.username, "pilot_label": counts[(r.id, PILOT)], "study_rating": counts[(r.id, STUDY)],
             "review": counts[(r.id, REVIEW)]}
            for r in raters]
