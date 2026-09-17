"""Phase 3: a typed exercise must be well-formed before anyone runs it.

The failure these guard against is an item that looks fine in a list and turns
out to be unanswerable with a participant sitting in front of the robot. Every
check here is one that costs nothing at authoring time and cannot be recovered
from at run time.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas import exercise_spec as spec  # noqa: E402
from app.services import exercises  # noqa: E402


# --- the fork ---------------------------------------------------------------

def test_perception_items_never_reach_the_recogniser():
    """Six of twenty pilot participants said the robot could not hear Kenyan
    English. An exercise that cannot invoke the recogniser cannot false-reject
    anyone, and that is the point of typing items at all."""
    tapped = (exercises.MINIMAL_PAIR_ID, exercises.ODD_ONE_OUT,
              exercises.SAME_SOUND_MATCH, exercises.SYLLABLE_COUNT,
              exercises.SCHWA_SPOT, exercises.STRESS_PLACE)
    for key in tapped:
        assert not exercises.needs_asr(key), key
        assert not exercises.is_scored_by_pipeline(key), key


def test_spoken_items_are_the_only_ones_the_pipeline_sees():
    assert exercises.is_scored_by_pipeline(exercises.REPEAT_WORD)
    assert exercises.is_scored_by_pipeline(exercises.READ_SENTENCE)


def test_picture_describe_is_recorded_but_not_scored():
    """There is no reference transcript to align a free description against, so
    a verdict from the pipeline would be meaningless. It is kept for human
    rating instead."""
    assert exercises.needs_asr(exercises.PICTURE_DESCRIBE)
    assert not exercises.is_scored_by_pipeline(exercises.PICTURE_DESCRIBE)


def test_an_untyped_item_is_the_behaviour_that_predates_typing():
    """Every item stored before Phase 3 has no type and was a repeat-the-word
    item. Defaulting keeps them, and every attempt against them, meaning what
    they meant."""
    assert exercises.resolve(None).key == exercises.REPEAT_WORD
    assert exercises.needs_asr(None)


def test_an_unknown_type_is_refused_rather_than_guessed():
    with pytest.raises(exercises.UnknownExerciseType):
        exercises.resolve("tap_the_vibes")


# --- answer keys ------------------------------------------------------------

def test_an_answer_outside_the_options_is_refused():
    """The likeliest authoring mistake by a wide margin: a distractor edited
    later and the key left pointing at the old string."""
    with pytest.raises(ValidationError):
        spec.parse("odd_one_out", {"options": ["ship", "sheep", "chip"],
                                   "answer": "sheap"})


def test_duplicate_options_are_refused():
    with pytest.raises(ValidationError):
        spec.parse("odd_one_out", {"options": ["ship", "ship", "chip"],
                                   "answer": "chip"})


def test_a_minimal_pair_has_exactly_two_options():
    with pytest.raises(ValidationError):
        spec.parse("minimal_pair_id",
                   {"options": ["ship", "sheep", "chip"], "answer": "ship"})
    parsed = spec.parse("minimal_pair_id",
                        {"options": ["ship", "sheep"], "answer": "sheep"})
    assert parsed.answer == "sheep"


def test_a_same_sound_cue_cannot_also_be_an_option():
    """Otherwise the answer is "the one identical to the cue" and the item
    measures nothing about vowels."""
    with pytest.raises(ValidationError):
        spec.parse("same_sound_match",
                   {"cue": "hate", "options": ["hate", "day", "hat"],
                    "answer": "day"})


def test_a_typo_in_a_spec_key_is_refused_not_ignored():
    """Silently defaulting would run the item as something other than authored."""
    with pytest.raises(ValidationError):
        spec.parse("repeat_word", {"word": "cat", "wrod": "cat"})


# --- sentences --------------------------------------------------------------

def test_the_target_word_must_be_in_the_sentence():
    with pytest.raises(ValidationError):
        spec.parse("read_sentence",
                   {"sentence": "The ship is here.", "target_word": "sheep"})


def test_the_target_word_is_found_past_punctuation():
    parsed = spec.parse("read_sentence",
                        {"sentence": "I can see the sheep.", "target_word": "sheep"})
    assert parsed.target_word == "sheep"


# --- syllables --------------------------------------------------------------

def test_syllables_must_spell_the_word():
    """A breakdown that does not reconstruct the word means the item is showing
    the participant one word and grading another."""
    with pytest.raises(ValidationError):
        spec.parse("stress_place",
                   {"word": "banana", "syllables": ["ba", "na"], "answer_index": 1})


def test_a_stress_index_outside_the_word_is_refused():
    with pytest.raises(ValidationError):
        spec.parse("stress_place",
                   {"word": "banana", "syllables": ["ba", "na", "na"],
                    "answer_index": 5})


def test_schwa_spot_takes_every_reduced_syllable():
    """"banana" has two, and an item that accepted only one would mark a
    correct answer wrong."""
    parsed = spec.parse("schwa_spot",
                        {"word": "banana", "syllables": ["ba", "na", "na"],
                         "answer_indices": [0, 2]})
    assert parsed.answer_indices == [0, 2]


def test_every_syllable_cannot_be_reduced():
    with pytest.raises(ValidationError):
        spec.parse("schwa_spot",
                   {"word": "banana", "syllables": ["ba", "na", "na"],
                    "answer_indices": [0, 1, 2]})


# --- grading ----------------------------------------------------------------

def test_a_tapped_answer_is_graded_exactly():
    body = {"options": ["ship", "sheep"], "answer": "sheep"}
    assert spec.is_correct("minimal_pair_id", body, "sheep")
    assert spec.is_correct("minimal_pair_id", body, "  sheep ")
    assert not spec.is_correct("minimal_pair_id", body, "ship")
    # Never fuzzy: the participant tapped a string this item supplied, so
    # anything else means the client sent something that was not offered.
    assert not spec.is_correct("minimal_pair_id", body, "sheeps")


def test_schwa_answers_are_compared_as_a_set():
    body = {"word": "banana", "syllables": ["ba", "na", "na"],
            "answer_indices": [0, 2]}
    assert spec.is_correct("schwa_spot", body, [2, 0])
    assert not spec.is_correct("schwa_spot", body, [0])
    assert not spec.is_correct("schwa_spot", body, [0, 1, 2])


def test_a_spoken_item_cannot_be_graded_by_tapping():
    with pytest.raises(ValueError):
        spec.is_correct("repeat_word", {"word": "cat"}, "cat")


# --- display ----------------------------------------------------------------

def test_the_name_comes_from_the_spec():
    """Derived rather than stored beside it: a name and a spec that disagree is
    a list that reads correctly and runs as something else."""
    assert spec.display_name(spec.parse("repeat_word", {"word": "cat"})) == "cat"
    assert spec.display_name(spec.parse(
        "read_sentence",
        {"sentence": "I can see the sheep.", "target_word": "sheep"})) == "sheep"


def test_every_type_has_an_instruction():
    """An instruction that varies between lists is itself a difficulty
    difference between them, so each type has exactly one."""
    samples = {
        "repeat_word": {"word": "cat"},
        "read_sentence": {"sentence": "I see a cat.", "target_word": "cat"},
        "picture_describe": {"prompt": "What is happening?"},
        "minimal_pair_id": {"options": ["ship", "sheep"], "answer": "ship"},
        "odd_one_out": {"options": ["ship", "chip", "sheep"], "answer": "sheep"},
        "same_sound_match": {"cue": "hate", "options": ["day", "hat", "cut"],
                             "answer": "day"},
        "syllable_count": {"options": ["water", "table", "banana"],
                           "answer": "banana"},
        "schwa_spot": {"word": "banana", "syllables": ["ba", "na", "na"],
                       "answer_indices": [0, 2]},
        "stress_place": {"word": "banana", "syllables": ["ba", "na", "na"],
                         "answer_index": 1},
    }
    assert set(samples) == set(exercises.EXERCISE_TYPES)
    for key, body in samples.items():
        prompt = spec.default_prompt(spec.parse(key, body))
        assert prompt and prompt.strip() == prompt


# --- target features --------------------------------------------------------

def test_features_are_the_kenyan_transfer_set():
    """Not "hardest English words": epitome and hyperbole test whether someone
    has seen the word written, which is lexical knowledge and is not what a
    pronunciation tutor teaches in one session."""
    assert "kit_fleece" in exercises.TARGET_FEATURES
    assert "dental_fricative" in exercises.TARGET_FEATURES
    assert len(exercises.TARGET_FEATURES) == len(set(exercises.TARGET_FEATURES))
