from sqlalchemy import Column, Text, Integer, ForeignKey, DateTime, String, Float
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from sqlalchemy.orm import relationship

from app.database import Base


class LearningPath(Base):
    __tablename__ = "learning_paths"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    child_id = Column(UUID, ForeignKey("children.id"), nullable=False)
    category_id = Column(UUID, ForeignKey("activity_categories.id"), nullable=False)
    target_score = Column(Float, default=0.7)  # Target mastery score for this category
    current_priority = Column(Integer)  # Order in learning path (1=highest priority)
    status = Column(String(20), default='pending')  # 'pending', 'in-progress', 'mastered'
    started_at = Column(DateTime)
    mastered_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    child = relationship("Child", backref="learning_paths")
    category = relationship("ActivityCategory")


