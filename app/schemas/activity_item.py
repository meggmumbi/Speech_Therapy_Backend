from pydantic import BaseModel
from typing import Optional
import uuid


class ActivityItemBase(BaseModel):
    name: str
    category_id: uuid.UUID
    difficulty_level: Optional[str] = None


class ActivityItemCreate(ActivityItemBase):
    generate_image: bool = True  # Flag to generate image with DALL-E


class ActivityItem(ActivityItemBase):
    id: uuid.UUID
    image_url: Optional[str] = None
    audio_url: Optional[str] = None

    class Config:
        from_attributes = True