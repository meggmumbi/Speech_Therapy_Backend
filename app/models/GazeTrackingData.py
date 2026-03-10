import uuid
from datetime import datetime

from sqlalchemy import Column, Integer, ForeignKey, BigInteger, Float, DateTime, UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.models import TherapySession


class GazeTrackingData(Base):
    __tablename__ = "gaze_tracking_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID, ForeignKey('therapy_sessions.id'), nullable=False)
    child_id = Column(UUID, ForeignKey('children.id'), nullable=False)

    # Session metrics
    session_duration_ms = Column(BigInteger, nullable=False)
    total_attention_time_ms = Column(BigInteger, nullable=False)
    attention_percentage = Column(Float, nullable=False)

    # Zone metrics
    time_in_zone1_ms = Column(BigInteger, nullable=False)
    time_in_zone2_ms = Column(BigInteger, nullable=False)
    time_in_zone3_ms = Column(BigInteger, nullable=False)
    zone1_percentage = Column(Float, nullable=False)
    zone2_percentage = Column(Float, nullable=False)
    zone3_percentage = Column(Float, nullable=False)

    # Emotion metrics
    average_pleasure = Column(Float, nullable=False)
    average_excitement = Column(Float, nullable=False)
    engagement_percentage = Column(Float, nullable=False)
    smile_percentage = Column(Float, nullable=False)

    # Additional data
    total_gaze_data_points = Column(Integer, nullable=False)
    session_start_time = Column(BigInteger, nullable=False)
    session_end_time = Column(BigInteger, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    session = relationship("TherapySession", back_populates="gaze_tracking_data")
    child = relationship("Child")


# Add relationship to TherapySession model
TherapySession.gaze_tracking_data = relationship("GazeTrackingData", back_populates="session")