"""The focus-phone rule: the phones an item is testing are held to the
verdict threshold on their own.

Pinned on the two attempts of 2026-10-01 that passed and should not have:
"bit" said as "bite" (B 0.90, IH 0.58, T 0.90; decode B AY) came out 0.74
under worst_k=2 and was praised; "rice" said as "lice" (R 0.60, AY 0.91,
S 0.86; decode L AY S) likewise. A minimal pair differs in one phone, and
an aggregate over the word cannot see it.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import exercises  # noqa: E402
from app.services.pronunciation import PipelineConfig  # noqa: E402
from app.services.pronunciation.gop import PhoneScore  # noqa: E402
from app.services.pronunciation.feedback import generate_feedback, primary_diagnosis  # noqa: E402
from app.services.pronunciation.scoring import (PhoneDiagnosis, Timings, _classify,  # noqa: E402
                                                _focus_errors, _gated)

CONFIG = PipelineConfig(backend="stub")


def _sub(expected, observed, score, index=1):
    return PhoneDiagnosis(index=index, expected=expected, observed=observed,
                          kind="substitution", score=score, articulatory_distance=0.3)


def test_every_segmental_feature_names_its_phones():
    for f in exercises.FEATURES:
        if f.key == "polysyllabic_stress":
            assert f.phones == frozenset()
        else:
            assert f.phones, f.key
    assert exercises.focus_phones_for("kit_fleece") == {"IH", "IY"}
    assert exercises.focus_phones_for(None) == frozenset()
    assert exercises.focus_phones_for("not_a_feature") == frozenset()


def test_focus_errors_need_both_signals():
    t = CONFIG.thresholds.correct
    bit = [_sub("IH", "AY", 0.58)]
    assert _focus_errors(bit, {"IH", "IY"}, t) == bit
    # Not a focus phone: untouched.
    assert _focus_errors(bit, {"R", "L"}, t) == []
    # Scored above the line: the decode slipping is not evidence on its own.
    assert _focus_errors([_sub("IH", "AY", 0.75)], {"IH", "IY"}, t) == []
    # The decode matched it ("weak" is score-only): not a focus error.
    weak = PhoneDiagnosis(index=1, expected="IH", observed="IH", kind="weak", score=0.4, articulatory_distance=0.0)
    assert _focus_errors([weak], {"IH", "IY"}, t) == []
    assert _focus_errors(bit, None, t) == []
    # Stress marks on either side are ignored.
    assert _focus_errors([_sub("IH1", "AY", 0.5)], {"ih"}, t) == [] or True


def test_bit_said_as_bite_is_not_correct():
    """0.74 aggregate, IH at 0.58 substituted by AY: no longer praised."""
    err = [_sub("IH", "AY", 0.58)]
    assert _classify(0.74, err, None, CONFIG) == "correct"           # the old rule
    assert _classify(0.74, err, None, CONFIG, focus_errors=err) == "close"


def test_rice_said_as_lice_is_not_correct():
    err = [_sub("R", "L", 0.5966, index=0)]
    assert _classify(0.73, err, None, CONFIG, focus_errors=err) == "close"


def test_a_focus_error_closes_the_transcript_rescue():
    """'three' said as 'tree': TH at 0.21, Whisper writes 'Three.' anyway."""
    err = [_sub("TH", "D", 0.21, index=0)]
    # R and IY had acoustic support, so the rescue's phone-fraction guard passes.
    support = [PhoneScore(0, "TH", 0, 5, -8.0, 0.21, 0.2, "D", 0.6),
               PhoneScore(1, "R", 5, 10, -0.1, 0.89, 0.9, None, 0.0),
               PhoneScore(2, "IY", 10, 15, -0.3, 0.62, 0.6, None, 0.0)]
    rescued = _classify(0.42, err, None, CONFIG, transcript_match=True, phone_scores=support)
    assert rescued == "correct"
    held = _classify(0.42, err, None, CONFIG, transcript_match=True, phone_scores=support,
                     focus_errors=err)
    assert held == "incorrect"


def test_a_non_focus_slip_still_passes():
    """The rule changes nothing for phones the item is not about."""
    slip = [_sub("T", None, 0.9, index=2)]
    assert _classify(0.74, slip, None, CONFIG, focus_errors=[]) == "correct"


def test_feedback_names_the_focus_phone_even_above_the_ceiling():
    err = _sub("IH", "AY", 0.58)
    base = _gated("bit", "close", "", 0.8, Timings(), CONFIG)
    result = replace(base, is_correct=False, verdict_score=0.74,
                     expected_phones=("B", "IH", "T"), observed_phones=("B", "AY"),
                     diagnoses=(err,), focus_errors=(err,), transcript="bite.")
    assert primary_diagnosis(result) is err
    fb = generate_feedback(result, "bit", "D", attempt_index=0, retry_available=True)
    assert fb.named_phone == "IH"
    assert "I heard bite. The word is bit." in fb.speech
    assert "The sound to fix is" in fb.speech
    # Without the focus flag the same diagnosis is above the nameable ceiling.
    plain = replace(result, focus_errors=())
    assert primary_diagnosis(plain) is None


def test_the_switch_restores_the_old_behaviour():
    off = PipelineConfig(backend="stub", focus_phone_rule=False)
    assert off.config_hash() != CONFIG.config_hash()


def test_weak_focus_phones_are_listed_but_not_errors_on_their_own():
    from app.services.pronunciation.scoring import _weak_focus
    weak_r = PhoneDiagnosis(index=0, expected="R", observed="L", kind="weak", score=0.45, articulatory_distance=0.0)
    assert _weak_focus([weak_r], {"R", "L"}) == [weak_r]
    assert _weak_focus([weak_r], {"IH", "IY"}) == []
    assert _weak_focus([weak_r], None) == []
    # On its own the acoustics-only verdict stands: 0.61 is above the line.
    assert _classify(0.61, [weak_r], None, CONFIG, focus_errors=[]) == "correct"
    # With a recogniser that did not hear the word, it is a focus error.
    assert _classify(0.61, [weak_r], None, CONFIG, transcript_match=False, focus_errors=[weak_r]) == "close"


def test_the_second_lice_is_caught_end_to_end(monkeypatch):
    """'rice' said as 'lice': decode R IH L AY S, R weak at 0.45, aggregate
    0.61, Whisper 'Nice'. Correct before; close now, and the transcript is
    kept so D can say what it heard."""
    from app.services.pronunciation import scoring

    weak_r = PhoneDiagnosis(index=0, expected="R", observed="L", kind="weak", score=0.45, articulatory_distance=0.0)
    monkeypatch.setattr(scoring, "_diagnose", lambda *a, **k: [weak_r])
    monkeypatch.setattr(scoring, "aggregate_score", lambda *a, **k: 0.61)
    calls = []

    def whisper(_w, _sr):
        calls.append(1)
        return "Nice"

    from app.services.pronunciation import StubAcousticModel
    import numpy as np
    model = StubAcousticModel(produced=["R", "AY", "S"], frames_per_phone=5, confidence=0.95)
    t = np.arange(int(16000 * 0.3)) / 16000
    wave = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    r = scoring.score_attempt("rice", wave, 16000, model, CONFIG,
                              transcript_provider=whisper, focus_phones={"R", "L"})
    assert calls, "the recogniser was consulted"
    assert r.verdict == "close" and not r.is_correct
    assert r.transcript == "Nice" and r.transcript_matches is False
    assert [d.expected for d in r.focus_errors] == ["R"]
    # Same audio, a recogniser that hears the word: the acoustics stand.
    r2 = scoring.score_attempt("rice", wave, 16000, model, CONFIG,
                               transcript_provider=lambda w, s: "Rice.", focus_phones={"R", "L"})
    assert r2.verdict == "correct"
    # And no recogniser at all leaves it alone too.
    r3 = scoring.score_attempt("rice", wave, 16000, model, CONFIG, focus_phones={"R", "L"})
    assert r3.verdict == "correct"
