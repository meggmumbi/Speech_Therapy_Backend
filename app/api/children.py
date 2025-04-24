from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .. import models, schemas
from ..database import get_db
from typing import List
import uuid

router = APIRouter()


@router.get("/", response_model=List[schemas.Child])
def list_children(db: Session = Depends(get_db)):
    children = db.query(models.Child).all()
    return children


@router.post("/", response_model=schemas.Child)
def create_child(child: schemas.ChildCreate, db: Session = Depends(get_db)):
    db_child = models.Child(**child.dict())
    db.add(db_child)
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
def update_child(child_id: uuid.UUID, child_data: schemas.ChildCreate, db: Session = Depends(get_db)):
    child = db.query(models.Child).filter(models.Child.id == child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    for key, value in child_data.dict().items():
        setattr(child, key, value)

    db.commit()
    db.refresh(child)
    return child