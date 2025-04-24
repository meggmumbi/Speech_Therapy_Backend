from pydantic import BaseModel
from typing import Optional
from datetime import date
import uuid


class ChildBase(BaseModel):
    name: str
    age: Optional[int] = None
    diagnosis_date: Optional[date] = None
    notes: Optional[str] = None


class ChildCreate(ChildBase):
    pass


class Child(ChildBase):
    id: uuid.UUID
    created_at: date

    class Config:
        from_attributes = True