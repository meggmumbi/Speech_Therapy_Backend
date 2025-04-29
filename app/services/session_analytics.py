import uuid

from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from typing import Dict, List
from ..models import TherapySession, SessionActivity, ActivityItem


class SessionAnalytics:
    def __init__(self, db: Session):
        self.db = db

    def get_session_overview(self, session_id: uuid.UUID) -> Dict:
        session = self.db.query(TherapySession) \
            .options(
            joinedload(TherapySession.child),
            joinedload(TherapySession.category),
            joinedload(TherapySession.activities)
            .joinedload(SessionActivity.item)
        ) \
            .filter(TherapySession.id == session_id) \
            .first()

        if not session:
            raise ValueError("Session not found")

        # Calculate basic metrics
        duration = (
            (session.end_time - session.start_time).total_seconds() / 60
            if session.end_time else 0
        )
        total_activities = len(session.activities)
        correct_answers = sum(1 for a in session.activities if a.is_correct)
        accuracy = (correct_answers / total_activities) * 100 if total_activities else 0

        # Analyze activities
        activities = []
        strengths = set()
        weaknesses = set()

        for activity in session.activities:
            activities.append({
                "item_name": activity.item.name,
                "response_type": activity.response_type,
                "is_correct": activity.is_correct,
                "pronunciation_score": activity.pronunciation_score,
                "response_time": activity.response_time_seconds,
                "feedback": activity.feedback
            })

            if activity.is_correct:
                strengths.add(activity.item.name)
            else:
                weaknesses.add(activity.item.name)

        # Generate recommendations
        recommendations = self._generate_recommendations(
            accuracy,
            list(strengths),
            list(weaknesses)
        )

        return {
            "session_id": session.id,
            "child_name": session.child.name,
            "category_name": session.category.name,
            "start_time": session.start_time,
            "duration_minutes": duration,
            "total_activities": total_activities,
            "correct_answers": correct_answers,
            "accuracy_percentage": accuracy,
            "average_response_time": self._calculate_avg_response(session.activities),
            "activities": activities,
            "strengths": list(strengths),
            "areas_for_improvement": list(weaknesses),
            "recommendations": recommendations
        }

    def _calculate_avg_response(self, activities: List[SessionActivity]) -> float:
        times = [a.response_time_seconds for a in activities if a.response_time_seconds]
        return sum(times) / len(times) if times else 0

    def _generate_recommendations(self, accuracy: float, strengths: List[str], weaknesses: List[str]) -> List[str]:
        recommendations = []

        if accuracy < 50:
            recommendations.append("Consider revisiting basic concepts before advancing")
        elif accuracy < 75:
            recommendations.append("More practice would help solidify these concepts")
        else:
            recommendations.append("Excellent progress! Ready for more challenging activities")

        if strengths:
            recommendations.append(f"Strong performance on: {', '.join(strengths[:3])}")

        if weaknesses:
            recommendations.append(f"Practice needed on: {', '.join(weaknesses[:3])}")
            if len(weaknesses) > 3:
                recommendations.append("Focus on 2-3 items at a time for better retention")

        return recommendations