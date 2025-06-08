from pydantic import BaseModel, Field, conint
from typing import Optional
import uuid
from datetime import datetime


class FeedbackBase(BaseModel):
    child_id: uuid.UUID
    rating: conint(ge=1, le=5)
    comments: Optional[str] = Field(None, description="General comments about the session")
    progress_achievements: Optional[str] = Field(
        None,
        description="Positive changes or milestones in communication/language"
    )
    areas_for_improvement: Optional[str] = Field(
        None,
        description="Specific challenges like articulation, vocabulary etc."
    )
    behavioral_observations: Optional[str] = Field(
        None,
        description="Notable behaviors during the session"
    )

class FeedbackCreate(FeedbackBase):
    pass

class Feedback(FeedbackBase):
    id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    feedback_type: str
    created_at: datetime

    class Config:
        from_attributes = True