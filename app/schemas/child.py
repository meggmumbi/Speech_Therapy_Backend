from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date
import uuid




class ChildBase(BaseModel):
    name: str
    age: Optional[int] = None
    diagnosis_date: Optional[date] = None
    notes: Optional[str] = None
    therapy_goals: Optional[str] = None

class ChildCreate(ChildBase):
    areas_of_interest_ids: List[uuid.UUID] = list

class ActivityCategory(BaseModel):
    id: uuid.UUID
    name: str

    class Config:
        from_attributes = True

class Child(ChildBase):
    id: uuid.UUID
    created_at: date
    areas_of_interest: List[ActivityCategory] = list

    class Config:
        from_attributes = True