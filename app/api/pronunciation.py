"""Condition-aware pronunciation scoring from raw audio.

One endpoint serves both study conditions. The client records, endpoints
locally, and POSTs the WAV; the backend scores it with the *same* pipeline
regardless of condition, and only the feedback string differs. That is what
makes a K-vs-D difference attributable to feedback content: the two conditions
cannot drift apart in scoring, timing or UI because there is only one of each.

This replaces ``/speech/.../process-transcription`` (which scored the spelling
of a Google ASR transcript) and ``/generic/.../process-transcription`` (which
scored exact string equality). Both remain mounted and untouched until this
path is validated against the rater-adjudicated sample.
"""

from __future__ import annotations

import io
import json
import logging
import math
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..models import ActivityItem, SessionActivity, TherapySession
from ..services import study_design
from ..services import exercises
from ..services.pronunciation import asr, score_attempt, score_sentence
from ..services.pronunciation.audio import assess_quality, to_mono_float32
from ..services.pronunciation.feedback import (assessment_acknowledgement,
                                               generate_feedback)
from ..services.pronunciation.runtime import get_config, get_model, is_ready

log = logging.getLogger(__name__)
router = APIRouter(tags=["pronunciation"])

# Retained with consent, for the rater-adjudicated validation sample and so
# that every published number can be regenerated from the raw audio.
AUDIO_ROOT = Path("study_audio")

MAX_UPLOAD_BYTES = 4 * 1024 * 1024
TARGET_SR = 16_000


def _decode_wav(raw: bytes) -> tuple[np.ndarray, int]:
    """Decode an uploaded WAV into mono float32.

    soundfile only -- no ffmpeg dependency, because the study laptop does not
    have one and a missing codec mid-session is not a failure worth risking.
    The client is specified to send 16 kHz mono PCM WAV.
    """
    import soundfile as sf

    try:
        data, sample_rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"could not decode audio: {exc}") from exc

    waveform = to_mono_float32(data)
    if sample_rate != TARGET_SR:
        try:
            import librosa
            waveform = librosa.resample(waveform, orig_sr=sample_rate,
                                        target_sr=TARGET_SR)
        except ImportError as exc:
            raise HTTPException(
                400,
                f"audio is {sample_rate} Hz; send 16 kHz or install librosa",
            ) from exc
        sample_rate = TARGET_SR
    return waveform, sample_rate


