from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.database import Base


class ActivityItem(Base):
    __tablename__ = "activity_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), nullable=False)
    category_id = Column(UUID, ForeignKey("activity_categories.id"))
    image_url = Column(String(300))  # Will store OpenAI DALL-E generated image URL
    audio_url = Column(String(300))  # For pronunciation examples
    difficulty_level = Column(String(20))  # Can override category level