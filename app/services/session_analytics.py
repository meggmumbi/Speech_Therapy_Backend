import uuid

from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from typing import Dict, List, Set
from ..models import TherapySession, SessionActivity, ActivityItem


class SessionAnalytics:
    def __init__(self, db: Session):
        self.db = db

    def get_session_overview(self, session_id: uuid.UUID) -> Dict:
        """
        Get comprehensive overview of a therapy session
        """
        session = self._get_session_with_relations(session_id)

        # Calculate metrics
        duration = self._calculate_duration(session)
        total_activities = len(session.activities)
        correct_answers = sum(1 for a in session.activities if a.is_correct)
        accuracy = self._calculate_accuracy(correct_answers, total_activities)

        # Analyze activities
        activities, strengths, weaknesses = self._analyze_activities(session.activities)

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
            "recommendations": self._generate_recommendations(accuracy, strengths, weaknesses)
        }

    def _get_session_with_relations(self, session_id: uuid.UUID) -> TherapySession:
        """Get session with all related data loaded"""
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
        return session

    def _calculate_duration(self, session: TherapySession) -> float:
        """Calculate session duration in minutes"""
        if not session.end_time:
            return 0.0
        return (session.end_time - session.start_time).total_seconds() / 60

    def _calculate_accuracy(self, correct: int, total: int) -> float:
        """Calculate accuracy percentage"""
        return (correct / total * 100) if total > 0 else 0.0

    def _analyze_activities(self, activities: List[SessionActivity]) -> tuple:
        """Analyze session activities and identify strengths/weaknesses"""
        activity_data = []
        strengths: Set[str] = set()
        weaknesses: Set[str] = set()

        for activity in activities:
            activity_data.append({
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

        return activity_data, strengths, weaknesses

    def _calculate_avg_response(self, activities: List[SessionActivity]) -> float:
        """Calculate average response time"""
        times = [a.response_time_seconds for a in activities if a.response_time_seconds]
        return sum(times) / len(times) if times else 0.0

    def _generate_recommendations(self, accuracy: float,
                                  strengths: Set[str],
                                  weaknesses: Set[str]) -> List[str]:
        """Generate personalized recommendations"""
        recommendations = []

        if accuracy < 50:
            recommendations.append("Consider revisiting basic concepts before advancing")
        elif accuracy < 75:
            recommendations.append("More practice would help solidify these concepts")
        else:
            recommendations.append("Excellent progress! Ready for more challenging activities")

        if strengths:
            recommendations.append(f"Strong performance on: {', '.join(sorted(strengths)[:3])}")

        if weaknesses:
            weaknesses_list = sorted(weaknesses)
            recommendations.append(f"Practice needed on: {', '.join(weaknesses_list[:3])}")
            if len(weaknesses_list) > 3:
                recommendations.append("Focus on 2-3 items at a time for better retention")

        return recommendations