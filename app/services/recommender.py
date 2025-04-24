from typing import Dict  # Add this import for Dict
from sqlalchemy.orm import Session  # Add this import for Session
import uuid
from ..models import ChildPerformance, TherapySession, ActivityCategory, ActivityItem
from ..ml.recommendation_model import RecommendationModel


class Recommender:
    def __init__(self, db: Session):  # Session type now recognized
        self.db = db
        self.ml_model = RecommendationModel()

    def get_recommendations(self, child_id: uuid.UUID) -> Dict:  # Dict type now recognized
        # Get performance data
        child_data = self._prepare_ml_input(child_id)

        # Get ML recommendation
        ml_recommendation = self.ml_model.predict(child_data)

        # Combine with rule-based recommendations
        return {
            **self._get_rule_based_recommendations(child_id),
            "ml_recommendation": ml_recommendation,
            "confidence_score": self._get_confidence_score(child_data)
        }

    def _prepare_ml_input(self, child_id: uuid.UUID) -> Dict[str, float]:  # Explicit dict type
        """Prepare child data for ML model input"""
        performances = self.db.query(ChildPerformance).filter(
            ChildPerformance.child_id == child_id
        ).all()

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

        categories = self.db.query(ActivityCategory).join(
            TherapySession,
            TherapySession.category_id == ActivityCategory.id
        ).filter(
            TherapySession.child_id == child_id
        ).all()

        if not categories:
            return 1.0  # Default to easy if no sessions

        avg_score = sum(difficulties.get(c.difficulty_level, 1) for c in categories) / len(categories)
        return avg_score

    def _get_average_session_time(self, child_id: uuid.UUID) -> float:
        """Calculate average session time in minutes"""
        sessions = self.db.query(TherapySession).filter(
            TherapySession.child_id == child_id,
            TherapySession.end_time.isnot(None)
        ).all()

        if not sessions:
            return 0.0

        total_seconds = sum(
            (s.end_time - s.start_time).total_seconds()
            for s in sessions
        )
        return total_seconds / len(sessions) / 60

    def _get_confidence_score(self, child_data: Dict[str, float]) -> float:
        """Calculate confidence score for recommendations"""
        # Simple implementation - can be enhanced with ML
        verbal_weight = 0.6
        selection_weight = 0.4

        return (
                child_data['verbal_accuracy'] * verbal_weight +
                child_data['selection_accuracy'] * selection_weight
        )