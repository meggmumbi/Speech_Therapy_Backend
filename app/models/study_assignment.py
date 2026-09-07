from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from sqlalchemy.orm import relationship

from app.database import Base


class StudyAssignment(Base):
    """A participant's counterbalancing group, fixed once and never re-rolled.

    One row per participant. ``child_id`` is unique so that a second call to
    the assignment endpoint cannot move someone between groups mid-study --
    which would silently destroy the counterbalance and could not be detected
    afterwards from the session records alone.

    An excluded participant keeps their row (the record of what happened) but
    frees their slot in the balance count, so a withdrawal does not leave the
    design permanently lopsided.
    """

    __tablename__ = "study_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    child_id = Column(UUID, ForeignKey("children.id"), unique=True, nullable=False)

    # 0..3, indexing services.study_design.GROUPS
    group_index = Column(Integer, nullable=False)
    # Denormalised from the group for query convenience and so that a change
    # to the group table can never silently rewrite history.
    block1_condition = Column(String(1), nullable=False)
    block1_list = Column(String(1), nullable=False)
    block2_condition = Column(String(1), nullable=False)
    block2_list = Column(String(1), nullable=False)

    excluded = Column(Boolean, default=False, nullable=False)
    exclusion_reason = Column(String(300))

    assigned_at = Column(DateTime, default=datetime.utcnow)

    child = relationship("Child")
