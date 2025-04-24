from pydantic import BaseModel, Field, conint
from typing import Optional
import uuid
from datetime import datetime


class FeedbackBase(BaseModel):
    child_id: uuid.UUID
    rating: conint(ge=1, le=5)  # Rating between 1-5
    comments: Optional[str] = None


class FeedbackCreate(FeedbackBase):
    pass


class Feedback(FeedbackBase):
    id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    feedback_type: str
    created_at: datetime

    class Config:
        from_attributes = True  # Replaces 'orm_mode = True' in Pydantic v2