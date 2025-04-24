import uuid

from sqlalchemy.orm import Session
from ..models import ChildPerformance, SessionActivity, TherapySession
from datetime import datetime


def update_performance_metrics(db: Session, child_id: uuid.UUID, category_id: uuid.UUID):
    # Get all session activities for this child and category
    activities = db.query(SessionActivity).join(
        TherapySession,
        TherapySession.id == SessionActivity.session_id
    ).filter(
        TherapySession.child_id == child_id,
        TherapySession.category_id == category_id
    ).all()

    # Calculate metrics
    verbal_attempts = sum(1 for a in activities if a.response_type == "verbal")
    verbal_success = sum(1 for a in activities if a.response_type == "verbal" and a.is_correct)
    selection_attempts = sum(1 for a in activities if a.response_type == "select")
    selection_success = sum(1 for a in activities if a.response_type == "select" and a.is_correct)

    # Calculate overall score (weighted average)
    total_attempts = verbal_attempts + selection_attempts
    if total_attempts > 0:
        overall_score = (
                (verbal_success * 0.7 + selection_success * 0.3) /
                (verbal_attempts * 0.7 + selection_attempts * 0.3)
        )
    else:
        overall_score = 0.0

    # Update or create performance record
    performance = db.query(ChildPerformance).filter(
        ChildPerformance.child_id == child_id,
        ChildPerformance.category_id == category_id
    ).first()

    if performance:
        performance.overall_score = overall_score
        performance.verbal_attempts = verbal_attempts
        performance.verbal_success = verbal_success
        performance.selection_attempts = selection_attempts
        performance.selection_success = selection_success
    else:
        performance = ChildPerformance(
            child_id=child_id,
            category_id=category_id,
            overall_score=overall_score,
            verbal_attempts=verbal_attempts,
            verbal_success=verbal_success,
            selection_attempts=selection_attempts,
            selection_success=selection_success
        )
        db.add(performance)

    db.commit()
    return performance