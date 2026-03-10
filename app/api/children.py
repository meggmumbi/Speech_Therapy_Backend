import os
from datetime import datetime

import openai
from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
from sqlalchemy import case
from sqlalchemy.orm import Session
from .. import models, schemas
from ..database import get_db
from typing import List, Dict, Any, Optional
import uuid

from ..models import Caregiver, Child, TherapySession, ActivityCategory, ChildPerformance, ActivityItem, \
    CaregiverFeedback
from ..models.LearningPath import LearningPath
from ..schemas import ChatGPTRecommendationResponse
from ..schemas.personalization import LearningPathSchema
from ..services.personalization import PersonalizationEngine

from ..services.recommendation_engine import RecommendationEngine
from ..utils.auth import get_current_user

router = APIRouter()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")   # ✅ Correct way
)

@router.get("/", response_model=List[schemas.Child])
def list_children(db: Session = Depends(get_db),current_user: Caregiver = Depends(get_current_user)):
    children = db.query(models.Child).filter(
        models.Child.caregiver_id == current_user.id
    ).all()
    return children


@router.post("/", response_model=schemas.Child)
def create_child(
        child: schemas.ChildCreate,
        db: Session = Depends(get_db),
        current_user: models.Caregiver = Depends(get_current_user)
):
    # Create the child object without the areas_of_interest_ids
    child_data = child.dict(exclude={"areas_of_interest_ids"})
    db_child = models.Child(**child_data,caregiver_id=current_user.id)
    db.add(db_child)

    # Get the selected categories
    if child.areas_of_interest_ids:
        categories = db.query(models.ActivityCategory).filter(
            models.ActivityCategory.id.in_(child.areas_of_interest_ids)
        ).all()
        db_child.areas_of_interest = categories

    db.commit()
    db.refresh(db_child)
    return db_child


