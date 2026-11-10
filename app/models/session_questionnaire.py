from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, JSON
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from sqlalchemy.orm import relationship

from app.database import Base


class SessionQuestionnaire(Base):
    """One participant's ratings of one training block.

    Keyed to `session_id`, which is the entire point. The pilot used a Google
    Form that asked the participant to type a code like "P2" while the database
    keys everything by UUID, so no rating could be attributed to a condition
    with certainty. Every subjective measure from that round is unusable for
    the K-versus-D comparison, however good the items were.

    `condition` and `session_type` are copied here at submission time, for the
    same reason they are copied onto sessions and attempts: a later edit
    elsewhere must not be able to rewrite what this rating was a rating of.
    """

    __tablename__ = "session_questionnaires"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID, ForeignKey("therapy_sessions.id"), unique=True)
    child_id = Column(UUID, ForeignKey("children.id"))

    # Denormalised from the session it rates.
    session_type = Column(String(12))
    condition = Column(String(1))
    block_index = Column(Integer)

    # {item_key: 1..7}. One column rather than a table of rows because the
    # instrument is versioned as a whole and a partial answer set has to stay
    # recognisable as one.
    answers = Column(JSON)
    # {scale_key: mean}, computed at submission from the answers above.
    # Stored as well as derivable, so a later change to a reverse-scoring
    # decision cannot silently restate what was reported.
    scores = Column(JSON)
    comment = Column(String(1000))

    # Which wording the participant actually saw. Without it, revising an item
    # would silently pool two different questions in one column.
    instrument_version = Column(String(20))

    # How long they took, in seconds. A questionnaire completed in eleven
    # seconds is straight-lining, and the analysis should be able to see that
    # rather than infer it from suspiciously round means.
    duration_seconds = Column(Integer)

    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("TherapySession")
    child = relationship("Child")


class SessionNote(Base):
    """The researcher's note about how a session actually ran.

    Replaces the old caregiver feedback dialog, which asked for a star rating
    and three boxes of clinical prose ("progress and achievements", "areas for
    improvement", "behavioural observations"). Those came from the ASD therapy
    app. In a pronunciation study the researcher's opinion of the participant's
    progress is not a measure of anything -- the recordings are -- and asking
    for it invites exactly the kind of unblinded impression that should not be
    near the data.

    What is worth recording is what would make a session unusable, and that is
    a small set of checkboxes rather than an essay: it has to be quick enough
    to actually fill in between participants.
    """

    __tablename__ = "session_notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID, ForeignKey("therapy_sessions.id"), unique=True)

    # Things that happened in the room, each of which is a reason to treat the
    # session with caution or to exclude it.
    interrupted = Column(Boolean, default=False)       # someone walked in, phone rang
    noisy_environment = Column(Boolean, default=False)
    equipment_problem = Column(Boolean, default=False)  # microphone, robot, network
    participant_unwell = Column(Boolean, default=False)
    language_help_given = Column(Boolean, default=False)  # instructions explained in another language

    # The researcher's own judgement, kept as one field and phrased as a
    # recommendation rather than a rating, because it is an action to take and
    # not a score to average.
    exclude_recommended = Column(Boolean, default=False)
    note = Column(String(1000))

    recorded_by = Column(UUID, ForeignKey("caregivers.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("TherapySession")
