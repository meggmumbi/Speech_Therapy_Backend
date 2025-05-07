from typing import Dict, List  # Add this import for Dict
from sqlalchemy.orm import Session, joinedload  # Add this import for Session
import uuid
from ..models import ChildPerformance, TherapySession, ActivityCategory, ActivityItem
from ..ml.recommendation_model import RecommendationModel


class Recommender:
    def __init__(self, db: Session):
        self.db = db
        self.ml_model = RecommendationModel()

    def get_recommendations(self, child_id: uuid.UUID) -> Dict:
        """Get combined ML and rule-based recommendations"""
        try:
            child_data = self._prepare_ml_input(child_id)
            ml_recommendation = self.ml_model.predict(child_data)
            confidence = self._get_confidence_score(child_data)
        except Exception as e:
            print(f"Model prediction failed: {str(e)}")
            return self._get_rule_based_recommendations(child_id)

        rule_based = self._get_rule_based_recommendations(child_id)
        return {
            **rule_based,
            "ml_recommendation": ml_recommendation,
            "confidence_score": confidence,
            "model_version": "1.0"
        }

    def _get_recommended_difficulty(self, category: ActivityCategory) -> str:
        """Determine recommended difficulty level based on category"""
        if category.difficulty_level == "easy":
            return "medium"
        elif category.difficulty_level == "medium":
            return "hard"
        else:
            return "hard"

    def _prepare_ml_input(self, child_id: uuid.UUID) -> Dict[str, float]:
        """Prepare child data for ML model input"""
        performances = self.db.query(ChildPerformance) \
            .filter(ChildPerformance.child_id == child_id) \
            .all()

        # Calculate metrics
        total_verbal = sum(p.verbal_attempts for p in performances)
        verbal_accuracy = (
            sum(p.verbal_success for p in performances) / total_verbal
            if total_verbal > 0 else 0
        )

        total_selection = sum(p.selection_attempts for p in performances)
        selection_accuracy = (
            sum(p.selection_success for p in performances) / total_selection
            if total_selection > 0 else 0
        )

        return {
            'verbal_accuracy': verbal_accuracy,
            'selection_accuracy': selection_accuracy,
            'category_difficulty': self._get_avg_difficulty(child_id),
            'time_spent': self._get_average_session_time(child_id),
            'success_rate': sum(p.overall_score for p in performances) / len(performances) if performances else 0,
            'previous_attempts': total_verbal + total_selection
        }

    def _get_avg_difficulty(self, child_id: uuid.UUID) -> float:
        """Calculate average difficulty level of attempted categories"""
        difficulties = {
            'easy': 1,
            'medium': 2,
            'hard': 3
        }

        categories = self.db.query(ActivityCategory) \
            .join(TherapySession, TherapySession.category_id == ActivityCategory.id) \
            .filter(TherapySession.child_id == child_id) \
            .all()

        if not categories:
            return 1.0  # Default to easy if no sessions

        avg_score = sum(difficulties.get(c.difficulty_level, 1) for c in categories) / len(categories)
        return avg_score

    def _get_average_session_time(self, child_id: uuid.UUID) -> float:
        """Calculate average session time in minutes"""
        sessions = self.db.query(TherapySession) \
            .filter(
            TherapySession.child_id == child_id,
            TherapySession.end_time.isnot(None)
        ) \
            .all()

        if not sessions:
            return 0.0

        total_seconds = sum(
            (s.end_time - s.start_time).total_seconds()
            for s in sessions
        )
        return total_seconds / len(sessions) / 60

    def _get_confidence_score(self, child_data: Dict[str, float]) -> float:
        """Calculate confidence score for recommendations"""
        verbal_weight = 0.6
        selection_weight = 0.4
        return (
                child_data['verbal_accuracy'] * verbal_weight +
                child_data['selection_accuracy'] * selection_weight
        )

    def _get_rule_based_recommendations(self, child_id: uuid.UUID) -> Dict:
        """Generate rule-based recommendations"""
        performances = self.db.query(ChildPerformance) \
            .options(joinedload(ChildPerformance.category)) \
            .filter(ChildPerformance.child_id == child_id) \
            .all()

        if not performances:
            return self._get_initial_recommendations()

        weak_categories = [
                              perf.category.name for perf in performances
                              if perf.overall_score < 0.6 and perf.category
                          ][:3]

        strong_categories = [
                                perf.category.name for perf in performances
                                if perf.overall_score >= 0.8 and perf.category
                            ][:2]

        return {
            "practice_more": weak_categories,
            "next_activities": self._suggest_next_activities(weak_categories),
            "progress_tracking": self._generate_progress_report(performances),
            "encouragement": self._generate_encouragement(strong_categories)
        }

    def _get_initial_recommendations(self) -> Dict:
        """Default recommendations for new children"""
        basic_categories = self.db.query(ActivityCategory) \
            .options(joinedload(ActivityCategory.items)) \
            .filter(ActivityCategory.difficulty_level == "easy") \
            .limit(3) \
            .all()

        next_activities = []
        for c in basic_categories:
            next_activities.append({
                "category": c.name,
                "items": [i.name for i in c.items[:3]]  # Now this works
            })

        return {
            "practice_more": [],
            "next_activities": next_activities,
            "progress_tracking": "New learner - starting with basic activities",
            "encouragement": "Let's get started with some fun activities!"
        }

    def _suggest_next_activities(self, weak_categories: List[str]) -> List[Dict]:
        """Suggest activities for weak categories"""
        suggestions = []
        for category_name in weak_categories[:3]:
            category = self.db.query(ActivityCategory) \
                .filter(ActivityCategory.name == category_name) \
                .first()

            if category:
                items = self.db.query(ActivityItem) \
                    .filter(
                    ActivityItem.category_id == category.id,
                    ActivityItem.difficulty_level == self._get_recommended_difficulty(category)
                ) \
                    .limit(5) \
                    .all()

                suggestions.append({
                    "category": category.name,
                    "items": [item.name for item in items]
                })

        return suggestions

    def _generate_progress_report(self, performances: List[ChildPerformance]) -> Dict:
        """Generate progress metrics"""
        avg_score = sum(p.overall_score for p in performances) / len(performances) if performances else 0
        best_category = max(performances, key=lambda p: p.overall_score).category.name if performances else "N/A"
        worst_category = min(performances, key=lambda p: p.overall_score).category.name if performances else "N/A"

        return {
            "average_score": avg_score,
            "strongest_category": best_category,
            "weakest_category": worst_category
        }

    def _generate_encouragement(self, strong_categories: List[str]) -> str:
        """Generate encouraging feedback"""
        if not strong_categories:
            return "Keep practicing! You're making progress."
        return f"Great work on {', '.join(strong_categories[:3])}! Let's build on this success."