@router.get("/{child_id}", response_model=schemas.Child)
def get_child(child_id: uuid.UUID, db: Session = Depends(get_db)):
    child = db.query(models.Child).filter(models.Child.id == child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    return child


@router.put("/{child_id}", response_model=schemas.Child)
def update_child(
        child_id: uuid.UUID,
        child_data: schemas.ChildCreate,
        db: Session = Depends(get_db),
        current_user: models.Caregiver = Depends(get_current_user)
):
    # Get the child from database
    child = db.query(models.Child).filter(models.Child.id == child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    # Update basic fields (excluding areas_of_interest_ids)
    update_data = child_data.dict(exclude={"areas_of_interest_ids"})
    for key, value in update_data.items():
        setattr(child, key, value)

    # Handle areas of interest update if provided
    if child_data.areas_of_interest_ids is not None:
        # Clear existing relationships
        child.areas_of_interest = []

        # Add new relationships if IDs are provided
        if child_data.areas_of_interest_ids:
            categories = db.query(models.ActivityCategory).filter(
                models.ActivityCategory.id.in_(child_data.areas_of_interest_ids)
            ).all()
            child.areas_of_interest = categories

    db.commit()
    db.refresh(child)
    return child

@router.delete("/{child_id}", status_code=204)
def delete_child(child_id: uuid.UUID, db: Session = Depends(get_db), current_user: Caregiver = Depends(get_current_user)):
    child = db.query(models.Child).filter(models.Child.id == child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    db.delete(child)
    db.commit()
    return None


@router.get("/{child_id}/similar")
def find_similar_children(child_id: uuid.UUID, db: Session = Depends(get_db)):
    engine = RecommendationEngine(db)
    return engine.find_similar_children(child_id)

@router.get("/{child_id}/activities")
def recommend_activities(
    child_id: uuid.UUID,
    category_id: uuid.UUID = None,
    db: Session = Depends(get_db)
):
    engine = RecommendationEngine(db)
    return engine.recommend_activities(child_id, category_id)


@router.get("/{child_id}/learning-path", response_model=LearningPathSchema)
def get_learning_path(child_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get or generate personalized learning path for a child"""
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    # Generate the path items
    path_items = generate_learning_path_items(child_id, db)

    # Get category names
    category_ids = [str(item['category_id']) for item in path_items]
    categories = db.query(ActivityCategory).filter(
        ActivityCategory.id.in_(category_ids)
    ).all()
    category_map = {str(cat.id): cat.name for cat in categories}

    # Format items with category names
    formatted_items = []
    for item in path_items:
        formatted_items.append({
            "category_id": item['category_id'],
            "category_name": category_map.get(str(item['category_id']), "Unknown"),
            "reason": item['reason'],
            "target_score": item['target_score'],
            "priority": item.get('priority', 0),
            "status": item.get('status', 'pending'),
            "current_score": 0.0  # Will be populated from performance data
        })

    # Create the proper response structure
    return {
        "child_id": child_id,
        "paths": formatted_items,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }


def generate_learning_path_items(child_id: uuid.UUID, db: Session):
    """Generate the raw path items without schema formatting"""
    engine = PersonalizationEngine(db)
    profile = engine.analyze_child_profile(child_id)

    categories = db.query(ActivityCategory).order_by(
        case(
            (ActivityCategory.difficulty_level == 'easy', 1),
            (ActivityCategory.difficulty_level == 'medium', 2),
            (ActivityCategory.difficulty_level == 'hard', 3),
            else_=4
        )
    ).all()

    learning_path = []
    priority = 1

    # 1. Start with strengths
    for cat in categories:
        if str(cat.id) in profile['strengths']:
            learning_path.append({
                'category_id': cat.id,
                'reason': 'strength',
                'target_score': 0.9,
                'priority': priority,
                'status': 'pending'
            })
            priority += 1

    # 2. Add new categories at recommended level
    for cat in categories:
        if str(cat.id) not in profile['strengths'] + profile['challenges']:
            if cat.difficulty_level == profile['recommended_level']:
                learning_path.append({
                    'category_id': cat.id,
                    'reason': 'new_at_level',
                    'target_score': 0.7,
                    'priority': priority,
                    'status': 'pending'
                })
                priority += 1

    # 3. Address challenges
    for cat in categories:
        if str(cat.id) in profile['challenges']:
            learning_path.append({
                'category_id': cat.id,
                'reason': 'challenge',
                'target_score': 0.5,
                'priority': priority,
                'status': 'pending'
            })
            priority += 1

    return learning_path



@router.post("/{child_id}/update-path")
def update_path(child_id: uuid.UUID, db: Session = Depends(get_db)):
    """Update learning path based on latest progress"""
    child = db.query(Child).get(child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    engine = PersonalizationEngine(db)
    return engine.update_learning_path(child_id)


@router.get("/children/{child_id}/recommendations", response_model=ChatGPTRecommendationResponse)
async def get_child_recommendations(
        child_id: str,
        db: Session = Depends(get_db)
):
    try:
        # Get child data
        child = db.query(Child).filter(Child.id == child_id).first()
        if not child:
            raise HTTPException(status_code=404, detail="Child not found")

        child_data = {
            "name": child.name,
            "age": child.age,
            "therapy_goals": child.therapy_goals,
            "notes": child.notes
        }

        # Get performance data with categories and items
        performances = db.query(ChildPerformance).filter(ChildPerformance.child_id == child_id).all()
        performance_data = []

        for perf in performances:
            category = db.query(ActivityCategory).filter(ActivityCategory.id == perf.category_id).first()
            items = db.query(ActivityItem).filter(ActivityItem.category_id == perf.category_id).all()

            performance_data.append({
                "name": category.name,
                "overall_score": perf.overall_score,
                "last_updated": perf.last_updated.isoformat(),
                "items": [{
                    "name": item.name,
                    "difficulty_level": item.difficulty_level or category.difficulty_level
                } for item in items]
            })

            # Get latest therapy session
            latest_session = db.query(TherapySession) \
                .filter(TherapySession.child_id == child_id) \
                .order_by(TherapySession.start_time.desc()) \
                .first()

            feedback_data = None
            if latest_session:
                # Get feedback for this session if it exists
                feedback = db.query(CaregiverFeedback) \
                    .filter(CaregiverFeedback.session_id == latest_session.id) \
                    .first()

                if feedback:
                    feedback_data = {
                        "rating": feedback.rating,
                        "comments": feedback.comments or "",
                        "progress_achievements": feedback.progress_achievements or "",
                        "areas_for_improvement": feedback.areas_for_improvement or "",
                        "behavioral_observations": feedback.behavioral_observations or ""
                    }


        # Generate ChatGPT prompt
        prompt = generate_chatgpt_prompt(child_data, performance_data, feedback_data)

        print(prompt)
        # Call ChatGPT API
        response = client.responses.create(
            model="gpt-3.5-turbo",
            input=[
                {"role": "system",
                 "content": "You are a helpful therapy assistant that provides recommendations for children with ASD. "},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        print(response.output_text)
        # Parse the response
        recommendations = response.output_text

        return {
            "child_id": child_id,
            "child_name": child.name,
            "recommendations": recommendations,
            "prompt_used": prompt,
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating recommendations: {str(e)}")


def generate_chatgpt_prompt(
        child_data: Dict[str, Any],
        performance_data: List[Dict[str, Any]],
        feedback_data: Optional[Dict[str, Any]] = None
) -> str:
    """Generate the ChatGPT prompt from the collected data"""
    prompt = f"""
Given the following Data from a therapy session for a child with ASD Using Pepper robot tablet during a speech therapy session where we are using visual aids with pictures for the item categories.
**Child Information:**
- Name: {child_data['name']}
- Age: {child_data['age']}
- Therapy Goals: {child_data['therapy_goals']}
- Notes: {child_data['notes']}

**Latest Performance Data:**
"""

    for category in performance_data:
        prompt += f"""
1. **Category Name**: {category['name']}
   - **Overall Score**: {category['overall_score']}%
   - **Last Updated**: {category['last_updated']}
   - **Items in Category**: 
"""
        for item in category['items']:
            prompt += f"     - {item['name']} (Difficulty: {item['difficulty_level']})\n"

    if feedback_data:
        prompt += f"""
**Caregiver Feedback (from latest session):**
- **Rating**: {feedback_data['rating']}/5
- **Comments**: "{feedback_data['comments']}"
- **Progress Achievements**: "{feedback_data['progress_achievements']}"
- **Areas for Improvement**: "{feedback_data['areas_for_improvement']}"
- **Behavioral Observations**: "{feedback_data['behavioral_observations']}"
"""
    else:
        prompt += "\n**No caregiver feedback available for the latest session.**\n"

    prompt += """
**Request for Recommendations:**
Based on the above data, please provide:
1. **Focus Areas**: Identify 1-3 key areas where the child needs the most attention (the given categories or suggest other categories that can be created in order to practice more).
2. **Progress Insights**: Highlight notable progress or regressions.
3. **Recommendations**: Suggest specific activities or strategies to help meet therapy goals.
"""
    return prompt