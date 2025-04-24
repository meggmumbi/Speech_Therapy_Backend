from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
import uuid
from datetime import datetime
from ..services.whisper_service import transcribe_audio, validate_audio_file
from ..services.pronunciation_analysis import analyze_pronunciation
from ..database import get_db
from sqlalchemy.orm import Session
from ..models import SessionActivity, TherapySession, ActivityItem

router = APIRouter(tags=["speech_processing"])


@router.post("/sessions/{session_id}/process-audio")
async def process_audio_response(
        session_id: uuid.UUID,
        item_id: uuid.UUID,
        audio_file: UploadFile = File(...),
        db: Session = Depends(get_db)
):
    # Validate audio file first
    await validate_audio_file(audio_file)
    # Verify session exists
    session = db.query(TherapySession).filter(TherapySession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Verify item exists
    item = db.query(ActivityItem).filter(ActivityItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Activity item not found")

    try:
        # Step 1: Transcribe audio with Whisper
        transcription = await transcribe_audio(audio_file)

        # Step 2: Analyze pronunciation
        analysis = analyze_pronunciation(item.name, transcription)

        # Step 3: Store results
        activity = SessionActivity(
            session_id=session_id,
            item_id=item_id,
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
            "activity_id": str(activity.id)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))