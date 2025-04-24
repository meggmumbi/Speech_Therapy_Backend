from sqlalchemy import Column, ForeignKey, Boolean, Integer, Float, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime
from app.database import Base


class SessionActivity(Base):
    __tablename__ = "session_activities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID, ForeignKey("therapy_sessions.id"))
    item_id = Column(UUID, ForeignKey("activity_items.id"))
    attempt_number = Column(Integer, default=1)
    is_correct = Column(Boolean)
    response_type = Column(String(10))  # 'verbal' or 'select'
    pronunciation_score = Column(Float)
    response_time_seconds = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)