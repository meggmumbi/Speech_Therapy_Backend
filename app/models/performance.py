from sqlalchemy import Column, Float, ForeignKey, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime
from app.database import Base


class ChildPerformance(Base):
    __tablename__ = "child_performance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    child_id = Column(UUID, ForeignKey("children.id"), nullable=False)
    category_id = Column(UUID, ForeignKey("activity_categories.id"))
    overall_score = Column(Float, default=0.0)
    verbal_attempts = Column(Integer, default=0)
    verbal_success = Column(Integer, default=0)
    selection_attempts = Column(Integer, default=0)
    selection_success = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)