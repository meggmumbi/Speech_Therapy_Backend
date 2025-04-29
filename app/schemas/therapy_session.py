from pydantic import BaseModel
from typing import Optional, List
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


class SessionActivityOverview(BaseModel):
    item_name: str
    response_type: str
    is_correct: bool
    pronunciation_score: Optional[float]
    response_time: Optional[float]
    feedback: Optional[str]


class SessionOverview(BaseModel):
    session_id: uuid.UUID
    child_name: str
    category_name: str
    start_time: datetime
    duration_minutes: float
    total_activities: int
    correct_answers: int
    accuracy_percentage: float
    average_response_time: float
    activities: List[SessionActivityOverview]
    strengths: List[str]
    areas_for_improvement: List[str]
    recommendations: List[str]

    class Config:
        from_attributes = True