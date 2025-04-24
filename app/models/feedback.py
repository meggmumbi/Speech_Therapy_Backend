from sqlalchemy import Column, Text, Integer, ForeignKey, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime
from app.database import Base


class CaregiverFeedback(Base):
    __tablename__ = "caregiver_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID, ForeignKey("therapy_sessions.id"))
    child_id = Column(UUID, ForeignKey("children.id"))
    rating = Column(Integer)  # 1-5 scale
    comments = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    feedback_type = Column(String(20))  # 'session', 'progress', 'recommendation'