import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ChildCategoryDisplay(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    difficulty_level: str
    item_count: int
    total_attempts: int
    latest_performance: Optional[float]  # Percentage (0-100)
    last_attempt_date: Optional[datetime]
    child_interest_order: int  # Order of preference for this child

    class Config:
        from_attributes = True