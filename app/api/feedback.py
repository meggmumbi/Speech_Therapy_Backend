from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import uuid
from ..models import CaregiverFeedback
from ..schemas.feedback import FeedbackCreate
from ..database import get_db

router = APIRouter(tags=["feedback"])


@router.post("/sessions/{session_id}/feedback")
def submit_session_feedback(
        session_id: uuid.UUID,
        feedback: FeedbackCreate,
        db: Session = Depends(get_db)
):
    db_feedback = CaregiverFeedback(
        **feedback.dict(),
        session_id=session_id,
        feedback_type="session"
    )
    db.add(db_feedback)
    db.commit()
    return {"status": "success"}


@router.get("/children/{child_id}/feedback")
def get_child_feedback(
        child_id: uuid.UUID,
        limit: int = 5,
        db: Session = Depends(get_db)
):
    feedback = db.query(CaregiverFeedback).filter(
        CaregiverFeedback.child_id == child_id
    ).order_by(CaregiverFeedback.created_at.desc()).limit(limit).all()

    return [
        {
            "id": str(f.id),
            "rating": f.rating,
            "comments": f.comments,
            "type": f.feedback_type,
            "date": f.created_at.date()
        }
        for f in feedback
    ]