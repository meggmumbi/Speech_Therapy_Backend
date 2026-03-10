from sqlalchemy import Column, ForeignKey, Boolean, Integer, Float, String, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from sqlalchemy.orm import relationship

from app.database import Base


class SessionActivity(Base):
    __tablename__ = "session_activities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID, ForeignKey("therapy_sessions.id"))
    item_id = Column(UUID, ForeignKey("activity_items.id"))
    attempt_number = Column(Integer, default=1)
    is_correct = Column(Boolean)
    response_type = Column(String(10))  # 'verbal' or 'select'
    response_text = Column(String)
    feedback = Column(String)
    pronunciation_score = Column(Float)
    response_time_seconds = Column(Float)
    # Enhanced error tracking for sentences
    error_type = Column(String(20))  # 'repetition', 'stammering', 'substitution', 'sentence_errors', 'correct'
    substitutions = Column(JSON)  # Store specific sound substitutions
    repetition_count = Column(Integer, default=0)
    stammering_detected = Column(Boolean, default=False)
    # New fields for sentence analysis
    word_analysis = Column(JSON)  # Store per-word analysis
    correct_word_count = Column(Integer, default=0)
    total_word_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    session = relationship("TherapySession", back_populates="activities")
    item = relationship("ActivityItem")