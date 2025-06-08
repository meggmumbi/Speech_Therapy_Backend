from collections import Counter
from datetime import datetime
from typing import List, Union
from uuid import UUID

from sqlalchemy import case
from sqlalchemy.orm import Session

from app.models import ChildPerformance, TherapySession, ActivityCategory, ActivityItem, \
    SessionActivity
from app.models.LearningPath import LearningPath
from app.schemas.personalization import LearningPathSchema, AdaptationSchema, AdaptationRecommendation
from app.services.pronunciation_analysis import get_most_different_sound


class PersonalizationEngine:
    def __init__(self, db: Session):
        self.db = db

    def analyze_child_profile(self, child_id: UUID):
        """
        Analyze child's performance data to create a baseline profile
        Returns a dict with strengths, challenges, and recommended starting level
        """
        # Get all performance records for this child
        performances = self.db.query(ChildPerformance).filter(
            ChildPerformance.child_id == child_id
        ).all()

        # Get all session activities
        activities = self.db.query(SessionActivity).join(TherapySession).filter(
            TherapySession.child_id == child_id
        ).all()

        profile = {
            'strengths': [],
            'challenges': [],
            'recommended_level': 'easy',
            'preferred_modality': None,
            'communication_style': {}
        }

        if not performances and not activities:
            return profile  # New child with no data

        # Calculate success rates by category and modality
        verbal_success = 0
        verbal_total = 0
        selection_success = 0
        selection_total = 0
        category_scores = {}

        for perf in performances:
            category_scores[perf.category_id] = perf.overall_score

            # Determine strengths and challenges
            if perf.overall_score >= 0.7:  # 70% success rate
                profile['strengths'].append(str(perf.category_id))
            elif perf.overall_score <= 0.3:
                profile['challenges'].append(str(perf.category_id))

        for act in activities:
            if act.response_type == 'verbal':
                verbal_total += 1
                if act.is_correct:
                    verbal_success += 1
            elif act.response_type == 'nonverbal':
                selection_total += 1
                if act.is_correct:
                    selection_success += 1

        # Determine preferred modality
        if verbal_total > 0 and selection_total > 0:
            verbal_rate = verbal_success / verbal_total
            selection_rate = selection_success / selection_total
            profile['preferred_modality'] = 'verbal' if verbal_rate > selection_rate else 'nonverbal'

        # Determine recommended difficulty level
        avg_score = sum([p.overall_score for p in performances]) / len(performances) if performances else 0
        if avg_score > 0.75:
            profile['recommended_level'] = 'hard'
        elif avg_score > 0.5:
            profile['recommended_level'] = 'medium'

        return profile

    def generate_learning_path(self, child_id: UUID):
        """
        Generate a personalized learning path based on child's profile
        Returns an ordered list of activity categories with progression logic
        """
        profile = self.analyze_child_profile(child_id)

        # Get all available activity categories ordered by base difficulty
        categories = self.db.query(ActivityCategory).order_by(
            case(
                (ActivityCategory.difficulty_level == 'easy', 1),
                (ActivityCategory.difficulty_level == 'medium', 2),
                (ActivityCategory.difficulty_level == 'hard', 3),
                else_=4
            )
        ).all()

        # Reorder based on child's profile
        learning_path = []

        # 1. Start with strengths to build confidence
        for cat in categories:
            if str(cat.id) in profile['strengths']:
                learning_path.append({
                    'category_id': cat.id,
                    'reason': 'strength',
                    'target_score': 0.9  # Aim for mastery
                })

        # 2. Add new categories at recommended difficulty level
        for cat in categories:
            if str(cat.id) not in profile['strengths'] + profile['challenges']:
                if cat.difficulty_level == profile['recommended_level']:
                    learning_path.append({
                        'category_id': cat.id,
                        'reason': 'new_at_level',
                        'target_score': 0.7
                    })

        # 3. Address challenges with extra support
        for cat in categories:
            if str(cat.id) in profile['challenges']:
                learning_path.append({
                    'category_id': cat.id,
                    'reason': 'challenge',
                    'target_score': 0.5,
                    'support': 'visual_aids' if profile['preferred_modality'] == 'select' else 'verbal_prompts'
                })

        return learning_path

    # def get_recommended_action(self, milestone: LearningPathMilestone, performance_score: float):
    #     """
    #     Determine recommended action for a milestone
    #     """
    #     if milestone.status == "mastered":
    #         return "maintain"
    #     elif milestone.status == "in_progress":
    #         if performance_score >= 0.7:
    #             return "practice_more"
    #         else:
    #             return "provide_support"
    #     else:
    #         if performance_score == 0:
    #             return "introduce"
    #         else:
    #             return "reintroduce"

    def select_next_activity(self, session: TherapySession):
        """
        Select the next activity item adaptively based on:
        - Current session progress
        - Child's performance history
        - Learning path goals
        """
        # Get current category
        current_category = session.category

        # Get child's performance in this category
        child_perf = self.db.query(ChildPerformance).filter(
            ChildPerformance.child_id == session.child_id,
            ChildPerformance.category_id == current_category.id
        ).first()

        # Get all items in this category
        items = self.db.query(ActivityItem).filter(
            ActivityItem.category_id == current_category.id
        ).all()

        if not items:
            return None

        # If new to category, start with easiest items
        if not child_perf or child_perf.overall_score < 0.1:
            return sorted(items, key=lambda x: x.difficulty_level or current_category.difficulty_level)[0]

        # Filter items based on current performance
        if child_perf.overall_score < 0.4:
            # Struggling - simplify
            candidates = [i for i in items if (
                    i.difficulty_level == 'easy' or
                    (i.difficulty_level is None and current_category.difficulty_level == 'easy')
            )]
            if not candidates:
                candidates = items[:3]  # fallback
        elif child_perf.overall_score > 0.8:
            # Excelling - challenge
            candidates = [i for i in items if (
                    i.difficulty_level == 'hard' or
                    (i.difficulty_level is None and current_category.difficulty_level == 'hard')
            )]
            if not candidates:
                candidates = items[-3:]  # fallback
        else:
            # On track - maintain
            candidates = [i for i in items if (
                    i.difficulty_level == 'medium' or
                    (i.difficulty_level is None and current_category.difficulty_level == 'medium')
            )]
            if not candidates:
                candidates = items[3:-3] if len(items) > 6 else items

        # Avoid recently used items
        recent_items = self.db.query(SessionActivity.item_id).filter(
            SessionActivity.session_id == session.id
        ).all()
        recent_ids = {str(i[0]) for i in recent_items}

        filtered_candidates = [i for i in candidates if str(i.id) not in recent_ids]
        candidates = filtered_candidates if filtered_candidates else candidates

        # Select based on preferred modality if known
        profile = self.analyze_child_profile(session.child_id)
        if profile['preferred_modality']:
            if profile['preferred_modality'] == 'verbal':
                candidates.sort(key=lambda x: (x.audio_url is not None, x.difficulty_level))
            else:
                candidates.sort(key=lambda x: (x.image_url is not None, x.difficulty_level))

        return candidates[0] if candidates else None

    # def select_next_category(self, child_id: UUID):
    #     """
    #     Select the next category when starting new learning path
    #     """
    #     path = self.get_current_learning_path(child_id)
    #
    #     # Get first not-started milestone
    #     milestone = self.db.query(LearningPathMilestone).filter(
    #         LearningPathMilestone.path_id == path.id,
    #         LearningPathMilestone.status == "not_started"
    #     ).order_by(
    #         case(
    #             (ActivityCategory.difficulty_level == 'easy', 1),
    #             (ActivityCategory.difficulty_level == 'medium', 2),
    #             (ActivityCategory.difficulty_level == 'hard', 3),
    #             else_=4
    #         )
    #     ).first()
    #
    #     if milestone:
    #         path.current_category_id = milestone.category_id
    #         path.current_stage = "item_practice"
    #         self.db.commit()
    #         return milestone.category
    #
    #     return None

    def adapt_session(self, session_id: UUID):
        """Adjust the current session based on real-time performance"""
        session = self.db.query(TherapySession).get(session_id)
        if not session:
            return None

        activities = self.db.query(SessionActivity).filter(
            SessionActivity.session_id == session_id
        ).order_by(SessionActivity.created_at.desc()).limit(5).all()

        if not activities:
            return AdaptationSchema(
                recommendations=[],
                session_id=session_id,
                generated_at=datetime.utcnow()
            )

        recent_correct = sum(1 for a in activities if a.is_correct)
        recent_performance = recent_correct / len(activities)

        recommendations = []

        if recent_performance < 0.3:
            recommendations.append(AdaptationRecommendation(
                action='simplify',
                difficulty_adjustment=-1,
                feedback='Child is struggling. Try simplifying the activity.'
            ))
        elif recent_performance > 0.8:
            recommendations.append(AdaptationRecommendation(
                action='challenge',
                difficulty_adjustment=1,
                feedback='Child is excelling. Consider increasing difficulty.'
            ))
        else:
            recommendations.append(AdaptationRecommendation(
                action='continue',
                feedback='Current approach is working well'
            ))

        error_analysis = self.analyze_errors(activities)
        if error_analysis:
            if 'phonetic' in error_analysis:
                recommendations.append(AdaptationRecommendation(
                    action='focus',
                    feedback=f"Focus on {error_analysis['phonetic']} sounds.",
                    error_patterns=error_analysis
                ))

        return AdaptationSchema(
            recommendations=recommendations,
            session_id=session_id,
            generated_at=datetime.utcnow()
        )

    def analyze_errors(self, activities: List[SessionActivity]):
        """
        Analyze error patterns across activities
        """
        errors = [a for a in activities if not a.is_correct]
        if not errors:
            return None

        analysis = {}

        # Phonetic error patterns
        phonetic_errors = []
        for a in errors:
            if a.response_type == 'verbal' and a.response_text:
                expected = a.item.name.lower()
                actual = a.response_text.lower()
                diff = get_most_different_sound(expected, actual)
                if diff:
                    phonetic_errors.append(diff)

        if phonetic_errors:
            common_phonetic = Counter(phonetic_errors).most_common(1)
            analysis['phonetic'] = common_phonetic[0][0]

        # Modality patterns
        verbal_errors = sum(1 for a in errors if a.response_type == 'verbal')
        select_errors = sum(1 for a in errors if a.response_type == 'nonverbal')

        if verbal_errors > select_errors * 2:
            analysis['modality'] = 'verbal_challenge'
        elif select_errors > verbal_errors * 2:
            analysis['modality'] = 'selection_challenge'

        return analysis

    def update_learning_path(self, child_id: UUID):
        """
        Re-evaluate and update the learning path based on latest performance
        """
        # Get current path (could be stored in a separate table)
        current_path = self.get_current_learning_path(child_id)

        # Get latest performance data
        performances = self.db.query(ChildPerformance).filter(
            ChildPerformance.child_id == child_id
        ).all()

        # Update target scores and progression
        for item in current_path:
            perf = next((p for p in performances if str(p.category_id) == str(item['category_id'])), None)
            if perf:
                # Adjust target based on progress
                if perf.overall_score > item['target_score'] * 0.9:
                    item['target_score'] = min(1.0, item['target_score'] + 0.1)
                elif perf.overall_score < item['target_score'] * 0.5:
                    item['target_score'] = max(0.3, item['target_score'] - 0.1)

        # Save updated path (implementation depends on your storage)
        self.save_learning_path(child_id, current_path)

        return current_path

    def get_current_learning_path(self, child_id: UUID):
        """Retrieve the current learning path for a child"""
        path_items = self.db.query(LearningPath).filter(
            LearningPath.child_id == child_id
        ).order_by(LearningPath.current_priority).all()

        if not path_items:
            # Generate new path if none exists
            return self.generate_learning_path(child_id)

        # Convert to schema format
        path_data = []
        for item in path_items:
            # Get current performance for this category
            perf = self.db.query(ChildPerformance).filter(
                ChildPerformance.child_id == child_id,
                ChildPerformance.category_id == item.category_id
            ).first()

            path_data.append({
                'category_id': item.category_id,
                'target_score': item.target_score,
                'current_priority': item.current_priority,
                'status': item.status,
                'current_score': perf.overall_score if perf else 0.0
            })

        return {
            'child_id': child_id,
            'paths': path_data,
            'created_at': path_items[0].created_at if path_items else datetime.utcnow(),
            'updated_at': path_items[0].updated_at if path_items else datetime.utcnow()
        }

    def save_learning_path(self, child_id: UUID, path_data: Union[dict, List[dict]]):
        """Save or update a learning path"""
        # First delete any existing path items for this child
        self.db.query(LearningPath).filter(
            LearningPath.child_id == child_id
        ).delete()

        # Normalize input - handle both dict with 'paths' key and direct list
        if isinstance(path_data, dict) and 'paths' in path_data:
            items = path_data['paths']
        elif isinstance(path_data, list):
            items = path_data
        else:
            raise ValueError("Invalid path_data format. Expected dict with 'paths' key or list of items")

        # Create new path items
        for item in items:
            path_item = LearningPath(
                child_id=child_id,
                category_id=item['category_id'],
                target_score=item['target_score'],
                current_priority=item.get('priority', 0),  # Use get with default
                status=item.get('status', 'pending'),  # Use get with default
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            self.db.add(path_item)

        self.db.commit()

    # def generate_initial_milestones(self, path: LearningPath):
    #     """
    #     Create initial milestones based on child's profile with personalized ordering
    #     and difficulty adjustments.
    #     """
    #     profile = self.analyze_child_profile(path.child_id)
    #     categories = self.db.query(ActivityCategory).all()
    #
    #     # Sort categories based on profile:
    #     # 1. Start with strengths (if any)
    #     # 2. Then recommended difficulty level
    #     # 3. Then remaining categories
    #     strength_categories = [cat for cat in categories
    #                            if str(cat.id) in profile.get('strengths', [])]
    #     recommended_categories = [cat for cat in categories
    #                               if cat.difficulty_level == profile.get('recommended_level', 'easy')
    #                               and cat not in strength_categories]
    #     other_categories = [cat for cat in categories
    #                         if cat not in strength_categories
    #                         and cat not in recommended_categories]
    #
    #     ordered_categories = strength_categories + recommended_categories + other_categories
    #
    #     for cat in ordered_categories:
    #         # Determine target skill based on category name
    #         target_skill = cat.name.lower().replace(" activities", "")
    #
    #         # Set initial status based on profile
    #         status = "not_started"
    #         if str(cat.id) in profile.get('strengths', []):
    #             status = "in_progress"  # Mark strengths as in progress to reinforce
    #
    #         milestone = LearningPathMilestone(
    #             path_id=path.id,
    #             category_id=cat.id,
    #             target_skill=target_skill,
    #             status=status,
    #             # Add support hints based on preferred modality
    #
    #         )
    #         self.db.add(milestone)
    #
    #     self.db.commit()