from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, String,
                        UniqueConstraint)
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from sqlalchemy.orm import relationship

from app.database import Base


class RatingSet(Base):
    """Which recordings are to be rated, for one task.

    Built once by the researcher, then served identically to every rater.
    Two raters who rated different samples cannot be compared, so the sample
    is a table rather than a query each rater runs for themselves.

    A tenth of the set is entered twice, with repeat_index 1: the same clip
    presented again later in the queue, so within-rater consistency can be
    measured rather than assumed.
    """

    __tablename__ = "rating_sets"
    __table_args__ = (UniqueConstraint("task", "attempt_id", "repeat_index"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # pilot_label | study_rating
    task = Column(String(16), nullable=False)
    attempt_id = Column(UUID, ForeignKey("session_activities.id"), nullable=False)
    # session_type/condition/feature, so the agreement report can be split.
    stratum = Column(String(80))
    repeat_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    attempt = relationship("SessionActivity")


class Rating(Base):
    """One person's judgement of one recording.

    Made blind: the rater saw the target and heard the clip, and nothing
    else -- not the pipeline's verdict, not its score, not the recogniser's
    transcript, not the condition or the participant. The queue endpoint is
    where that is enforced; this row is what it produces.
    """

    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("task", "attempt_id", "rater_id", "repeat_index"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task = Column(String(16), nullable=False)
    attempt_id = Column(UUID, ForeignKey("session_activities.id"), nullable=False)
    rater_id = Column(UUID, ForeignKey("caregivers.id"), nullable=False)
    repeat_index = Column(Integer, default=0)

    # Was the target word produced correctly? Both tasks ask this; it is what
    # the threshold refit reads and what the false-correction rate is built on.
    correct = Column(Boolean)
    # 1..5, study_rating only: the graded measure.
    accuracy = Column(Integer)
    # Which target feature the rater heard go wrong, if any.
    wrong_feature = Column(String(32))
    # The recording, not the speaker, was the problem. Never scored.
    unusable = Column(Boolean, default=False)

    # Milliseconds from the clip loading to the rating being sent. A rating
    # made in 400 ms was not listened to.
    duration_ms = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    attempt = relationship("SessionActivity")
    rater = relationship("Caregiver")
