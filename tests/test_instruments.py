"""Phase 5: what the questionnaire is allowed to ask, and of whom.

The pilot's subjective measures failed for three reasons, and each of these
tests pins one of them shut.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import instruments  # noqa: E402


# --- who is asked ------------------------------------------------------------

@pytest.mark.parametrize("phase", ["pretest", "posttest", "delayed"])
def test_assessments_are_not_rated(phase):
    """There is no tutor behaviour in a pre-test to form an impression of: the
    robot says only "thank you, here is the next one". Asking would collect
    ratings of something that did not happen, and asking at all would frame the
    test as a performance worth reflecting on."""
    assert instruments.for_session(phase, None) == []


def test_training_blocks_are_rated():
    assert len(instruments.for_session("training", "K")) == len(instruments.ALL_SCALES)


def test_an_adhoc_session_is_not_rated():
    """It carries no condition, so its ratings could not be attributed to one."""
    assert instruments.for_session(None, None) == []


# --- the ceiling the pilot hit ----------------------------------------------

def test_the_scale_has_seven_points_not_five():
    """A five-point scale with a virtuous end is what produced the pilot's
    ceiling: pleasant, kind, friendly and likable all sat at strongly-agree.
    Seven leaves room above "good" for "very good"."""
    assert (instruments.SCALE_MIN, instruments.SCALE_MAX) == (1, 7)


def test_every_item_names_both_ends():
    """Named poles rather than agree/disagree. "Disagree ... agree" about a
    virtuous statement has one obviously nice end, which is how every
    likeability item in the pilot reached the top."""
    for scale in instruments.ALL_SCALES:
        for item in scale.items:
            if item.kind == "single_choice":
                continue
            assert item.low_label, f"{scale.key}/{item.key}"
            assert item.high_label, f"{scale.key}/{item.key}"


def test_some_items_are_reverse_scored():
    """Without reversals a respondent who taps 7 down the page produces a
    perfect score rather than an inconsistent one, and straight-lining is
    undetectable."""
    reversed_items = [
        item for scale in instruments.ALL_SCALES for item in scale.items if item.reverse
    ]
    assert len(reversed_items) >= 3


def test_reverse_scoring_is_not_sent_to_the_tablet():
    """A respondent who knows which items are flipped can keep their answers
    consistent on purpose, which is exactly what reversals exist to detect."""
    for scale in instruments.ALL_SCALES:
        body = instruments.serialise(scale)
        for item in body["items"]:
            assert "reverse" not in item


# --- scoring -----------------------------------------------------------------

def test_reversals_actually_change_the_mean():
    answers = {item.key: 6 for item in instruments.MOTIVATION.items
               if item.kind != "single_choice"}
    scored = instruments.score(instruments.MOTIVATION, answers)
    assert scored["mean"] != 6.0, "reverse-scored items were not flipped"


def test_a_scale_with_no_reversals_averages_plainly():
    answers = {item.key: 6 for item in instruments.GODSPEED.items}
    assert instruments.score(instruments.GODSPEED, answers)["mean"] == 6.0


def test_a_partial_answer_set_reports_how_partial_it_was():
    """A mean over two of seven items is not the same number as a mean over
    seven, and nothing downstream should have to guess which it got."""
    first = next(i for i in instruments.GODSPEED.items)
    scored = instruments.score(instruments.GODSPEED, {first.key: 5})
    assert scored["answered"] == 1
    assert scored["items"] == len(instruments.GODSPEED.items)


def test_no_answers_gives_no_mean_rather_than_zero():
    """Zero would be averaged into a group mean as though it were an opinion."""
    assert instruments.score(instruments.GODSPEED, {})["mean"] is None


# --- what is measured --------------------------------------------------------

def test_feedback_trust_is_present_and_asks_about_false_corrections():
    """The one scale that makes the system's own error rate interpretable. A
    participant falsely corrected three times should report lower trust, and if
    they do not, the false-correction rate is not doing what the analysis
    assumes."""
    keys = {item.key for item in instruments.FEEDBACK_TRUST.items}
    assert "accurate" in keys
    assert "missed" in keys


def test_item_keys_are_unique_across_the_whole_instrument():
    """They are stored in one JSON object, so a collision would silently
    overwrite one scale's answer with another's."""
    keys = [item.key for scale in instruments.ALL_SCALES for item in scale.items]
    assert len(keys) == len(set(keys))


def test_the_instrument_is_short_enough_to_finish():
    """Volunteers, at the end of a session. A long form is how straight-lined
    answers get into the data."""
    rated = [item for scale in instruments.ALL_SCALES for item in scale.items
             if item.kind != "single_choice"]
    assert len(rated) <= 20, f"{len(rated)} rated items is too many to finish honestly"
