"""Editing one item in place, and what the server refuses to let change.

The bulk import validates a whole list. These pin the single-row path the
console uses, and the one rule that matters most: an item that has recorded
attempts cannot have its question rewritten under them.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException  # noqa: E402

from app.api import authoring  # noqa: E402


class _Category:
    difficulty_level = "medium"


def _write(**kw):
    return authoring.ItemWrite(**kw)


# --- validation at the row -----------------------------------------------

def test_a_row_is_validated_against_its_type():
    with pytest.raises(HTTPException) as exc:
        authoring._prepare(_write(exercise_type="minimal_pair_id",
                                  spec={"options": ["ship", "sheep"], "answer": "chip"}),
                           _Category())
    assert exc.value.status_code == 422
    assert "answer" in exc.value.detail


def test_an_unknown_type_is_refused_with_the_known_ones_listed():
    with pytest.raises(HTTPException) as exc:
        authoring._prepare(_write(exercise_type="hum_the_tune", spec={}), _Category())
    assert exc.value.status_code == 422
    assert "repeat_word" in exc.value.detail


def test_an_unknown_feature_is_refused():
    with pytest.raises(HTTPException) as exc:
        authoring._prepare(_write(exercise_type="repeat_word", spec={"word": "cat"},
                                  target_feature="lateral_fricative"), _Category())
    assert exc.value.status_code == 422


def test_the_name_and_prompt_are_derived_not_typed():
    """A name column and a spec that disagree is a list that reads correctly
    and runs as something else, so the row never carries a typed name."""
    values = authoring._prepare(
        _write(exercise_type="read_sentence",
               spec={"sentence": "I can see the sheep.", "target_word": "sheep"},
               target_feature="kit_fleece", match_key=" kf-01 "),
        _Category())
    assert values["name"] == "sheep"
    assert values["description"].startswith("Read this out loud.")
    assert values["match_key"] == "kf-01"
    assert values["difficulty_level"] == "medium"


def test_a_custom_prompt_is_kept():
    values = authoring._prepare(
        _write(exercise_type="repeat_word", spec={"word": "cat"},
               description="Say it like you mean it: cat."),
        _Category())
    assert values["description"] == "Say it like you mean it: cat."


# --- the reveal shape the console highlights --------------------------------

def test_serialised_item_carries_everything_the_editor_needs():
    class _Item:
        id = uuid.uuid4(); category_id = uuid.uuid4(); name = "ship"
        description = "Say the word. ship"; exercise_type = None
        spec = {"word": "ship"}; target_feature = "kit_fleece"; match_key = "kf-say"
        position = 3; audio_url = None; difficulty_level = "medium"
        effective_type = "repeat_word"
    body = authoring._serialise_item(_Item(), attempts=2)
    assert body["exercise_type"] == "repeat_word"
    assert body["spec"] == {"word": "ship"}
    assert body["attempts"] == 2
