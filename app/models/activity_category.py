from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.database import Base


class ActivityCategory(Base):
    __tablename__ = "activity_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(200))
    difficulty_level = Column(String(20))  # 'easy', 'medium', 'hard'