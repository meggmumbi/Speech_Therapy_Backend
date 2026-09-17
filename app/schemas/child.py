"""Request and response shapes for the participant record.

Validation here is deliberately stricter than the database, which stores plain
strings. Controlled vocabulary is enforced at the API boundary so that the
analysis export never has to clean up "Eng"/"english"/"English " as three
values, while a new value can still be added by editing one tuple rather than
migrating a database enum mid-study.

See app/models/child.py for why the clinical fields are gone and why names are
not stored.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional, List
from datetime import date
import uuid


MediumOfInstruction = Literal["english", "kiswahili", "mother_tongue", "mixed", "other"]
CEFRLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
VoiceAssistantUse = Literal["never", "rarely", "monthly", "weekly", "daily"]


class ChildBase(BaseModel):
    """Fields a researcher fills in at enrolment, other than the code.

    ``participant_code`` is deliberately *not* here. Writing it is mandatory
    and reading it is not, and one shared field cannot be both: see
    [ChildCreate] and [Child].
    """

    age: Optional[int] = Field(default=None, ge=5, le=120)
    gender: Optional[str] = Field(default=None, max_length=40)

    # Language background: the covariates the analysis model needs.
    first_language: Optional[str] = Field(default=None, max_length=60)
    other_languages: Optional[str] = Field(
        default=None, max_length=200,
        description="Comma-separated, in order of fluency.",
    )
    home_language: Optional[str] = Field(default=None, max_length=60)
    region_of_upbringing: Optional[str] = Field(default=None, max_length=80)
    english_onset_age: Optional[int] = Field(
        default=None, ge=0, le=60,
        description="Age at first sustained exposure to English.",
    )
    primary_medium_of_instruction: Optional[MediumOfInstruction] = None
    self_rated_english: Optional[CEFRLevel] = None

    # Controls.
    voice_assistant_use: Optional[VoiceAssistantUse] = None
    hearing_or_speech_difficulty: bool = False
    hearing_or_speech_note: Optional[str] = Field(default=None, max_length=300)

    # Ethics trail. Separately refusable, so separately recorded.
    consent_participation: bool = False
    consent_audio_retention: bool = False
    consent_date: Optional[date] = None

    notes: Optional[str] = None

    @field_validator("first_language", "home_language", "region_of_upbringing")
    @classmethod
    def _tidy_free_text(cls, value: Optional[str]) -> Optional[str]:
        """Trim and title-case so "kikuyu" and "Kikuyu " group together."""
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned.title() if cleaned else None


class ChildCreate(ChildBase):
    """Enrolling or editing a participant. A code is required here."""

    participant_code: str = Field(
        min_length=1, max_length=32,
        description="Pseudonymous study code, e.g. P21. The code-to-name link "
                    "is kept on paper, offline, and never sent here.",
    )
    areas_of_interest_ids: List[uuid.UUID] = Field(default_factory=list)

    @field_validator("participant_code")
    @classmethod
    def _tidy_code(cls, value: str) -> str:
        """Normalise the code so "p21", "P21 " and "P21" are one participant.

        Case and whitespace slips are the most likely way to end up with two
        rows for one person, and a duplicate participant is not recoverable
        from the data afterwards.
        """
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("participant_code cannot be blank")
        return cleaned


class ActivityCategory(BaseModel):
    id: uuid.UUID
    name: str

    class Config:
        from_attributes = True


class Child(ChildBase):
    """What the API returns. Carries no direct identifier by construction.

    The code is optional *on read only*, and that asymmetry is the point. Rows
    enrolled before the participant record existed have no code, and a required
    field here made the whole list endpoint fail validation: one legacy row
    without a code hid all twenty-three participants, including the ones just
    created. A record the researcher cannot see is a record they cannot fix.
    """

    participant_code: Optional[str] = Field(
        default=None, max_length=32,
        description="Null for participants enrolled before codes were "
                    "introduced. They need one before they can be run.",
    )
    id: uuid.UUID
    created_at: Optional[date] = None
    areas_of_interest: List[ActivityCategory] = Field(default_factory=list)

    class Config:
        from_attributes = True
