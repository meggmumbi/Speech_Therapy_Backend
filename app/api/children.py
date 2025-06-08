from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case
from sqlalchemy.orm import Session
from .. import models, schemas
from ..database import get_db
from typing import List
import uuid

from ..models import Caregiver, Child, TherapySession, ActivityCategory
from ..models.LearningPath import LearningPath
from ..schemas.personalization import LearningPathSchema
from ..services.personalization import PersonalizationEngine

from ..services.recommendation_engine import RecommendationEngine
from ..utils.auth import get_current_user

router = APIRouter()


@router.get("/", response_model=List[schemas.Child])
def list_children(db: Session = Depends(get_db),current_user: Caregiver = Depends(get_current_user)):
    children = db.query(models.Child).all()
    return children


@router.post("/", response_model=schemas.Child)
def create_child(child: schemas.ChildCreate, db: Session = Depends(get_db),current_user: Caregiver = Depends(get_current_user)):
    db_child = models.Child(**child.dict())
    db.add(db_child)
    db.commit()
    db.refresh(db_child)
    return db_child


@router.get("/{child_id}", response_model=schemas.Child)
def get_child(child_id: uuid.UUID, db: Session = Depends(get_db),current_user: Caregiver = Depends(get_current_user)):
    child = db.query(models.Child).filter(models.Child.id == child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    return child


@router.put("/{child_id}", response_model=schemas.Child)
def update_child(child_id: uuid.UUID, child_data: schemas.ChildCreate, db: Session = Depends(get_db),current_user: Caregiver = Depends(get_current_user)):
    child = db.query(models.Child).filter(models.Child.id == child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    for key, value in child_data.dict().items():
        setattr(child, key, value)

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
