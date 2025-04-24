from pydantic import BaseModel
from typing import Optional
import uuid


class ActivityCategoryBase(BaseModel):
    name: str
    description: Optional[str] = None
    difficulty_level: str  # 'easy', 'medium', 'hard'


class ActivityCategoryCreate(ActivityCategoryBase):
    pass


class ActivityCategory(ActivityCategoryBase):
    id: uuid.UUID

    class Config:
        from_attributes = True