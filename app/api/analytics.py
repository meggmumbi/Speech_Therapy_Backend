from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import uuid
from typing import List
from ..services import performance_updater, Recommender, ProgressTracker
from ..database import get_db
from ..models import TherapySession, SessionActivity, ChildPerformance, Caregiver
from ..utils.auth import get_current_user

router = APIRouter(tags=["analytics"])


@router.get("/children/{child_id}/progress")
def get_child_progress(
        child_id: uuid.UUID,
        db: Session = Depends(get_db),

):
    # Update all performance metrics first
    categories = db.query(TherapySession.category_id).filter(
        TherapySession.child_id == child_id
    ).distinct().all()

    for category in categories:
        performance_updater.update_performance_metrics(db, child_id, category[0])

    # Get recommendations
    recommender = Recommender(db)
    recommendations = recommender.get_recommendations(child_id)

    return {
        "progress": recommendations["progress_tracking"],
        "recommendations": {
            "practice_more": recommendations["practice_more"],
            "next_activities": recommendations["next_activities"],
            "encouragement": recommendations["encouragement"]
        }
    }


@router.get("/children/{child_id}/session-history")
def get_session_history(
        child_id: uuid.UUID,
        limit: int = 10,
        db: Session = Depends(get_db),
current_user: Caregiver = Depends(get_current_user)
):
    sessions = db.query(TherapySession).filter(
        TherapySession.child_id == child_id
    ).order_by(TherapySession.start_time.desc()).limit(limit).all()

    return [
        {
            "id": str(session.id),
            "date": session.start_time.date(),
            "category": session.category.name,
            "duration_minutes": (
                (session.end_time - session.start_time).total_seconds() / 60
                if session.end_time else None
            ),
            "score": sum(
                a.pronunciation_score for a in session.activities
                if a.pronunciation_score is not None
            ) / len(session.activities) if session.activities else 0
        }
        for session in sessions
    ]


@router.get("/children/{child_id}/performance-details")
def get_performance_details(
        child_id: uuid.UUID,
        db: Session = Depends(get_db),
current_user: Caregiver = Depends(get_current_user)
):
    performances = db.query(ChildPerformance).filter(
        ChildPerformance.child_id == child_id
    ).all()

    return [
        {
            "category": perf.category.name,
            "overall_score": perf.overall_score,
            "verbal_accuracy": (
                perf.verbal_success / perf.verbal_attempts
                if perf.verbal_attempts > 0 else 0
            ),
            "selection_accuracy": (
                perf.selection_success / perf.selection_attempts
                if perf.selection_attempts > 0 else 0
            ),
            "last_updated": perf.last_updated.date()
        }
        for perf in performances
    ]

@router.get("/children/{child_id}/progress-trends")
def get_progress_trends(
    child_id: uuid.UUID,
    db: Session = Depends(get_db),
current_user: Caregiver = Depends(get_current_user)
):
    tracker = ProgressTracker(db)
    return tracker.get_progress_trends(child_id)