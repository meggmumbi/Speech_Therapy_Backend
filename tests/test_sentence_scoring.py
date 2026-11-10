"""A word read inside a sentence is judged on that word, and D says what it heard.

Last week's recordings: every read-aloud item came back "incorrect" with a
transcript that was the sentence read perfectly. The scorer had been handed the
target word as the reference and the whole sentence as the audio, and aligned
twenty-five phones against six. These pin the fix, and the feedback that the
supervisor could not tell apart from K.

The bug itself is not reproduced here: the stub acoustic model scores too
leniently to fail the old path. The evidence is the re-score of the stored
recordings of 2026-09-18 through the fixed path, 13/42 correct before and
40/42 after, with the two remaining failures being a real cup-for-cap
substitution the recogniser also heard.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pronunciation import (PipelineConfig, StubAcousticModel,  # noqa: E402
                                        score_attempt, score_sentence)
from app.services.pronunciation.feedback import (K_FILLERS,  # noqa: E402
                                                 generate_feedback, heard_instead,
                                                 perception_feedback)
from app.services.pronunciation.scoring import transcript_matches_target  # noqa: E402

SR = 16_000


def _waveform(seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


# "He ate a banana for lunch" as the stub model would decode a clean British
# reading. BEEP gives banana its PALM vowel, B AH N AA N AH; an American AE
# in the fixture would be the fixture's error, not the scorer's.
SENTENCE = "He ate a banana for lunch."
CLEAN = ["HH", "IY", "EY", "T", "AH", "B", "AH", "N", "AA", "N", "AH",
         "F", "AO", "R", "L", "AH", "N", "CH"]


def _score(produced, **kw):
    model = StubAcousticModel(produced=produced, frames_per_phone=5, confidence=0.95)
    config = PipelineConfig(backend="stub")
    return score_sentence(SENTENCE, "banana", _waveform(len(produced) * 5 * 0.02),
                          SR, model, config, **kw)


# --- the bug --------------------------------------------------------------

def test_a_sentence_read_correctly_is_correct():
    result = _score(CLEAN)
    assert result.verdict == "correct", result.note
    assert result.word == "banana"


def test_judgement_covers_the_target_word_only():
    """expected_phones is the target; observed_phones stays the whole decode so
    an audit can see the sentence was heard."""
    result = _score(CLEAN)
    assert [p.rstrip("012") for p in result.expected_phones] == ["B", "AH", "N", "AA", "N", "AH"]
    assert len(result.observed_phones) == len(CLEAN)
    offsets = sorted(s.index for s in result.phone_scores)
    assert offsets == list(range(5, 11)), "phone scores must be the target's, at its offsets"


def test_an_error_in_a_carrier_word_does_not_fail_the_target():
    """"pot" for "port" in "The ship is leaving the port" is not a ship error."""
    wrong_carrier = list(CLEAN)
    wrong_carrier[0] = "SH"
    assert _score(wrong_carrier).verdict == "correct"


def test_an_error_in_the_target_word_still_fails():
    """Two clear substitutions inside the target: the verdict aggregates the
    two worst phones, so one slip is tolerated and two are not."""
    wrong_target = list(CLEAN)
    wrong_target[5] = "P"                        # b -> p
    wrong_target[8] = "IY"                       # PALM vowel -> FLEECE
    assert _score(wrong_target).verdict != "correct"


def test_a_sentence_gets_the_longer_ceiling():
    config = PipelineConfig(backend="stub")
    assert config.max_sentence_seconds > config.max_audio_seconds
    long_clean = CLEAN * 3
    seconds = len(long_clean) * 5 * 0.02
    assert seconds > config.max_audio_seconds
    model = StubAcousticModel(produced=long_clean, frames_per_phone=5, confidence=0.95)
    result = score_sentence(SENTENCE, "banana", _waveform(seconds), SR, model, config)
    assert "too long" not in (result.note or "")


def test_a_target_missing_from_the_sentence_is_refused_not_guessed():
    bad = score_sentence("He ate lunch.", "banana", _waveform(1.0), SR,
                         StubAcousticModel(produced=CLEAN), PipelineConfig(backend="stub"))
    assert bad.verdict == "unscorable"
    assert "not in the sentence" in (bad.note or "")


# --- transcript rescue understands sentences --------------------------------

def test_a_sentence_transcript_containing_the_target_matches():
    assert transcript_matches_target("He ate a banana for lunch.", "banana", None) is True


def test_a_sentence_transcript_without_the_target_does_not():
    assert transcript_matches_target("He ate a mango for lunch.", "banana", None) is False


# --- what D says --------------------------------------------------------------

class _Result:
    def __init__(self, transcript):
        self.transcript = transcript


def test_d_names_the_word_it_heard_in_a_single_word_item():
    assert heard_instead(_Result("Tink."), "think") == "tink"
    assert heard_instead(_Result("cup"), "cap") == "cup"
    assert heard_instead(_Result("light"), "right") == "light"


def test_d_places_the_heard_word_inside_a_sentence():
    heard = heard_instead(_Result("He wore a red cup to school."), "cap",
                          sentence="He wore a red cap to school.")
    assert heard == "cup"


def test_d_says_nothing_when_the_target_was_heard():
    assert heard_instead(_Result("He ate a banana for lunch."), "banana",
                         sentence=SENTENCE) is None


def test_d_says_nothing_for_a_non_word():
    """A wrong contrast is worse than a vague one. "Bnnna" is not a word to
    tell someone they said."""
    assert heard_instead(_Result("bnnna"), "banana") is None


def test_d_says_nothing_when_the_replacement_is_not_one_word():
    assert heard_instead(_Result("He wore a red cap to school please."), "cap",
                         sentence="He wore a red cap to school.") is None


def test_d_contrast_reaches_the_spoken_feedback_and_k_never_does():
    model = StubAcousticModel(produced=["T", "IH", "NG", "K"], frames_per_phone=5,
                              confidence=0.95)
    config = PipelineConfig(backend="stub")
    result = score_attempt("think", _waveform(0.4), SR, model, config)
    with_transcript = type(result)(**{**result.__dict__, "transcript": "Tink."})

    d = generate_feedback(with_transcript, "think", "D")
    k = generate_feedback(with_transcript, "think", "K")
    assert "I heard tink. The word is think." in d.speech
    assert "tink" not in k.speech
    assert "Listen again: think." in d.speech and "Listen again: think." in k.speech


def test_d_contrast_alone_beats_falling_back_to_k():
    """Nothing nameable at phone level, but the recogniser heard a real
    different word: that is a diagnosis, and D must not read K's filler."""
    model = StubAcousticModel(produced=["K", "AE", "T"], frames_per_phone=5)
    result = score_attempt("cat", _waveform(0.3), SR, model, PipelineConfig(backend="stub"))
    stripped = type(result)(**{**result.__dict__, "verdict": "incorrect",
                               "is_correct": False, "diagnoses": (),
                               "transcript": "cut"})
    fb = generate_feedback(stripped, "cat", "D")
    assert "I heard cut. The word is cat." in fb.speech
    assert not any(filler in fb.speech for filler in K_FILLERS)


# --- tapped items in D ----------------------------------------------------

def test_a_wrong_tap_in_d_is_told_the_answer_and_in_k_is_not():
    d = perception_feedback(False, 0, condition="D", reveal="The word you heard was ship.")
    k = perception_feedback(False, 0, condition="K", reveal="The word you heard was ship.")
    assert "ship" in d.speech
    assert "ship" not in k.speech
    assert d.condition == "D" and k.condition == "K"


def test_a_right_tap_is_praised_the_same_in_both_conditions():
    d = perception_feedback(True, 2, condition="D", reveal="irrelevant")
    k = perception_feedback(True, 2, condition="K", reveal="irrelevant")
    assert d.speech == k.speech
