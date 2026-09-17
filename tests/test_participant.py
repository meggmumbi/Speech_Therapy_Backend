"""The participant record: what it must collect, and what it must not.

These tests encode decisions rather than mechanics. The clinical fields and the
name are gone for legal and ethical reasons, not stylistic ones, and a future
refactor that quietly reintroduces them should fail here rather than in a data
protection review.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.child import Child  # noqa: E402
from app.schemas.child import Child as ChildRead  # noqa: E402
from app.schemas.child import ChildCreate  # noqa: E402


def _valid(**overrides) -> dict:
    payload = {
        "participant_code": "P21",
        "age": 21,
        "gender": "Female",
        "first_language": "Dholuo",
        "other_languages": "Kiswahili, English",
        "home_language": "Dholuo",
        "region_of_upbringing": "Kisumu",
        "english_onset_age": 5,
        "primary_medium_of_instruction": "mother_tongue",
        "self_rated_english": "B2",
        "voice_assistant_use": "weekly",
        "hearing_or_speech_difficulty": False,
        "consent_participation": True,
        "consent_audio_retention": True,
        "consent_date": "2026-09-17",
    }
    payload.update(overrides)
    return payload


# --- what must not be collected --------------------------------------------

def test_clinical_fields_are_gone_from_the_model():
    """A diagnosis date from a healthy volunteer is special-category health
    data with no purpose that justifies holding it."""
    columns = {c.name for c in Child.__table__.columns}
    assert "diagnosis_date" not in columns
    assert "therapy_goals" not in columns


def test_clinical_fields_are_rejected_by_the_api():
    """Pydantic ignores unknown keys by default, so this asserts the field did
    not survive anywhere in the request shape rather than that it 400s."""
    model = ChildCreate(**_valid())
    assert not hasattr(model, "diagnosis_date")
    assert not hasattr(model, "therapy_goals")


def test_name_is_not_part_of_the_enrolment_payload():
    """The code-to-name link is kept on paper. An extract for analysis must
    carry no direct identifier by construction, not by remembering to strip
    one."""
    assert "name" not in ChildCreate.model_fields


# --- what must be collected -------------------------------------------------

def test_participant_code_is_required():
    with pytest.raises(Exception):
        ChildCreate(**{k: v for k, v in _valid().items()
                       if k != "participant_code"})


def test_participant_code_is_normalised():
    """Case and whitespace slips are the likeliest route to two rows for one
    person, which cannot be untangled from the session data afterwards."""
    assert ChildCreate(**_valid(participant_code=" p21 ")).participant_code == "P21"


def test_language_background_is_normalised():
    model = ChildCreate(**_valid(first_language="  kikuyu  ",
                                 region_of_upbringing="nyeri"))
    assert model.first_language == "Kikuyu"
    assert model.region_of_upbringing == "Nyeri"


def test_covariates_the_analysis_needs_are_present():
    """The mixed-effects model treats language background as a fixed effect:
    a Dholuo speaker and a Gikuyu speaker do not make the same substitutions."""
    fields = ChildCreate.model_fields
    for required in ("first_language", "other_languages", "home_language",
                     "region_of_upbringing", "english_onset_age",
                     "primary_medium_of_instruction", "self_rated_english",
                     "voice_assistant_use", "hearing_or_speech_difficulty"):
        assert required in fields, required


def test_consent_is_recorded_as_two_separable_decisions():
    """Someone may agree to take part while refusing to have their audio kept.
    Scoring needs the audio in the moment; retention does not follow from it."""
    model = ChildCreate(**_valid(consent_participation=True,
                                 consent_audio_retention=False))
    assert model.consent_participation is True
    assert model.consent_audio_retention is False


# --- controlled vocabulary --------------------------------------------------

def test_controlled_vocabulary_is_enforced():
    """Enforced at the API boundary so the analysis export never has to treat
    "Eng", "english" and "English " as three values."""
    for bad in ({"self_rated_english": "B7"},
                {"primary_medium_of_instruction": "Swahili"},
                {"voice_assistant_use": "sometimes"}):
        with pytest.raises(Exception):
            ChildCreate(**_valid(**bad))


def test_implausible_ages_are_rejected():
    for bad in ({"age": 3}, {"age": 200}, {"english_onset_age": 90}):
        with pytest.raises(Exception):
            ChildCreate(**_valid(**bad))


def test_optional_background_still_enrols():
    """A participant who declines to answer a background question must still be
    enrollable; refusing to answer is not a reason to exclude someone."""
    model = ChildCreate(participant_code="P22")
    assert model.participant_code == "P22"
    assert model.first_language is None


# --- reading a legacy row ---------------------------------------------------
#
# On 2026-09-17 the list endpoint returned 500 for every request, because the
# read schema required participant_code and twenty-two rows enrolled before the
# participant record existed have none. One legacy row hid all twenty-three
# participants, including the one just created. These pin the asymmetry that
# fixed it: mandatory to write, optional to read.

def test_a_participant_without_a_code_can_still_be_read():
    """Otherwise the rows that most need fixing are the ones nobody can see."""
    import uuid as _uuid
    model = ChildRead(id=_uuid.uuid4(), age=22)
    assert model.participant_code is None


def test_one_legacy_row_cannot_break_the_whole_list():
    import uuid as _uuid
    rows = [ChildRead(id=_uuid.uuid4(), participant_code="P1", age=24),
            ChildRead(id=_uuid.uuid4(), age=22)]
    assert [row.participant_code for row in rows] == ["P1", None]


def test_enrolling_without_a_code_is_still_refused():
    """The read side is lenient about history; the write side is not, or the
    pool of code-less rows would keep growing."""
    with pytest.raises(Exception):
        ChildCreate(age=21)
    with pytest.raises(Exception):
        ChildCreate(participant_code="   ")


def test_a_code_is_still_normalised_on_write():
    assert ChildCreate(participant_code=" p21 ").participant_code == "P21"


# --- display ----------------------------------------------------------------

def test_label_never_exposes_a_name():
    child = Child(participant_code="P21", name="should not be here")
    assert child.label == "P21"

    import uuid as _uuid
    unlabelled = Child(id=_uuid.uuid4(), name="also not here")
    assert "not here" not in unlabelled.label
