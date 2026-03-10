import uuid

from sqlalchemy import func, case, literal, and_, exists, distinct
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from typing import Dict, List, Set

from .. import models
from ..models import TherapySession, SessionActivity, ActivityItem
from ..models.child import child_category_association


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

    def get_child_categories_with_stats(self, child_id: uuid.UUID):
        # Get the child's selected categories with their order
        child_interests = (
            self.db.query(
                models.ActivityCategory.id.label('category_id'),
                literal(True).label('is_selected')  # Mark as selected
            )
            .join(child_category_association,
                  models.ActivityCategory.id == child_category_association.c.category_id)
            .filter(child_category_association.c.child_id == child_id)
            .filter(models.ActivityCategory.type == 'personalized')
            .subquery()
        )



        # Get all categories with selection status
        all_categories = (
            self.db.query(
                models.ActivityCategory.id,
                models.ActivityCategory.name,
                models.ActivityCategory.description,
                models.ActivityCategory.difficulty_level,
                models.ActivityCategory.type,
                # Use a fixed display order - selected categories first
                case(
                    (child_interests.c.category_id.isnot(None), True),
                    else_=False
                ).label('is_selected'),
                # Display priority - selected first (1), others later (2)
                case(
                    (child_interests.c.category_id.isnot(None), 1),
                    else_=2
                ).label('display_priority')
            )
            .filter(models.ActivityCategory.type == 'personalized')
            .outerjoin(child_interests, models.ActivityCategory.id == child_interests.c.category_id)
            .subquery()
        )

        # Count items in each category
        item_counts = (
            self.db.query(
                models.ActivityItem.category_id,
                func.count(models.ActivityItem.id).label('item_count')
            )
            .join(models.ActivityCategory, models.ActivityItem.category_id == models.ActivityCategory.id)
            .filter(models.ActivityCategory.type == 'personalized')
            .group_by(models.ActivityItem.category_id)
            .subquery()
        )


        # Get aggregated session attempts data
        category_attempts = (
            self.db.query(
                models.ActivityItem.category_id,
                func.count(models.SessionActivity.id).label('total_item_attempts'),
                func.count(distinct(models.TherapySession.id)).label('total_attempts'),
                func.sum(case((models.SessionActivity.is_correct == True, 1), else_=0)).label('correct_attempts'),
                func.max(models.SessionActivity.created_at).label('last_attempt_date'),
            )
            .join(models.ActivityItem, models.SessionActivity.item_id == models.ActivityItem.id)
            .join(models.TherapySession, models.SessionActivity.session_id == models.TherapySession.id)
            .filter(models.TherapySession.child_id == child_id)
            .filter(models.ActivityCategory.type == 'personalized')
            .group_by(models.ActivityItem.category_id)
            .subquery()
        )

        # Final query combining all data
        results = (
            self.db.query(
                all_categories.c.id.label('id'),
                all_categories.c.name,
                all_categories.c.description,
                all_categories.c.difficulty_level,
                all_categories.c.is_selected,
                func.coalesce(item_counts.c.item_count, 0).label('item_count'),
                func.coalesce(category_attempts.c.total_attempts, 0).label('total_attempts'),
                case(
                    (func.coalesce(category_attempts.c.total_item_attempts, 0) > 0,
                     (func.coalesce(category_attempts.c.correct_attempts, 0) /
                      func.coalesce(category_attempts.c.total_item_attempts, 1)) * 100),
                    else_=None
                ).label('latest_performance'),
                category_attempts.c.last_attempt_date,
                case(
                    (all_categories.c.is_selected == True, 1),
                    else_=2
                ).label('child_interest_order')
            )
            .outerjoin(item_counts, all_categories.c.id == item_counts.c.category_id)
            .outerjoin(category_attempts, all_categories.c.id == category_attempts.c.category_id)
            .order_by(
                all_categories.c.display_priority.asc(),
                all_categories.c.name.asc()
            )
            .all()
        )

        return results

    def get_generic_child_categories_with_stats(self, child_id: uuid.UUID):
        # Get the child's selected categories with their order
        child_interests = (
            self.db.query(
                models.ActivityCategory.id.label('category_id'),
                literal(True).label('is_selected')  # Mark as selected
            )
            .join(child_category_association,
                  models.ActivityCategory.id == child_category_association.c.category_id)
            .filter(child_category_association.c.child_id == child_id)
            .filter(models.ActivityCategory.type == 'generic')
            .subquery()
        )



        # Get all categories with selection status
        all_categories = (
            self.db.query(
                models.ActivityCategory.id,
                models.ActivityCategory.name,
                models.ActivityCategory.description,
                models.ActivityCategory.difficulty_level,
                models.ActivityCategory.type,
                # Use a fixed display order - selected categories first
                case(
                    (child_interests.c.category_id.isnot(None), True),
                    else_=False
                ).label('is_selected'),
                # Display priority - selected first (1), others later (2)
                case(
                    (child_interests.c.category_id.isnot(None), 1),
                    else_=2
                ).label('display_priority')
            )
            .filter(models.ActivityCategory.type == 'generic')
            .outerjoin(child_interests, models.ActivityCategory.id == child_interests.c.category_id)
            .subquery()
        )

        # Count items in each category
        item_counts = (
            self.db.query(
                models.ActivityItem.category_id,
                func.count(models.ActivityItem.id).label('item_count')
            )
            .join(models.ActivityCategory, models.ActivityItem.category_id == models.ActivityCategory.id)
            .filter(models.ActivityCategory.type == 'generic')
            .group_by(models.ActivityItem.category_id)
            .subquery()
        )


        # Get aggregated session attempts data
        category_attempts = (
            self.db.query(
                models.ActivityItem.category_id,
                func.count(models.SessionActivity.id).label('total_item_attempts'),
                func.count(distinct(models.TherapySession.id)).label('total_attempts'),
                func.sum(case((models.SessionActivity.is_correct == True, 1), else_=0)).label('correct_attempts'),
                func.max(models.SessionActivity.created_at).label('last_attempt_date'),
            )
            .join(models.ActivityItem, models.SessionActivity.item_id == models.ActivityItem.id)
            .join(models.TherapySession, models.SessionActivity.session_id == models.TherapySession.id)
            .filter(models.TherapySession.child_id == child_id)
            .filter(models.ActivityCategory.type == 'generic')
            .group_by(models.ActivityItem.category_id)
            .subquery()
        )

        # Final query combining all data
        results = (
            self.db.query(
                all_categories.c.id.label('id'),
                all_categories.c.name,
                all_categories.c.description,
                all_categories.c.difficulty_level,
                all_categories.c.is_selected,
                func.coalesce(item_counts.c.item_count, 0).label('item_count'),
                func.coalesce(category_attempts.c.total_attempts, 0).label('total_attempts'),
                case(
                    (func.coalesce(category_attempts.c.total_item_attempts, 0) > 0,
                     (func.coalesce(category_attempts.c.correct_attempts, 0) /
                      func.coalesce(category_attempts.c.total_item_attempts, 1)) * 100),
                    else_=None
                ).label('latest_performance'),
                category_attempts.c.last_attempt_date,
                case(
                    (all_categories.c.is_selected == True, 1),
                    else_=2
                ).label('child_interest_order')
            )
            .outerjoin(item_counts, all_categories.c.id == item_counts.c.category_id)
            .outerjoin(category_attempts, all_categories.c.id == category_attempts.c.category_id)
            .order_by(
                all_categories.c.display_priority.asc(),
                all_categories.c.name.asc()
            )
            .all()
        )

        return results