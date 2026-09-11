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
import logging
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ActivityItem, SessionActivity, TherapySession
from ..services.pronunciation import score_attempt
from ..services.pronunciation.audio import to_mono_float32
from ..services.pronunciation.feedback import generate_feedback
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

    # A study session is stamped with its condition by /study/sessions. A
    # session created through the ordinary activities route has none: the app
    # also serves non-study therapy, so this defaults rather than refusing --
    # but it says so, and therapy_sessions.condition stays NULL, which is how
    # analysis can exclude anything that was never properly assigned.
    condition_source = "session" if session.condition else "default"
    if condition_source == "default":
        log.warning(
            "session %s has no condition; scoring as D. Study sessions must be "
            "created via POST /study/sessions.", session_id)
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

    prior = db.query(SessionActivity).filter(
        SessionActivity.session_id == session_id,
        SessionActivity.item_id == item_id,
    ).all()
    attempt_number = len(prior) + 1
    # A gated attempt is a request to repeat, not an attempt: it must not eat
    # into the item's retry budget, or two unclear recordings would end the
    # item without the participant ever having been scored.
    scored_before = sum(1 for a in prior if not a.gated)

    config = get_config()
    result = score_attempt(str(item.name), waveform, sample_rate,
                           get_model(), config, transcript=transcript)

    gated = result.verdict in ("gated", "unscorable")
    # Whether another attempt at this item follows. The client must not decide
    # this independently: the feedback wording depends on it, and two counters
    # drifting apart is how the robot ends up promising a retry it will not give.
    retry_available = (
        not result.is_correct
        and not gated
        and (scored_before + 1) < config.max_attempts_per_item
    )

    # attempt_number - 1 so the first attempt of an item draws index 0, and K
    # and D draw the same warmth marker at the same point in a session.
    feedback = generate_feedback(result, str(item.name), condition,
                                 attempt_index=attempt_number - 1,
                                 retry_available=retry_available)

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
        phone_scores=[asdict(s) for s in result.phone_scores],
        diagnoses=[asdict(d) for d in result.diagnoses],
        applied_folds=[list(f) for f in result.applied_folds],
        stress_error=bool(result.stress and result.stress.is_error),
        named_phone=feedback.named_phone,
        feedback_word_count=feedback.word_count,
        reference_source=result.reference_source,
        reference_needs_review=result.reference_needs_review,
        transcript=result.transcript,
        transcript_matches=result.transcript_matches,
        audio_ref=audio_ref,
        pipeline_version=result.provenance.get("pipeline_version"),
        config_hash=result.provenance.get("config_hash"),
        model_id=result.provenance.get("model_id"),
        stage_timings_ms=result.timings.stages,
        created_at=datetime.utcnow(),
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)

    return {
        "attempt_id": str(activity.id),
        "attempt_number": attempt_number,
        "condition": condition,
        "condition_source": condition_source,
        "is_correct": result.is_correct,
        "verdict": result.verdict,
        # gated attempts are a request to repeat, not a scored attempt, and
        # are excluded from correction-rate denominators in analysis
        "gated": gated,
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


@router.get("/health")
def pronunciation_health():
    """Whether scoring is available, and under exactly which configuration."""
    config = get_config()
    payload = {"ready": is_ready(), **config.provenance()}
    if is_ready():
        info = get_model().describe()
        payload.update(
            n_labels=info.n_labels,
            inventory_size=len(info.inventory),
            phone_level=info.is_phone_level,
        )
    return payload
