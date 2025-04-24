from datetime import datetime

from pydantic import BaseModel
from typing import Optional
import uuid


class SessionActivityBase(BaseModel):
    item_id: uuid.UUID
    is_correct: bool
    response_type: str  # 'verbal' or 'select'
    pronunciation_score: Optional[float] = None
    response_time_seconds: Optional[float] = None


class SessionActivityCreate(SessionActivityBase):
    pass


class SessionActivity(SessionActivityBase):
    id: uuid.UUID
    session_id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True