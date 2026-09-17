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

    # Which part of the study this category is: training list A, training list
    # B, the assessment set, or NULL for an ordinary practice category.
    #
    # This used to live in three environment variables on the server. A fact
    # about the experiment was being kept in deployment configuration that is
    # not in version control, and as of 2026-09-17 was unset, which is what was
    # blocking a study run. Unique where it is set, because two categories both
    # claiming to be list A is not a state the design can be run from.
    study_role = Column(String(12), unique=True)

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