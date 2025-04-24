from pydantic import BaseModel
from typing import Optional
import uuid
from datetime import datetime


class TherapySessionBase(BaseModel):
    child_id: uuid.UUID
    category_id: uuid.UUID
    current_level: str


class TherapySessionCreate(TherapySessionBase):
    pass


class TherapySession(TherapySessionBase):
    id: uuid.UUID
    caregiver_id: Optional[uuid.UUID] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    is_completed: bool = False

    class Config:
        from_attributes = True