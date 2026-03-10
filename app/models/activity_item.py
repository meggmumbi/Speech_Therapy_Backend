from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid

from sqlalchemy.orm import relationship

from app.database import Base


class ActivityItem(Base):
    __tablename__ = "activity_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(300), nullable=False)
    description = Column(String(300), nullable=True)
    category_id = Column(UUID, ForeignKey("activity_categories.id"))
    image_url = Column(String(300))
    audio_url = Column(String(300))
    difficulty_level = Column(String(20))

    category = relationship("ActivityCategory", back_populates="items")