import uuid
from datetime import datetime
from http.client import HTTPException
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..models import ActivityItem, Caregiver, TherapySession, SessionActivity
from ..schemas import (ActivityItemCreate, activity_item, activity_category
                       )

from ..database import get_db
from ..utils.auth import get_current_user


class TranscriptionRequest(BaseModel):
    transcription: str
router = APIRouter(tags=["generic"])

@router.post("/categoryItems/")
async def create_item(
        item: ActivityItemCreate,
        db: Session = Depends(get_db),

):

    db_item = ActivityItem(
        name=item.name,
        description=item.description,
        category_id=item.category_id,
        difficulty_level=item.difficulty_level,
        image_url=item.image_url,

    )

    db.add(db_item)
    db.commit()
    db.refresh(db_item)

    return db_item

@router.get("/categories/", response_model=List[activity_category.ActivityCategory])
def list_categories(
    db: Session = Depends(get_db),
    current_user: Caregiver = Depends(get_current_user)
):
    return (
        db.query(models.ActivityCategory)
        .filter(models.ActivityCategory.type == "generic")
        .all()
    )


@router.post("/sessions/{session_id}/process-transcription")
async def process_transcription_response(
        session_id: uuid.UUID,
        item_id: uuid.UUID,
        request: TranscriptionRequest,
        response_time_seconds: float,
        db: Session = Depends(get_db)
):
    try:
        transcription = request.transcription
        session = db.query(TherapySession).filter(TherapySession.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        item = db.query(ActivityItem).filter(ActivityItem.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Activity item not found")

        previous_attempts = db.query(SessionActivity).filter(
            SessionActivity.session_id == session_id,
            SessionActivity.item_id == item_id
        ).order_by(SessionActivity.attempt_number.desc()).all()

        current_attempt_number = len(previous_attempts) + 1

        # Compare transcription with item name to determine correctness
        is_correct = transcription.strip().lower() == item.name.strip().lower()

        # Generate feedback based on correctness
        if is_correct:
            feedback = {
                "right": f"Correct!, Lets go to the next item.",
                "wrong": None
            }
        else:
            feedback = {
                "right": None,
                "wrong": f"Try again."
            }

        analysis = {
            "is_correct": is_correct,
            "feedback": feedback,
            "details": {
                "expected": item.name,
                "received": transcription,
                "match_type": "exact" if is_correct else "mismatch"
            }
        }

        # Store results
        activity = SessionActivity(
            session_id=session_id,
            item_id=item_id,
            attempt_number=current_attempt_number,
            response_time_seconds=response_time_seconds,
            response_type="generic",
            response_text=transcription,
            is_correct=analysis["is_correct"],
            created_at=datetime.utcnow()
        )

        db.add(activity)
        db.commit()
        db.refresh(activity)

        return {
            "transcription": transcription,
            "analysis": {
                "is_correct": analysis["is_correct"],
                "feedback": analysis["feedback"]["right"] if analysis["is_correct"] else analysis["feedback"]["wrong"],
                "details": str(analysis["details"])  # Convert details to string if needed
            },
            "activity_id": str(activity.id),
            "attempt_number": current_attempt_number,
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Processing failed: {str(e)}")