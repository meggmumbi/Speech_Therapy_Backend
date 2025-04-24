from sqlalchemy import Column, DateTime, ForeignKey, String, Boolean
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime
from app.database import Base


class TherapySession(Base):
    __tablename__ = "therapy_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    child_id = Column(UUID, ForeignKey("children.id"))
    caregiver_id = Column(UUID, ForeignKey("caregivers.id"))
    category_id = Column(UUID, ForeignKey("activity_categories.id"))
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime)
    current_level = Column(String(20))
    is_completed = Column(Boolean, default=False)