"""Where the participant's attention was, per item and phase of an item.

One row per (item, phase) in a session, written by the tablet at the end of
the session from what Pepper's HumanAwareness reported while that phase was
running. The phases are the three the item passes through on the device:

    prompt     the robot is giving the instruction and playing the model
    response   the participant is answering (microphone open, or options shown)
    feedback   the robot is delivering the verdict and the re-model

Everything here is a derived state: counts of 500 ms samples in which the
engine classed the person as attending to the robot or tablet, and a
histogram of the engine's own attention labels. No image, no face geometry
and no identity estimate ever leaves the robot. The engine's age and gender
guesses, which the older session summary table still carries, are not
collected at this grain on purpose: they are not measures of attention and
there is no question in the study they answer.

Exploratory. The study's claims rest on the attempt table; this one describes
whether attention differed by phase or by condition, and is reported as
description, not as evidence.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, BigInteger, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

PHASES = ("prompt", "response", "feedback")


class AttentionSegment(Base):
    __tablename__ = "attention_segments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("therapy_sessions.id"), nullable=False, index=True)
    item_id = Column(UUID(as_uuid=True), ForeignKey("activity_items.id"))
    phase = Column(String(12), nullable=False)
    revisit = Column(Boolean)
    # Device clock, epoch milliseconds, same clock as the attempt timestamps.
    started_at_ms = Column(BigInteger, nullable=False)
    ended_at_ms = Column(BigInteger, nullable=False)
    # How many 500 ms samples the engine produced, and in how many of those the
    # person was classed as attending. Zero samples means nobody was detected,
    # which is itself a recording to keep (the participant stepped out of the
    # camera's view, or the engine had lost them).
    samples = Column(Integer, nullable=False, default=0)
    attending_samples = Column(Integer, nullable=False, default=0)
    attending_fraction = Column(Float)
    # Histogram of the engine's AttentionState labels, e.g. {"LOOKING_AT_ROBOT": 9,
    # "LOOKING_DOWN": 3}. Kept so that "looking down" during the response can be
    # separated from "looking away", since looking down is the tablet.
    states = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
