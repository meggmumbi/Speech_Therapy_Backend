from datetime import datetime
from typing import Optional
from pydantic import BaseModel
import uuid

class ChildCategoryDisplay(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    difficulty_level: str
    is_selected: bool
    item_count: int
    total_attempts: int
    latest_performance: Optional[float]
    last_attempt_date: Optional[datetime]
    child_interest_order: Optional[int]

    class Config:
        from_attributes = True