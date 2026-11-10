"""Phase 2: a session must be attributable to what it actually was.

The failure these guard against is not a crash. It is data that looks like
study data and is not: every session recorded before 2026-09-17 has a NULL
condition because the scoring endpoint silently defaulted to 'D', so none of
them can be attributed to a condition and none can be distinguished from an
ad-hoc therapy session.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import study_design  # noqa: E402
from app.services.pronunciation.audio import assess_quality  # noqa: E402
from app.services.pronunciation.feedback import (  # noqa: E402
    ASSESSMENT_ACKS, assessment_acknowledgement)

SR = 16_000


def _tone(seconds: float = 1.0, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amplitude * np.sin(2 * np.pi * 200 * t)).astype(np.float32)


def _clipped(seconds: float = 1.0) -> np.ndarray:
    """A recording driven hard enough to flatten against full scale.

    Amplitude 1.5 before clipping, not 3x the 0.3 default: that only reaches
    0.9 and never touches the rail, which is how the first version of this
    fixture passed a clipping test without clipping.
    """
    return np.clip(_tone(seconds, amplitude=1.5) * 5.0, -1.0, 1.0).astype(np.float32)


# --- session types ----------------------------------------------------------

def test_assessments_are_the_three_test_phases():
    assert study_design.ASSESSMENT_PHASES == ("pretest", "posttest", "delayed")
    for phase in study_design.ASSESSMENT_PHASES:
        assert study_design.is_assessment(phase)


def test_training_and_unstamped_sessions_are_not_assessments():
    """An unstamped session is ad-hoc therapy, not a silent test. Muting the
    robot for one would be the more confusing failure."""
    assert not study_design.is_assessment(study_design.TRAINING)
    assert not study_design.is_assessment(None)
    assert not study_design.is_assessment("something else")


# --- item order -------------------------------------------------------------

def test_item_order_is_reproducible_from_the_seed():
    """The order is not stored; it is regenerated. If the same seed stopped
    producing the same order, every recorded session's sequence would be lost."""
    items = [f"item-{i}" for i in range(12)]
    seed = study_design.new_order_seed()
    assert study_design.order_items(items, seed) == study_design.order_items(items, seed)


def test_item_order_actually_varies_between_sessions():
    items = [f"item-{i}" for i in range(12)]
    orders = {tuple(study_design.order_items(items, s)) for s in range(1, 40)}
    assert len(orders) > 30, "seeds should give distinct orders"


def test_item_order_is_a_permutation_not_a_filter():
    items = [f"item-{i}" for i in range(12)]
    shuffled = study_design.order_items(items, 1234)
    assert sorted(shuffled) == sorted(items)


def test_unseeded_session_keeps_the_natural_order():
    """An ad-hoc session has no seed and should not be silently reordered."""
    items = ["a", "b", "c"]
    assert study_design.order_items(items, None) == items


def test_order_seed_fits_a_plain_integer_column():
    for _ in range(200):
        seed = study_design.new_order_seed()
        assert 0 < seed < 2 ** 31


# --- assessments say nothing ------------------------------------------------

def test_assessment_acknowledgement_takes_no_result():
    """There is no path from the verdict to what is said, so no later edit can
    make an assessment leak correctness without changing this signature."""
    import inspect
    params = inspect.signature(assessment_acknowledgement).parameters
    assert set(params) == {"attempt_index"}


def test_assessment_acknowledgement_carries_no_verdict():
    for index in range(len(ASSESSMENT_ACKS) * 2):
        fb = assessment_acknowledgement(index)
        assert fb.kind == "assessment"
        assert fb.condition is None
        assert fb.named_phone is None
        assert fb.cue_used is None
        assert fb.remodel is False


def test_assessment_acknowledgements_reveal_nothing_by_wording():
    """A pre-test that reacts to correctness trains the participant, and the
    post-test then measures the assessment as much as the training."""
    banned = ("correct", "right", "wrong", "not quite", "well done", "try again",
              "good", "almost", "listen", "the word is")
    for text in ASSESSMENT_ACKS:
        lowered = text.lower()
        for word in banned:
            assert word not in lowered, f"{text!r} leaks {word!r}"


def test_assessment_acknowledgements_are_similar_length():
    """Wildly uneven lengths would themselves become a cue over a session."""
    lengths = [len(text.split()) for text in ASSESSMENT_ACKS]
    assert max(lengths) - min(lengths) <= 3


# --- recording quality ------------------------------------------------------

def test_a_normal_word_is_usable():
    quality = assess_quality(_tone(1.0), SR)
    assert quality.verdict == "ok"
    assert quality.usable
    assert quality.advice is None


@pytest.mark.parametrize("waveform, expected", [
    (np.zeros(SR, dtype=np.float32), "silent"),
    (np.zeros(0, dtype=np.float32), "silent"),
])
def test_silence_is_caught(waveform, expected):
    assert assess_quality(waveform, SR).verdict == expected


def test_a_distant_microphone_reads_as_quiet():
    assert assess_quality(_tone(1.0, amplitude=0.004), SR).verdict == "quiet"


def test_a_distorting_recording_reads_as_clipped():
    assert assess_quality(_clipped(), SR).verdict == "clipped"


def test_a_clipped_of_the_2026_09_15_kind_is_not_called_ok():
    """The pilot batch contained a two-second clip of clucking and one of a
    bystander conversation, and nothing in the stored row said so."""
    assert assess_quality(_tone(0.1), SR).verdict == "short"
    assert assess_quality(_tone(5.0), SR, max_speech_s=4.0).verdict == "long"


def test_every_unusable_verdict_offers_actionable_advice():
    """Shown to the researcher, who can move a microphone. A verdict with no
    advice is just a scolding."""
    for waveform, bounds in (
        (np.zeros(SR, dtype=np.float32), {}),
        (_tone(1.0, amplitude=0.004), {}),
        (_clipped(), {}),
        (_tone(0.1), {}),
        (_tone(5.0), {"max_speech_s": 4.0}),
    ):
        quality = assess_quality(np.asarray(waveform, dtype=np.float32), SR, **bounds)
        assert not quality.usable
        assert quality.advice, quality.verdict


def test_quality_is_reported_even_for_a_silent_clip():
    """-inf loudness must not reach JSON or SQL; the API converts it to null."""
    quality = assess_quality(np.zeros(SR, dtype=np.float32), SR)
    assert quality.peak == 0.0
    assert quality.duration_s == pytest.approx(1.0)


# --- test item set ----------------------------------------------------------

def test_test_category_is_separate_from_the_training_lists(monkeypatch):
    """Generalisation to untrained words is what distinguishes learning from
    memorising twelve words, so the test set cannot be a training list."""
    monkeypatch.setenv("STUDY_LIST_A_CATEGORY_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("STUDY_LIST_B_CATEGORY_ID", "22222222-2222-2222-2222-222222222222")
    monkeypatch.setenv("STUDY_TEST_CATEGORY_ID", "33333333-3333-3333-3333-333333333333")
    lists = study_design.configured_lists()
    assert lists["test"] not in (lists["A"], lists["B"])


def test_missing_test_category_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("STUDY_TEST_CATEGORY_ID", raising=False)
    with pytest.raises(study_design.ListsNotConfigured) as excinfo:
        study_design.test_category_id()
    assert "STUDY_TEST_CATEGORY_ID" in str(excinfo.value)