def _parse_instant(value: str | None) -> datetime | None:
    """An ISO-8601 instant from the tablet, or None if it was not sent.

    Never raises. A clock the server cannot parse is worth losing; it is not
    worth failing a participant's attempt over, since the derived response time
    is a secondary measure and the recording is the primary one.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        log.warning("unparseable client timestamp %r; storing null", value)
        return None
    # Stored as naive UTC to match every other timestamp in this schema.
    # Mixing aware and naive values in one column makes ordering silently
    # wrong, and an offset-bearing timestamp from a tablet set to EAT would
    # otherwise sort three hours away from the server's own created_at.
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _finite(value: float) -> float | None:
    """-inf loudness for a silent clip is not valid JSON and not valid SQL."""
    return float(value) if math.isfinite(value) else None


def _json_safe(value):
    """Replace non-finite floats with None, recursively.

    ``PhoneScore.gop`` is ``-inf`` when a phone has no acoustic evidence at all
    -- outside the model's inventory, zero-width span, or below the evidence
    floor. That is meaningful in memory, but ``json.dumps`` renders it as
    ``-Infinity``, which is not valid JSON, and PostgreSQL rejects it:

        DataError: invalid input syntax for type json
        DETAIL: Token "-Infinity" is invalid.

    Every attempt containing such a phone failed to persist and returned 500
    mid-session. Sanitising at the persistence boundary keeps the in-memory
    value honest while writing something the column can hold; ``None`` reads
    correctly in analysis as "no value", which is exactly what -inf meant.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _persist_audio(raw: bytes, session_id: uuid.UUID, item_id: uuid.UUID,
                   attempt: int) -> str | None:
    """Write the recording to disk and return its reference.

    A failure here must not fail the attempt: the participant is mid-session,
    and losing one recording is far better than losing the turn.
    """
    try:
        directory = AUDIO_ROOT / str(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{item_id}_attempt{attempt}.wav"
        path.write_bytes(raw)
        return str(path)
    except OSError:
        log.exception("could not persist audio for session %s", session_id)
        return None


def _quarantine_attempt(session_id, item_id, attempt_number, result,
                        feedback, condition) -> None:
    """Write an unpersistable attempt to disk so no data is lost.

    Alongside the retained audio, so the attempt can be replayed into the
    database once whatever blocked the write is fixed.
    """
    try:
        directory = AUDIO_ROOT / str(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{item_id}_attempt{attempt_number}.quarantine.json"
        payload = {
            "session_id": str(session_id),
            "item_id": str(item_id),
            "attempt_number": attempt_number,
            "condition": condition,
            "word": result.word,
            "verdict": result.verdict,
            "is_correct": result.is_correct,
            "score": result.score,
            "verdict_score": result.verdict_score,
            "confidence": result.confidence,
            "expected_phones": list(result.expected_phones),
            "observed_phones": list(result.observed_phones),
            "phone_scores": [asdict(s) for s in result.phone_scores],
            "diagnoses": [asdict(d) for d in result.diagnoses],
            "reference_source": result.reference_source,
            "transcript": result.transcript,
            "transcript_matches": result.transcript_matches,
            "feedback": feedback.speech,
            "provenance": result.provenance,
            "recorded_at": datetime.utcnow().isoformat(),
        }
        path.write_text(json.dumps(_json_safe(payload), indent=1),
                        encoding="utf-8")
        log.warning("attempt quarantined to %s", path)
    except OSError:
        log.exception("could not quarantine attempt; it is lost")


@router.post("/sessions/{session_id}/attempts")
async def score_pronunciation_attempt(
    session_id: uuid.UUID,
    item_id: uuid.UUID = Form(...),
    response_time_seconds: float = Form(...),
    audio: UploadFile = File(...),
    # The client's on-device recogniser output, when it has one. Used only as
    # a guard against telling a participant they were wrong when they were
    # right; it can never make a verdict worse. Optional so the endpoint keeps
    # working for clients that do not run an ASR.
    transcript: str | None = Form(None),
    # Device-side instants, ISO-8601 from the tablet's clock. The response-time
    # DV is prompt-end to speech-onset, and both of those happen on the tablet;
    # timing them here would fold in upload latency and make the measure a
    # property of the room's wifi. Optional, so an older client still works.
    prompt_ended_at: str | None = Form(None),
    speech_started_at: str | None = Form(None),
    speech_ended_at: str | None = Form(None),
    # How many times the participant asked to hear the prompt again before
    # answering, and whether any of those was the slow replay. An item heard
    # four times is not the same trial as one heard once, and slowing the model
    # changes the stimulus rather than only the pacing.
    prompt_replays: int = Form(0),
    slow_replay_used: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Score one spoken attempt and return the robot's next utterance."""
    if not is_ready():
        raise HTTPException(503, "acoustic model is still loading")

    session = db.query(TherapySession).filter(
        TherapySession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    item = db.query(ActivityItem).filter(ActivityItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "Activity item not found")

    is_assessment = study_design.is_assessment(session.session_type)

    # An unstamped session is one created through the ordinary activities
    # route, with no session type and no condition. The app serves non-study
    # therapy too, so that is allowed in general -- but not for someone who has
    # a counterbalancing assignment. Every session recorded before 2026-09-17
    # was unstamped, which is why not one of them can be attributed to a
    # condition. Refusing at the first attempt is the only point at which a
    # researcher can still fix it; by the end of the session the data exists
    # and is already unusable.
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
                f"this participant is enrolled in the study (group "
                f"{assigned.group_index}). Start the session with "
                f"POST /study/sessions or POST /study/assessments so the "
                f"condition is recorded.",
            )
        log.warning(
            "session %s has no session_type; scoring it as ad-hoc therapy. "
            "Study sessions must be created via /study/sessions.", session_id)

    if is_assessment:
        # Assessments carry no condition, and nothing downstream may invent
        # one: a row labelled K or D that was recorded under neither would be
        # indistinguishable from real data in the analysis.
        condition = None
    else:
        condition = (session.condition or "D").upper()
        if condition not in ("K", "D"):
            raise HTTPException(
                500, f"session {session_id} has invalid condition {session.condition!r}")

    raw = await audio.read()
    if not raw:
        raise HTTPException(400, "empty audio upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "audio upload too large")

    waveform, sample_rate = _decode_wav(raw)

    config = get_config()
    # Judged before scoring, and recorded whatever the verdict. This is about
    # the recording rather than the recognition: a clipped or near-silent clip
    # still produces a confident, entirely wrong verdict, and on 2026-09-15 it
    # did, with nothing in the stored row to say so. Bounds come from the
    # pipeline config so the guard and the scorer agree on what is too short.
    # What the participant was asked to say. Until now this was item.name in
    # every case, and for a read-aloud item item.name is the *target word*:
    # the participant read "He ate a banana for lunch." and the scorer aligned
    # all of it against the six phones of "banana". Every correctly read
    # sentence came back "incorrect", which is the failure last week's
    # recordings show on every sentence item.
    exercise_type = item.effective_type
    spec = item.spec or {}
    sentence = spec.get("sentence") if exercise_type == exercises.READ_SENTENCE else None
    spoken_target = str(spec.get("target_word") or spec.get("word") or item.name)
    max_speech = config.max_sentence_seconds if sentence else config.max_audio_seconds

    quality = assess_quality(waveform, sample_rate,
                             min_speech_s=config.min_audio_seconds,
                             max_speech_s=max_speech)

    prior = db.query(SessionActivity).filter(
        SessionActivity.session_id == session_id,
        SessionActivity.item_id == item_id,
    ).all()
    attempt_number = len(prior) + 1
    # A gated attempt is a request to repeat, not an attempt: it must not eat
    # into the item's retry budget, or two unclear recordings would end the
    # item without the participant ever having been scored.
    scored_before = sum(1 for a in prior if not a.gated)

    # Server-side recognition, invoked only if the acoustics say wrong and the
    # client sent nothing to check that against. See services/asr.py.
    provider = asr.provider_for(config.server_asr)
    if sentence:
        result = score_sentence(
            sentence, spoken_target, waveform, sample_rate, get_model(), config,
            transcript=transcript, transcript_provider=provider,
        )
    else:
        result = score_attempt(
            spoken_target, waveform, sample_rate, get_model(), config,
            transcript=transcript, transcript_provider=provider,
        )

    gated = result.verdict in ("gated", "unscorable")
    # Whether another attempt at this item follows. The client must not decide
    # this independently: the feedback wording depends on it, and two counters
    # drifting apart is how the robot ends up promising a retry it will not give.
    #
    # An assessment never offers one. A second attempt after an implicit "that
    # was not right" is both feedback and practice, which is the thing an
    # assessment exists not to provide.
    retry_available = (
        not is_assessment
        and not result.is_correct
        and not gated
        and (scored_before + 1) < config.max_attempts_per_item
    )

    if is_assessment:
        # Takes no result argument by design: there is no path from the verdict
        # to what gets said, so no later edit can make an assessment leak
        # correctness without changing that function's signature.
        feedback = assessment_acknowledgement(attempt_index=attempt_number - 1)
    else:
        # attempt_number - 1 so the first attempt of an item draws index 0, and
        # K and D draw the same warmth marker at the same point in a session.
        feedback = generate_feedback(result, spoken_target, condition,
                                     attempt_index=attempt_number - 1,
                                     retry_available=retry_available,
                                     sentence=sentence)

    audio_ref = _persist_audio(raw, session_id, item_id, attempt_number)

    activity = SessionActivity(
        session_id=session_id,
        item_id=item_id,
        attempt_number=attempt_number,
        response_time_seconds=response_time_seconds,
        response_type="verbal",
        response_text=" ".join(result.observed_phones) or None,
        is_correct=result.is_correct,
        pronunciation_score=result.score,
        feedback=feedback.speech,
        error_type=result.verdict,
        condition=condition,
        verdict=result.verdict,
        verdict_score=result.verdict_score,
        confidence=result.confidence,
        gated=gated,
        expected_phones=list(result.expected_phones),
        observed_phones=list(result.observed_phones),
        phone_scores=_json_safe([asdict(s) for s in result.phone_scores]),
        diagnoses=_json_safe([asdict(d) for d in result.diagnoses]),
        applied_folds=[list(f) for f in result.applied_folds],
        stress_error=bool(result.stress and result.stress.is_error),
        named_phone=feedback.named_phone,
        feedback_word_count=feedback.word_count,
        reference_source=result.reference_source,
        reference_needs_review=result.reference_needs_review,
        transcript=result.transcript,
        transcript_matches=result.transcript_matches,
        prompt_ended_at=_parse_instant(prompt_ended_at),
        speech_started_at=_parse_instant(speech_started_at),
        speech_ended_at=_parse_instant(speech_ended_at),
        prompt_replays=max(0, prompt_replays),
        slow_replay_used=bool(slow_replay_used),
        skipped=False,
        celebration_shown=(feedback.kind == "praise"),
        # Copied from the item at the time. Last week every sentence attempt
        # was stored as NULL, i.e. repeat_word, and the summary could not tell
        # a read-aloud error from a single-word one.
        exercise_type=exercise_type,
        audio_peak=quality.peak,
        audio_rms_dbfs=_finite(quality.rms_dbfs),
        audio_clipped_fraction=quality.clipped_fraction,
        audio_quality=quality.verdict,
        audio_ref=audio_ref,
        pipeline_version=result.provenance.get("pipeline_version"),
        config_hash=result.provenance.get("config_hash"),
        model_id=result.provenance.get("model_id"),
        stage_timings_ms=_json_safe(result.timings.stages),
        created_at=datetime.utcnow(),
    )

    # A persistence failure must not cost the participant their turn. Log it,
    # keep the payload on disk so the attempt is recoverable, and still return
    # the feedback so the session continues.
    attempt_id: str | None = None
    try:
        db.add(activity)
        db.commit()
        db.refresh(activity)
        attempt_id = str(activity.id)
    except SQLAlchemyError:
        db.rollback()
        log.exception("could not persist attempt for session %s item %s",
                      session_id, item_id)
        _quarantine_attempt(session_id, item_id, attempt_number, result,
                            feedback, condition)

    return {
        "attempt_id": attempt_id,
        "persisted": attempt_id is not None,
        "attempt_number": attempt_number,
        "condition": condition,
        "session_type": session.session_type,
        # False in an assessment. The client does not decide this and must not
        # infer it: it speaks whatever comes back in "feedback", which in an
        # assessment is a fixed acknowledgement with no verdict in it.
        "gives_feedback": not is_assessment,
        "is_correct": result.is_correct,
        "verdict": result.verdict,
        # gated attempts are a request to repeat, not a scored attempt, and
        # are excluded from correction-rate denominators in analysis
        "gated": gated,
        # How usable the recording was, independent of how it scored. The app
        # shows the advice to the researcher, not to the participant: a retake
        # prompted by a bad microphone is a recording decision, not a
        # judgement of how the participant spoke.
        "audio_quality": {
            "verdict": quality.verdict,
            "usable": quality.usable,
            "advice": quality.advice,
            "peak": round(quality.peak, 4),
            "rms_dbfs": _finite(round(quality.rms_dbfs, 1)),
            "clipped_fraction": round(quality.clipped_fraction, 5),
            "duration_s": round(quality.duration_s, 2),
        },
        # Authoritative: the client advances the item when this is false.
        "should_retry": retry_available,
        "score": result.score,
        "verdict_score": result.verdict_score,
        "confidence": result.confidence,
        "feedback": {
            "speech": feedback.speech,
            "display": feedback.display,
            "kind": feedback.kind,
            "remodel": feedback.remodel,
            "word_count": feedback.word_count,
            "named_phone": feedback.named_phone,
        },
        "expected_phones": list(result.expected_phones),
        "observed_phones": list(result.observed_phones),
        "reference_source": result.reference_source,
        "reference_needs_review": result.reference_needs_review,
        "transcript_matches": result.transcript_matches,
        "timings_ms": result.timings.stages,
        "note": result.note,
    }


@router.post("/analyze")
async def analyze_audio(
    word: str = Form(...),
    audio: UploadFile = File(...),
    transcript: str | None = Form(None),
    condition: str = Form("D"),
    db: Session = Depends(get_db),
):
    """Score audio against any word, with no session, item or database row.

    A sandbox for checking the pipeline without a robot: record on a phone,
    post the WAV, see the verdict, the per-phone scores and both conditions'
    feedback. Nothing is persisted, so it cannot contaminate study data.

    This is a development tool. It runs a model inference per request and does
    not authenticate, so it belongs on a trusted network, not a public host.
    """
    if not is_ready():
        raise HTTPException(503, "acoustic model is still loading")

    raw = await audio.read()
    if not raw:
        raise HTTPException(400, "empty audio upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "audio upload too large")

    waveform, sample_rate = _decode_wav(raw)
    config = get_config()
    result = score_attempt(
        word, waveform, sample_rate, get_model(), config,
        transcript=transcript,
        transcript_provider=asr.provider_for(config.server_asr),
    )

    # Both conditions, so the wording of each can be compared side by side.
    feedback = {
        c: {
            "speech": fb.speech,
            "kind": fb.kind,
            "word_count": fb.word_count,
            "named_phone": fb.named_phone,
        }
        for c in ("K", "D")
        for fb in [generate_feedback(result, word, c, attempt_index=0)]
    }

    return {
        "word": result.word,
        "verdict": result.verdict,
        "is_correct": result.is_correct,
        "score": result.score,
        "verdict_score": result.verdict_score,
        "confidence": result.confidence,
        "gated": result.verdict in ("gated", "unscorable"),
        "note": result.note,
        "expected_phones": list(result.expected_phones),
        "observed_phones": list(result.observed_phones),
        "reference_source": result.reference_source,
        "reference_needs_review": result.reference_needs_review,
        "transcript": result.transcript,
        "transcript_matches": result.transcript_matches,
        "phone_scores": _json_safe([
            {
                "phone": p.phone,
                "score": round(p.score, 3),
                "gop": p.gop,
                "competitor": p.competitor,
                "frames": p.end_frame - p.start_frame,
            }
            for p in result.phone_scores
        ]),
        "diagnoses": _json_safe([
            {"expected": d.expected, "observed": d.observed, "kind": d.kind,
             "score": round(d.score, 3)}
            for d in result.diagnoses
        ]),
        "stress_error": bool(result.stress and result.stress.is_error),
        "feedback": feedback,
        "timings_ms": _json_safe(result.timings.stages),
        "audio_seconds": round(len(waveform) / sample_rate, 2),
    }


@router.get("/health")
def pronunciation_health():
    """Whether scoring is available, and under exactly which configuration."""
    config = get_config()
    payload = {"ready": is_ready(), **config.provenance()}
    # Both safety nets, stated explicitly. Either one silently absent is how
    # the 2026-09-15 pilot ran a morning of tests on a degraded scorer.
    payload["server_asr"] = (
        f"faster-whisper {config.server_asr}"
        if asr.is_available(config.server_asr) else "inactive"
    )
    if is_ready():
        info = get_model().describe()
        payload.update(
            n_labels=info.n_labels,
            inventory_size=len(info.inventory),
            phone_level=info.is_phone_level,
        )
    return payload
