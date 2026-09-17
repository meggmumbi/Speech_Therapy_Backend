"""The study participant.

Named ``Child`` / ``children`` for historical reasons: the system began as an
ASD speech-therapy app for children and became a pronunciation tutoring study
with adult volunteers. The rename to ``Participant`` touches every foreign key
and every stored session, so it is deliberately deferred -- see
docs/STUDY_ROADMAP.md. Read "child" as "participant" throughout.

Two changes here follow from that shift in purpose.

**No clinical fields.** ``diagnosis_date`` and ``therapy_goals`` were removed on
2026-09-17. A diagnosis date collected from a healthy adult volunteer is
special-category health data under the Data Protection Act 2019 with no purpose
that would justify holding it.

**No names.** ``participant_code`` is the identifier. The code-to-name link is
kept on paper by the researcher and never enters this database, so an extract
for analysis carries no direct identifier. ``name`` remains only so that rows
created before this change still load; new records leave it null.

Everything else here exists because the analysis needs it. The study's model has
participant as a random effect and language background as a fixed effect: which
transfer features a Kenyan English speaker shows depends heavily on their first
language, and a reviewer cannot judge the sample without knowing its
composition. A covariate not collected at enrolment cannot be recovered later.
"""

from sqlalchemy import (Boolean, Column, Date, ForeignKey, Integer, String,
                        Table, Text)
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from sqlalchemy.orm import relationship

from app.database import Base


child_category_association = Table(
    'child_category_association',
    Base.metadata,
    Column('child_id', UUID(as_uuid=True), ForeignKey('children.id')),
    Column('category_id', UUID(as_uuid=True), ForeignKey('activity_categories.id'))
)


# Allowed values, kept here so the API schema, the Android form and the analysis
# export all read them from one place. Stored as plain strings rather than a
# database enum: adding a value must not require a migration mid-study.
MEDIUM_OF_INSTRUCTION = ("english", "kiswahili", "mother_tongue", "mixed", "other")
CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
VOICE_ASSISTANT_USE = ("never", "rarely", "monthly", "weekly", "daily")


class Child(Base):
    """One enrolled participant."""

    __tablename__ = "children"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    caregiver_id = Column(UUID, ForeignKey("caregivers.id"))

    # --- identity -----------------------------------------------------------
    # The pseudonymous study identifier ("P21"). Unique so that two researchers
    # cannot enrol the same code twice and silently merge two people's data.
    participant_code = Column(String(32), unique=True, index=True)
    # Deprecated. Present so pre-2026-09-17 rows still load. Do not populate.
    name = Column(String(100))
    age = Column(Integer)
    # Free text rather than a fixed set: this is a person's own description.
    gender = Column(String(40))

    # --- language background ------------------------------------------------
    # The strongest predictor of which transfer features appear. A Dholuo
    # speaker and a Gikuyu speaker do not make the same English vowel and
    # liquid substitutions, so pooling them without this column would hide the
    # effect the study is looking for.
    first_language = Column(String(60))
    # Comma-separated; Kenyan multilingualism means one field cannot hold it.
    other_languages = Column(String(200))
    home_language = Column(String(60))
    # Dialect proxy. County or region where the participant grew up, which
    # predicts accent better than where they live now.
    region_of_upbringing = Column(String(80))

    # Age of first sustained English exposure, and the language lower primary
    # was actually taught in. Kenyan schooling often switches medium partway,
    # and both are standard covariates in second-language research.
    english_onset_age = Column(Integer)
    primary_medium_of_instruction = Column(String(20))

    # CEFR self-rating. Self-report is weak but it is what comparable studies
    # report, and it costs one question.
    self_rated_english = Column(String(2))

    # --- controls -----------------------------------------------------------
    # Novelty and familiarity control: someone who talks to Siri daily has
    # different expectations of a robot's listening than someone who never has.
    voice_assistant_use = Column(String(10))
    # Exclusion criterion, self-reported. The boolean drives exclusion; the text
    # records what was reported so the decision is auditable.
    hearing_or_speech_difficulty = Column(Boolean, default=False)
    hearing_or_speech_note = Column(String(300))

    # --- ethics trail -------------------------------------------------------
    # Separate flags because they are separately refusable: someone may agree to
    # take part while refusing to have their audio kept afterwards. Scoring
    # needs the audio in the moment; retention for the rater sample does not
    # follow from that.
    consent_participation = Column(Boolean, default=False)
    consent_audio_retention = Column(Boolean, default=False)
    consent_date = Column(Date)

    notes = Column(Text)
    created_at = Column(Date, default=datetime.utcnow)

    # Relationship with ActivityCategory
    areas_of_interest = relationship(
        "ActivityCategory",
        secondary=child_category_association,
        back_populates="children"
    )

    @property
    def label(self) -> str:
        """What to show in a UI or a log line. Never the name."""
        return self.participant_code or f"participant {str(self.id)[:8]}"
