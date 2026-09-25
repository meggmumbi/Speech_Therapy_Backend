from sqlalchemy import Column, String, Boolean
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.database import Base


class Caregiver(Base):
    __tablename__ = "caregivers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True)
    # researcher | rater. A rater can listen and judge, and see nothing else:
    # no participants, no dashboard, no stimuli. Raters are external people
    # and must see none of the study apart from the clips they are judging.
    role = Column(String(12), default="researcher")