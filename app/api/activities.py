from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import uuid
from datetime import datetime

from .. import models
from ..schemas import (
    activity_category,
    activity_item,
    therapy_session
)
from ..schemas.session_activity import SessionActivityCreate
from ..database import get_db
from ..utils.openai_utils import generate_image, generate_pronunciation_audio
from ..utils.auth import get_current_user


router = APIRouter(tags=["activities"])  # Add tags parameter


# Activity Categories CRUD
@router.post("/categories/", response_model=activity_category.ActivityCategory)
async def create_category(
        category: activity_category.ActivityCategoryCreate,
        db: Session = Depends(get_db)
):
    db_category = models.ActivityCategory(**category.dict())
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category


@router.get("/categories/", response_model=List[activity_category.ActivityCategory])
def list_categories(db: Session = Depends(get_db)):
    return db.query(models.ActivityCategory).all()


# Activity Items CRUD
@router.post("/items/", response_model=activity_item.ActivityItem)
async def create_item(
        item: activity_item.ActivityItemCreate,
        db: Session = Depends(get_db)
):
    # Create base item
    db_item = models.ActivityItem(**item.dict(exclude={"generate_image"}))

    # Generate image if requested
    if item.generate_image:
        db_item.image_url = await generate_image(item.name)
        db_item.audio_url = await generate_pronunciation_audio(item.name)

    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


@router.get("/categories/{category_id}/items", response_model=List[activity_item.ActivityItem])
def list_items_in_category(category_id: uuid.UUID, db: Session = Depends(get_db)):
    return db.query(models.ActivityItem).filter(
        models.ActivityItem.category_id == category_id
    ).all()


# Therapy Session Endpoints
@router.post("/sessions/", response_model=therapy_session.TherapySession)
async def start_session(
        session: therapy_session.TherapySessionCreate,
        db: Session = Depends(get_db),
        current_user: models.Caregiver = Depends(get_current_user)
):
    # Verify child exists
    child = db.query(models.Child).filter(models.Child.id == session.child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    # Verify category exists
    category = db.query(models.ActivityCategory).filter(
        models.ActivityCategory.id == session.category_id
    ).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    # Create new session
    db_session = models.TherapySession(
        **session.dict(),
        caregiver_id=current_user.id
    )
    db.add(db_session)
    db.commit()
    db.refresh(db_session)

    return db_session


@router.get("/sessions/{session_id}/next-item")
async def get_next_item(
        session_id: uuid.UUID,
        db: Session = Depends(get_db)
):
    # Get the session
    session = db.query(models.TherapySession).filter(
        models.TherapySession.id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get all items in this category at current difficulty level
    items = db.query(models.ActivityItem).filter(
        models.ActivityItem.category_id == session.category_id,
        models.ActivityItem.difficulty_level == session.current_level
    ).all()

    # Get items already attempted in this session
    attempted_items = db.query(models.SessionActivity.item_id).filter(
        models.SessionActivity.session_id == session_id
    ).all()
    attempted_ids = [item[0] for item in attempted_items]

    # Find next unattempted item
    next_item = next((item for item in items if item.id not in attempted_ids), None)

    if not next_item:
        # No more items - mark session as completed
        session.is_completed = True
        session.end_time = datetime.utcnow()
        db.commit()
        return {"status": "completed", "message": "All items in this category completed"}

    return {
        "item_id": next_item.id,
        "name": next_item.name,
        "image_url": next_item.image_url,
        "audio_url": next_item.audio_url
    }


@router.post("/sessions/{session_id}/record-response")
async def record_response(
        session_id: uuid.UUID,
        response: SessionActivityCreate,
        db: Session = Depends(get_db)
):
    # Verify session exists
    session = db.query(models.TherapySession).filter(
        models.TherapySession.id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Verify item exists
    item = db.query(models.ActivityItem).filter(
        models.ActivityItem.id == response.item_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Record the response
    db_response = models.SessionActivity(
        **response.dict(),
        session_id=session_id
    )
    db.add(db_response)
    db.commit()
    db.refresh(db_response)

    return {"status": "success", "activity_id": db_response.id}