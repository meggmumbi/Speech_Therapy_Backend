import os
import subprocess
import tempfile

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
import uuid
from datetime import datetime

from numba.core.cgutils import printf

from ..services.whisper_service import transcribe_audio, validate_audio_file
from ..services.pronunciation_analysis import analyze_pronunciation, detect_stuttering, detect_echolalia
from ..database import get_db
from sqlalchemy.orm import Session
from ..models import SessionActivity, TherapySession, ActivityItem

router = APIRouter(tags=["speech_processing"])


@router.post("/sessions/{session_id}/process-audio")
async def process_audio_response(
        session_id: uuid.UUID,
        item_id: uuid.UUID,
        response_time_seconds: float,
        audio_file: UploadFile = File(...),
        db: Session = Depends(get_db)
):
    try:
        # 1. Transcribe audio
        transcription = await transcribe_audio(audio_file)

        # Verify session exists
        session = db.query(TherapySession).filter(TherapySession.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Verify item exists
        item = db.query(ActivityItem).filter(ActivityItem.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Activity item not found")

        analysis = analyze_pronunciation(item.name, transcription)
        is_stuttering = detect_stuttering(transcription)
        is_echolalia = detect_echolalia(item.name, transcription)

        # 3. Store results
        activity = SessionActivity(
            session_id=session_id,
            item_id=item_id,
            response_time_seconds=response_time_seconds,
            response_type="verbal",
            response_text=transcription,
            is_correct=analysis["is_correct"],
            pronunciation_score=analysis["similarity_score"],
            feedback=analysis["feedback"],
            created_at=datetime.utcnow()
        )

        db.add(activity)
        db.commit()
        db.refresh(activity)


        return {
            "transcription": transcription,
            "analysis": analysis,
            "activity_id": str(activity.id),
            "stuttering": is_stuttering,
            "echolalia": is_echolalia
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Processing failed: {str(e)}")


async def convert_3gp_to_wav(audio_file: UploadFile):
    try:
        # Create temp files
        with tempfile.NamedTemporaryFile(suffix=".3gp", delete=False) as tmp_3gp:
            tmp_3gp_path = tmp_3gp.name
            tmp_3gp.write(await audio_file.read())

        wav_path = tmp_3gp_path.replace(".3gp", ".wav")

        # Convert using ffmpeg
        subprocess.run([
            "ffmpeg",
            "-y",  # Overwrite without asking
            "-i", tmp_3gp_path,
            "-acodec", "pcm_s16le",  # Standard WAV format
            "-ar", "16000",  # 16kHz sample rate
            "-ac", "1",  # Mono channel
            wav_path
        ], check=True)

        return wav_path

    except Exception as e:
        if os.path.exists(tmp_3gp_path):
            os.unlink(tmp_3gp_path)
        if os.path.exists(wav_path):
            os.unlink(wav_path)
        raise HTTPException(500, f"Audio conversion failed: {str(e)}")