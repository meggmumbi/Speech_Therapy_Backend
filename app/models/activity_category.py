from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID
import uuid

from sqlalchemy.orm import relationship

from app.database import Base
from app.models.child import child_category_association


class ActivityCategory(Base):
    __tablename__ = "activity_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(200))
    type = Column(String(50))
    difficulty_level = Column(String(20))

    items = relationship(
        "ActivityItem",
        back_populates="category",
        cascade="all, delete-orphan"
    )

    children = relationship(
        "Child",
        secondary=child_category_association,
        back_populates="areas_of_interest"
    )