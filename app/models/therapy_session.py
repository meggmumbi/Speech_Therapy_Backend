from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from sqlalchemy.orm import relationship

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
    # Study condition for this session: 'K' (knowledge of correct response --
    # re-model only) or 'D' (diagnostic feedback). Assigned per session by the
    # counterbalancing, so that a single app renders whichever feedback the
    # backend returns and the two conditions cannot drift apart in UI, timing
    # or scoring.
    condition = Column(String(1))

    # What kind of session this is: 'training' (a counterbalanced block, with
    # feedback) or one of 'pretest' / 'posttest' / 'delayed' (an assessment,
    # with none). See services/study_design.SESSION_TYPES.
    #
    # NULL means an ad-hoc therapy session that was never part of the study.
    # Those are allowed -- the app serves ordinary therapy too -- but a
    # participant who has a counterbalancing assignment must never be run
    # through one, and the scoring endpoint refuses to score into it. Every
    # session recorded before 2026-09-17 is NULL, which is exactly the problem
    # this column exists to stop recurring: none of them can be attributed to
    # a condition.
    session_type = Column(String(12))

    # 1 or 2 for a training block; NULL for an assessment. Denormalised from
    # the assignment so that a later change to the design table cannot rewrite
    # what a stored session actually was.
    block_index = Column(Integer)

    # Seed for this session's item order. The order itself is not stored: it is
    # regenerated from the seed, so the exact sequence a participant saw is
    # reproducible from two columns rather than trusted to a log.
    item_order_seed = Column(Integer)

    is_completed = Column(Boolean, default=False)

    # The researcher stopped this session before the last item. Recorded
    # because a session with fifteen of twenty-one items is not a short session
    # -- it is an incomplete one, and the two must not be averaged together.
    ended_early = Column(Boolean)
    child = relationship("Child")
    category = relationship("ActivityCategory")
    activities = relationship("SessionActivity", back_populates="session")