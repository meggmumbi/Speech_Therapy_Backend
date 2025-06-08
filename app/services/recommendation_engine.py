from collections import defaultdict
from typing import List, Dict
from uuid import UUID
from sqlalchemy.orm import Session
import numpy as np
from scipy.spatial.distance import cosine
from datetime import datetime, timedelta

from app.models import Child, ChildPerformance, TherapySession, CaregiverFeedback, ActivityItem, ActivityCategory, \
    SessionActivity


class RecommendationEngine:
    def __init__(self, db_session: Session):
        self.db = db_session

    def get_child_profile(self, child_id: UUID) -> Dict:
        """Get comprehensive child profile including performance data"""
        child = self.db.query(Child).filter(Child.id == child_id).first()
        if not child:
            return None

        # Get performance data
        performances = self.db.query(ChildPerformance).filter(
            ChildPerformance.child_id == child_id
        ).all()

        # Get recent sessions (last 30 days)
        recent_sessions = self.db.query(TherapySession).filter(
            TherapySession.child_id == child_id,
            TherapySession.start_time >= datetime.utcnow() - timedelta(days=30)
        ).all()

        # Get caregiver feedback
        feedback = self.db.query(CaregiverFeedback).filter(
            CaregiverFeedback.child_id == child_id
        ).order_by(CaregiverFeedback.created_at.desc()).limit(5).all()

        return {
            "child": child,
            "performances": performances,
            "recent_sessions": recent_sessions,
            "feedback": feedback
        }

    def calculate_skill_vector(self, child_id: UUID) -> Dict[str, float]:
        """Calculate a numerical vector representing the child's skills"""
        performances = self.db.query(ChildPerformance).filter(
            ChildPerformance.child_id == child_id
        ).all()

        # Initialize with default values
        vector = {
            "verbal_attempts": 0,
            "verbal_success_rate": 0,
            "selection_attempts": 0,
            "selection_success_rate": 0,
            "overall_score": 0,
            "categories_attempted": 0
        }

        if not performances:
            return vector

        total_verbal = 0
        total_verbal_success = 0
        total_selection = 0
        total_selection_success = 0
        total_score = 0

        for perf in performances:
            total_verbal += perf.verbal_attempts or 0
            total_verbal_success += perf.verbal_success or 0
            total_selection += perf.selection_attempts or 0
            total_selection_success += perf.selection_success or 0
            total_score += perf.overall_score or 0

        vector.update({
            "verbal_attempts": total_verbal,
            "verbal_success_rate": total_verbal_success / total_verbal if total_verbal > 0 else 0,
            "selection_attempts": total_selection,
            "selection_success_rate": total_selection_success / total_selection if total_selection > 0 else 0,
            "overall_score": total_score / len(performances),
            "categories_attempted": len(performances)
        })

        return vector

    def find_similar_children(self, child_id: UUID, limit: int = 5) -> List[Dict]:
        """Find children with similar performance profiles"""
        target_vector = self.calculate_skill_vector(child_id)
        all_children = self.db.query(Child).all()

        similarities = []

        for child in all_children:
            if child.id == child_id:
                continue

            child_vector = self.calculate_skill_vector(child.id)
            similarity = 1 - cosine(
                list(target_vector.values()),
                list(child_vector.values())
            )

            similarities.append({
                "child": child,
                "similarity": similarity,
                "vector": child_vector
            })

        # Sort by similarity and return top matches
        return sorted(similarities, key=lambda x: x["similarity"], reverse=True)[:limit]

    # def recommend_activities(self, child_id: UUID, category_id: UUID = None) -> List[ActivityItem]:
    #     """Recommend activities based on child's profile and performance"""
    #     child_profile = self.get_child_profile(child_id)
    #
    #     # Get target difficulty level
    #     if child_profile["performances"]:
    #         avg_score = np.mean([p.overall_score for p in child_profile["performances"] if p.overall_score])
    #         if avg_score < 0.4:
    #             difficulty = "easy"
    #         elif avg_score < 0.7:
    #             difficulty = "medium"
    #         else:
    #             difficulty = "hard"
    #     else:
    #         difficulty = "easy"  # Default for new children
    #
    #     # Filter by category if specified
    #     query = self.db.query(ActivityItem)
    #     if category_id:
    #         query = query.filter(ActivityItem.category_id == category_id)
    #
    #     # Get items at appropriate difficulty level
    #     items = query.filter(
    #         (ActivityItem.difficulty_level == difficulty) |
    #         (ActivityItem.difficulty_level == None)  # Items that inherit from category
    #     ).all()
    #
    #     # Filter out recently attempted items
    #     recent_item_ids = {a.item_id for session in child_profile["recent_sessions"]
    #                        for a in session.activities}
    #     items = [item for item in items if item.id not in recent_item_ids]
    #
    #     # Sort by potential effectiveness (simple heuristic - could be enhanced)
    #     items.sort(key=lambda x: (
    #         -len([f for f in child_profile["feedback"]
    #               if "progress" in f.progress_achievements.lower()]),
    #         x.difficulty_level == difficulty  # Prefer items with explicit difficulty
    #     ))
    #
    #     return items[:10]  # Return top 10 recommendations

    def generate_adaptive_session(self, child_id: UUID, caregiver_id: UUID) -> TherapySession:
        """Create an adaptive therapy session based on child's needs"""
        child_profile = self.get_child_profile(child_id)

        # Determine focus category (weakest area or new category)
        if child_profile["performances"]:
            focus_category = min(
                child_profile["performances"],
                key=lambda p: p.overall_score
            ).category
        else:
            # For new children, start with an easy category
            focus_category = self.db.query(ActivityCategory).filter(
                ActivityCategory.difficulty_level == "easy"
            ).first()

        # Create new session
        session = TherapySession(
            child_id=child_id,
            caregiver_id=caregiver_id,
            category_id=focus_category.id,
            start_time=datetime.utcnow(),
            current_level="adaptive"  # Mark as adaptive session
        )

        self.db.add(session)
        self.db.commit()

        # Add recommended activities
        recommended_items = self.recommend_activities(child_id, focus_category.id)
        for item in recommended_items[:5]:  # Start with 5 activities
            session.activities.append(SessionActivity(
                item_id=item.id,
                attempt_number=1
            ))

        self.db.commit()
        return session

    def update_session_adaptively(self, session_id: UUID):
        """Adjust the session in progress based on real-time performance"""
        session = self.db.query(TherapySession).filter(
            TherapySession.id == session_id
        ).first()

        if not session or session.is_completed:
            return

        # Calculate success rate so far
        completed_activities = [a for a in session.activities if a.is_correct is not None]
        if not completed_activities:
            return

        success_rate = sum(1 for a in completed_activities if a.is_correct) / len(completed_activities)

        # Determine adjustment needed
        if success_rate > 0.75:
            # Child is doing well - increase difficulty
            next_items = self.db.query(ActivityItem).filter(
                ActivityItem.category_id == session.category_id,
                ActivityItem.difficulty_level.in_(["medium", "hard"])
            ).limit(3).all()
        elif success_rate < 0.4:
            # Child is struggling - decrease difficulty
            next_items = self.db.query(ActivityItem).filter(
                ActivityItem.category_id == session.category_id,
                ActivityItem.difficulty_level.in_(["easy", "medium"])
            ).limit(3).all()
        else:
            # Continue with similar difficulty
            next_items = self.recommend_activities(session.child_id, session.category_id)[:3]

        # Add new activities to session
        for item in next_items:
            if item.id not in {a.item_id for a in session.activities}:
                session.activities.append(SessionActivity(
                    item_id=item.id,
                    attempt_number=1
                ))

        self.db.commit()


    def recommend_activities(self, child_id: UUID, category_id: UUID = None):
        child_profile = self.get_child_profile(child_id)

        # Get performance by category
        category_performance = {
            perf.category_id: perf
            for perf in child_profile["performances"]
        }

        # If no category specified, recommend categories first
        if not category_id:
            return self._recommend_categories(child_id, category_performance)

        # Otherwise recommend items within category
        return self._recommend_category_items(child_id, category_id, category_performance)

    def _recommend_categories(self, child_id: UUID, category_performance: Dict):
        """Recommend which categories to focus on"""
        all_categories = self.db.query(ActivityCategory).all()

        recommendations = []
        for category in all_categories:
            perf = category_performance.get(category.id)

            if not perf:
                # New category - recommend if matches child's level
                if category.difficulty_level == "easy":
                    recommendations.append({
                        "type": "category",
                        "id": category.id,
                        "name": category.name,
                        "reason": "New easy category for initial exposure",
                        "sort_key": 0  # Highest priority for new categories
                    })
            else:
                # Calculate improvement potential
                improvement_potential = 1 - perf.overall_score
                if improvement_potential > 0.3:
                    recommendations.append({
                        "type": "category",
                        "id": category.id,
                        "name": category.name,
                        "reason": f"Current score {perf.overall_score:.0%} - room for improvement",
                        "sort_key": improvement_potential
                    })

        # Sort by: 1) New categories first, then by improvement potential
        return sorted(recommendations, key=lambda x: -x["sort_key"])

    def _recommend_category_items(self, child_id: UUID, category_id: UUID, category_performance: Dict):
        """Recommend specific items within a category"""
        category = self.db.query(ActivityCategory).get(category_id)
        perf = category_performance.get(category_id)

        # Determine target difficulty
        if perf:
            if perf.overall_score < 0.4:
                target_difficulty = "easy"
            elif perf.overall_score < 0.7:
                target_difficulty = "medium"
            else:
                target_difficulty = "hard"
        else:
            target_difficulty = category.difficulty_level or "easy"

        # Get items in this category
        items = self.db.query(ActivityItem).filter(
            ActivityItem.category_id == category_id
        ).all()

        # Filter by difficulty (item-level or category default)
        candidates = []
        for item in items:
            item_diff = item.difficulty_level or category.difficulty_level
            if item_diff == target_difficulty:
                candidates.append(item)

        # Sort by success rate if available
        if perf:
            # Get session data for these items
            item_performance = self._get_item_performance(child_id, [i.id for i in items])
            candidates.sort(key=lambda x: (
                item_performance.get(x.id, {}).get("success_rate", 1),
                x.difficulty_level == target_difficulty  # Prefer exact matches
            ))

        return [{
            "type": "item",
            "id": item.id,
            "name": item.name,
            "difficulty": item.difficulty_level or category.difficulty_level,
            "reason": f"Target {target_difficulty} level for {category.name} practice"
        } for item in candidates[:5]]  # Return top 5

    def _get_item_performance(self, child_id: UUID, item_ids: List[UUID]) -> Dict[UUID, Dict[str, float]]:
        """Get performance metrics for specific activity items"""
        performance_data = {}

        # Get all session activities for this child through therapy sessions
        activities = self.db.query(SessionActivity).join(
            TherapySession,
            SessionActivity.session_id == TherapySession.id
        ).filter(
            TherapySession.child_id == child_id,
            SessionActivity.item_id.in_(item_ids)
        ).all()

        # Group by item_id
        item_activities = defaultdict(list)
        for activity in activities:
            item_activities[activity.item_id].append(activity)

        # Calculate metrics for each item
        for item_id, activities in item_activities.items():
            verbal_attempts = sum(1 for a in activities if a.response_type == "verbal")
            verbal_success = sum(1 for a in activities if a.response_type == "verbal" and a.is_correct)
            selection_attempts = sum(1 for a in activities if a.response_type == "nonverbal")
            selection_success = sum(1 for a in activities if a.response_type == "nonverbal" and a.is_correct)

            total_attempts = len(activities)
            success_rate = (verbal_success + selection_success) / total_attempts if total_attempts > 0 else 0

            performance_data[item_id] = {
                "success_rate": success_rate,
                "verbal_attempts": verbal_attempts,
                "verbal_success": verbal_success,
                "selection_attempts": selection_attempts,
                "selection_success": selection_success,
                "total_attempts": total_attempts
            }

        return performance_data