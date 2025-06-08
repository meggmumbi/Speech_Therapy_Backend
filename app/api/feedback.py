from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
import uuid

from .. import models
from ..schemas.feedback import FeedbackCreate
from ..database import get_db
from ..utils.auth import get_current_user

router = APIRouter(tags=["feedback"])


@router.post("/sessions/{session_id}/feedback")
def submit_session_feedback(
        session_id: uuid.UUID,
        feedback: FeedbackCreate,
        db: Session = Depends(get_db),
        current_user: models.Caregiver = Depends(get_current_user)
):
    """
    Submit comprehensive feedback about a therapy session including:
    - Rating (1-5)
    - General comments
    - Progress and achievements
    - Areas needing improvement
    - Behavioral observations
    """
    # Verify session exists
    session = db.query(models.TherapySession).filter_by(id=session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Verify child exists
    child = db.query(models.Child).filter_by(id=feedback.child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    db_feedback = models.CaregiverFeedback(
        **feedback.model_dump(),
        session_id=session_id,
        caregiver_id=current_user.id,
        feedback_type="session"
    )

    db.add(db_feedback)
    db.commit()
    db.refresh(db_feedback)

    return {
        "status": "success",
        "feedback_id": str(db_feedback.id)
    }


@router.get("/children/{child_id}/feedback")
def get_child_feedback(
        child_id: uuid.UUID,
        limit: int = 5,
        db: Session = Depends(get_db),
        current_user: models.Caregiver = Depends(get_current_user)
):
    """
    Get comprehensive feedback history for a child including:
    - All feedback fields
    - Therapist/caregiver info
    - Session context
    """
    feedback = db.query(models.CaregiverFeedback) \
        .options(
        joinedload(models.CaregiverFeedback.session)
        .joinedload(models.TherapySession.category)
    ) \
        .filter(models.CaregiverFeedback.child_id == child_id) \
        .order_by(models.CaregiverFeedback.created_at.desc()) \
        .limit(limit) \
        .all()

    return [
        {
            "id": str(f.id),
            "date": f.created_at.date(),
            "therapist": current_user.username if current_user else "System",
            "session": {
                "id": str(f.session.id) if f.session else None,
                "category": f.session.category.name if f.session and f.session.category else None
            },
            "rating": f.rating,
            "comments": f.comments,
            "progress_achievements": f.progress_achievements,
            "areas_for_improvement": f.areas_for_improvement,
            "behavioral_observations": f.behavioral_observations
        }
        for f in feedback
    ]