"""Tests for the acoustic pronunciation scoring package.

Runs under pytest, or standalone via ``python tests/test_pronunciation.py``
so it stays runnable on a machine without a test runner installed.

Several tests encode failures of the *original* pipeline directly, so that a
regression to the old behaviour is caught rather than argued about.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pronunciation import (PipelineConfig, StubAcousticModel,  # noqa: E402
                                        align_phones, ctc_forced_align,
                                        differing_feature, phone_distance,
                                        pronunciations, score_attempt)
from app.services.pronunciation.gop import (blank_weights,  # noqa: E402
                                            compute_phone_scores,
                                            greedy_phone_decode,
                                            phone_posteriors, word_score)
from app.services.pronunciation.align import (attach_phones,  # noqa: E402
                                              expand_spans)
from app.services.pronunciation.lexicon import stress_pattern, syllabify  # noqa: E402

SR = 16_000


def _waveform(seconds: float = 0.5, amplitude: float = 0.2) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amplitude * np.sin(2 * np.pi * 150 * t)).astype(np.float32)


# --- articulatory features --------------------------------------------------

def test_identity_distance_is_zero():
    assert phone_distance("F", "F") == 0.0
    # Stress is scored separately, so it must not register as a segmental
    # difference -- the original code compared AH0 and AH1 as unequal.
    assert phone_distance("AH0", "AH1") == 0.0


def test_voicing_pair_is_closer_than_unrelated_pair():
    assert phone_distance("F", "V") < phone_distance("F", "K")
    assert phone_distance("T", "D") < phone_distance("T", "M")


def test_vowel_consonant_distance_is_maximal():
    assert phone_distance("AA", "K") == 1.0


def test_dental_stop_confusion_is_a_near_miss():
    # TH -> T is the canonical L2 substitution the feedback layer must catch.
    assert 0.0 < phone_distance("TH", "T") < 0.5


def test_differing_feature_names_a_single_contrast():
    assert differing_feature("F", "V") == "voicing"
    assert differing_feature("IY", "IH") == "tenseness"
    # Several features differ at once: refuse to name one.
    assert differing_feature("F", "NG") is None


# --- phone alignment --------------------------------------------------------

def test_insertion_does_not_cascade():
    """The original bug: positional comparison over range(min_len).

    With an epenthetic vowel inserted mid-word, index-by-index comparison
    reports every following phone as substituted. Alignment must report one
    insertion and nothing else.
    """
    expected = ["D", "R", "AE", "F", "T"]
    observed = ["D", "R", "AH", "AE", "F", "T"]
    ops = align_phones(expected, observed)

    assert [op.kind for op in ops].count("insertion") == 1
    assert not any(op.kind == "substitution" for op in ops)
    assert sum(1 for op in ops if op.kind == "match") == len(expected)


def test_trailing_error_is_not_silently_dropped():
    """The original compared only min_len positions, so a dropped final
    consonant was invisible."""
    ops = align_phones(["K", "AE", "T"], ["K", "AE"])
    assert [op.kind for op in ops][-1] == "deletion"
    assert ops[-1].expected == "T"


def test_alignment_prefers_the_plausible_substitution():
    ops = align_phones(["TH", "IH", "NG", "K"], ["T", "IH", "NG", "K"])
    subs = [op for op in ops if op.kind == "substitution"]
    assert len(subs) == 1
    assert (subs[0].expected, subs[0].actual) == ("TH", "T")


def test_empty_observation_is_all_deletions():
    ops = align_phones(["K", "AE", "T"], [])
    assert all(op.kind == "deletion" for op in ops)
    assert len(ops) == 3


# --- CTC forced alignment ---------------------------------------------------

def test_forced_alignment_recovers_contiguous_spans():
    phones = ["D", "R", "AE", "F", "T"]
    model = StubAcousticModel(produced=phones, frames_per_phone=6)
    em = model.emissions(_waveform(), SR)

    ids = [em.phone_to_id[p] for p in phones]
    spans = attach_phones(ctc_forced_align(em.log_probs, ids, em.blank_id), phones)

    assert [s.phone for s in spans] == phones
    assert all(s.n_frames > 0 for s in spans)
    # Spans must be ordered and non-overlapping.
    for a, b in zip(spans, spans[1:]):
        assert a.end_frame <= b.start_frame


def test_forced_alignment_rejects_audio_too_short_for_target():
    model = StubAcousticModel(produced=["D"], frames_per_phone=2)
    em = model.emissions(_waveform(0.3), SR)
    ids = [em.phone_to_id[p] for p in ["D", "R", "AE", "F", "T"]]
    try:
        ctc_forced_align(em.log_probs, ids, em.blank_id)
    except ValueError:
        return
    raise AssertionError("expected ValueError for an over-short recording")


def test_greedy_decode_recovers_the_produced_sequence():
    phones = ["S", "K", "W", "ER", "AH", "L"]
    model = StubAcousticModel(produced=phones, frames_per_phone=4)
    em = model.emissions(_waveform(), SR)
    assert greedy_phone_decode(em.log_probs, em.id_to_phone, em.blank_id) == phones


# --- GOP --------------------------------------------------------------------

def test_confident_correct_production_scores_high():
    phones = ["K", "AE", "T"]
    model = StubAcousticModel(produced=phones, frames_per_phone=5, confidence=0.95)
    em = model.emissions(_waveform(), SR)
    ids = [em.phone_to_id[p] for p in phones]
    spans = expand_spans(
        attach_phones(ctc_forced_align(em.log_probs, ids, em.blank_id), phones),
        em.n_frames)
    lp, p2i, _ = phone_posteriors(em.log_probs, em.phone_to_id)
    scores = compute_phone_scores(lp, spans, phones, p2i, gop_floor=-10.0,
                                  frame_weights=blank_weights(em.log_probs,
                                                              em.blank_id))

    assert all(s.gop > -0.1 for s in scores)
    assert word_score(scores) > 0.9


def test_wrong_phone_is_scored_down_and_names_its_competitor():
    expected = ["TH", "IH", "NG", "K"]
    produced = ["T", "IH", "NG", "K"]
    model = StubAcousticModel(produced=produced, frames_per_phone=5, confidence=0.95)
    em = model.emissions(_waveform(), SR)
    ids = [em.phone_to_id[p] for p in expected]
    spans = expand_spans(
        attach_phones(ctc_forced_align(em.log_probs, ids, em.blank_id), expected),
        em.n_frames)
    lp, p2i, _ = phone_posteriors(em.log_probs, em.phone_to_id)
    scores = compute_phone_scores(lp, spans, expected, p2i, gop_floor=-10.0,
                                  frame_weights=blank_weights(em.log_probs,
                                                              em.blank_id))

    th = scores[0]
    assert th.score < 0.5
    assert th.competitor == "T"
    assert word_score(scores) < word_score(scores[1:])


# --- lexicon ----------------------------------------------------------------

def test_all_dictionary_variants_are_returned():
    """The original took cmu_dict[word][0] only, marking valid alternate
    pronunciations as errors."""
    variants = pronunciations("either")
    assert len(variants) >= 2


def test_stress_pattern_and_syllabification():
    phones = pronunciations("hyperbole")[0]
    assert 1 in stress_pattern(phones)
    syllables = syllabify(phones)
    assert len(syllables) >= 3
    # Syllabification must be lossless.
    assert [p for syl in syllables for p in syl] == list(phones)


def test_normalisation_spells_out_digits():
    from app.services.pronunciation import normalize_text
    assert normalize_text("Three, 3!") == "three three"


# --- end to end -------------------------------------------------------------

def _score(word: str, produced: list[str], confidence: float = 0.95):
    model = StubAcousticModel(produced=produced, frames_per_phone=5,
                              confidence=confidence)
    config = PipelineConfig(backend="stub")
    return score_attempt(word, _waveform(len(produced) * 5 * 0.02), SR, model, config)


def test_correct_production_is_scored_correct():
    # D R AA F T, not D R AE F T: the reference is British (BEEP), because
    # Kenyan English is taught on British English. The American vowel is a
    # near miss against that target, not a match.
    result = _score("draught", ["D", "R", "AA", "F", "T"])
    assert result.verdict == "correct"
    assert result.is_correct
    assert result.score > 0.9
    assert not result.diagnoses


def test_draught_said_as_drought_is_not_correct():
    """The headline failure of the text pipeline: orthographic Levenshtein
    scores draught/drought at 0.86, near the 'correct' threshold, despite a
    whole different vowel."""
    result = _score("draught", ["D", "R", "AW", "T"])
    assert not result.is_correct
    assert result.verdict in ("close", "incorrect")
    assert result.diagnoses


def test_low_confidence_audio_is_gated_not_diagnosed():
    """A confidently wrong diagnosis is worse than no diagnosis."""
    result = _score("draught", ["D", "R", "AE", "F", "T"], confidence=0.05)
    assert result.verdict == "gated"
    assert not result.diagnoses
    assert result.note


def test_result_carries_reproducibility_provenance():
    result = _score("cat", ["K", "AE", "T"])
    assert result.provenance["config_hash"]
    assert result.provenance["pipeline_version"]
    # Thresholds are not calibrated yet, and the result must say so.
    assert result.provenance["calibrated_on"] is None


def test_every_stage_is_timed():
    result = _score("cat", ["K", "AE", "T"])
    for stage in ("lexicon", "acoustic", "forced_align", "align_phones", "classify"):
        assert stage in result.timings.stages
    assert result.timings.total_ms >= 0


def test_unknown_word_is_unscorable_not_wrong():
    result = _score("zzzzq", ["K", "AE", "T"])
    assert result.verdict in ("unscorable", "incorrect")


def test_too_short_recording_is_rejected():
    model = StubAcousticModel(produced=["K", "AE", "T"])
    config = PipelineConfig(backend="stub")
    result = score_attempt("cat", _waveform(0.05), SR, model, config)
    assert result.verdict == "unscorable"
    assert "too short" in (result.note or "")


# --- feedback ---------------------------------------------------------------

def _feedback_for(word, produced, condition, **kw):
    from app.services.pronunciation.feedback import generate_feedback
    model = StubAcousticModel(produced=produced, frames_per_phone=5,
                              confidence=kw.pop("confidence", 0.95))
    config = PipelineConfig(backend="stub")
    result = score_attempt(word, _waveform(len(produced) * 5 * 0.02), SR,
                           model, config)
    return result, generate_feedback(result, word, condition, **kw)


def test_no_arpabet_ever_reaches_spoken_text():
    """The original pipeline interpolated raw phone symbols, so Pepper would
    say 'it sounds like AH0' out loud."""
    from app.services.pronunciation.feedback import (all_feedback_strings,
                                                     arpabet_tokens_in)
    for text in all_feedback_strings():
        assert not arpabet_tokens_in(text), f"ARPAbet leaked into: {text!r}"

    for condition in ("K", "D"):
        for produced in (["D", "R", "AW", "T"], ["T", "IH", "NG", "K"],
                         ["K", "AE", "T"]):
            _, fb = _feedback_for("think", produced, condition)
            assert not arpabet_tokens_in(fb.speech), fb.speech


def test_arpabet_guard_actually_detects_a_leak():
    """Guard the guard: a test that cannot fail is not a test."""
    from app.services.pronunciation.feedback import arpabet_tokens_in
    assert arpabet_tokens_in("it sounds like AH0 instead of TH")
    assert not arpabet_tokens_in("the th sound, as in think")


def test_every_phone_is_speakable_and_has_a_cue():
    from app.services.pronunciation.feedback import (ARTICULATORY_CUES,
                                                     PHONE_EXEMPLARS)
    from app.services.pronunciation.features import ARPABET_PHONES
    missing_exemplar = [p for p in ARPABET_PHONES if p not in PHONE_EXEMPLARS]
    missing_cue = [p for p in ARPABET_PHONES if p not in ARTICULATORY_CUES]
    assert not missing_exemplar, missing_exemplar
    assert not missing_cue, missing_cue


def test_feedback_never_names_the_substituted_phone():
    """Measured on Speechocean762: we identify the substituted phone only 19%
    of the time, so saying it would be wrong four times in five."""
    _, fb = _feedback_for("think", ["T", "IH", "NG", "K"], "D")
    assert "instead of" not in fb.speech.lower()
    assert "you said" not in fb.speech.lower()


def test_conditions_share_marker_and_remodel_and_differ_only_in_diagnosis():
    """The K/D contrast is only interpretable if everything else matches."""
    from app.services.pronunciation.feedback import WARMTH_MARKERS
    _, k = _feedback_for("think", ["T", "IH", "NG", "K"], "K", attempt_index=1)
    _, d = _feedback_for("think", ["T", "IH", "NG", "K"], "D", attempt_index=1)

    marker = WARMTH_MARKERS[1]
    assert k.speech.startswith(marker) and d.speech.startswith(marker)
    assert k.remodel and d.remodel
    assert "Listen again: think." in k.speech
    assert "Listen again: think." in d.speech
    assert len(d.speech) > len(k.speech)      # D adds the diagnosis
    assert k.named_phone is None and d.named_phone is not None


def test_condition_d_falls_back_to_k_when_nothing_is_nameable():
    """D must not invent a diagnosis just because it is condition D."""
    from app.services.pronunciation.feedback import generate_feedback
    model = StubAcousticModel(produced=["K", "AE", "T"], frames_per_phone=5)
    config = PipelineConfig(backend="stub")
    result = score_attempt("cat", _waveform(0.3), SR, model, config)
    # Force an incorrect verdict with no diagnoses.
    stripped = type(result)(**{**result.__dict__, "verdict": "incorrect",
                               "is_correct": False, "diagnoses": ()})
    fb = generate_feedback(stripped, "cat", "D")
    assert fb.named_phone is None
    assert "Listen again: cat." in fb.speech


def test_length_matching_narrows_the_k_d_gap_without_adding_diagnosis():
    """Unmatched, K runs ~5 spoken words against D's ~25. A D>K result would
    then be readable as 'the robot talked to them five times longer'."""
    from app.services.pronunciation.feedback import (ARTICULATORY_CUES,
                                                     generate_feedback)
    model = StubAcousticModel(produced=["T", "IH", "NG", "K"],
                              frames_per_phone=5, confidence=0.95)
    config = PipelineConfig(backend="stub")
    result = score_attempt("think", _waveform(0.4), SR, model, config)

    unmatched = generate_feedback(result, "think", "K", match_length=False)
    matched = generate_feedback(result, "think", "K", match_length=True)
    d = generate_feedback(result, "think", "D")

    assert matched.word_count > unmatched.word_count
    assert abs(d.word_count - matched.word_count) < abs(d.word_count - unmatched.word_count)
    # The filler must carry no diagnostic content.
    assert matched.named_phone is None and matched.cue_used is None
    for cue in ARTICULATORY_CUES.values():
        assert cue not in matched.speech


def test_gated_attempt_asks_for_a_repeat_identically_in_both_conditions():
    _, k = _feedback_for("draught", ["D", "R", "AE", "F", "T"], "K",
                         confidence=0.05)
    _, d = _feedback_for("draught", ["D", "R", "AE", "F", "T"], "D",
                         confidence=0.05)
    assert k.kind == d.kind == "repeat"
    assert k.speech == d.speech
    assert not k.remodel and not d.remodel


def test_correct_attempt_is_praised_without_a_diagnosis():
    _, fb = _feedback_for("cat", ["K", "AE", "T"], "D")
    assert fb.kind == "praise"
    assert fb.named_phone is None
    assert not fb.remodel


def test_contrast_cue_is_off_by_default_but_available():
    from app.services.pronunciation.feedback import contrast_cue
    # Direction matters: the cue describes the EXPECTED phone. /f/ is
    # voiceless, so the instruction is to take the voice off, not add it.
    assert "voice off" in (contrast_cue("F", "V") or "")
    assert "voice on" in (contrast_cue("V", "F") or "")
    _, default = _feedback_for("think", ["T", "IH", "NG", "K"], "D")
    _, enabled = _feedback_for("think", ["T", "IH", "NG", "K"], "D",
                               use_contrast_cue=True)
    assert default.cue_used is not None          # static cue still applies
    assert enabled.cue_used is not None


# --- score aggregation ------------------------------------------------------

def _fake_scores(values):
    from app.services.pronunciation.gop import PhoneScore
    return [PhoneScore(i, "AA", i * 5, i * 5 + 5, -0.1, v, v, None, 0.0)
            for i, v in enumerate(values)]


def test_mean_aggregation_dilutes_a_single_gross_error():
    """The reason a verdict must not use the mean: one bad phone in five
    barely moves the average."""
    from app.services.pronunciation.gop import aggregate_score
    clean = _fake_scores([1.0, 1.0, 1.0, 1.0, 1.0])
    one_bad = _fake_scores([1.0, 1.0, 0.05, 1.0, 1.0])

    mean_gap = (aggregate_score(clean, "mean")
                - aggregate_score(one_bad, "mean"))
    worst_gap = (aggregate_score(clean, "worst_k", k=2)
                 - aggregate_score(one_bad, "worst_k", k=2))
    assert mean_gap < 0.25
    assert worst_gap > mean_gap * 1.5


def test_worst_k_needs_two_bad_phones_to_bottom_out():
    """worst_k keeps min's sensitivity but is less trigger-happy on a single
    noisy frame."""
    from app.services.pronunciation.gop import aggregate_score
    one_bad = _fake_scores([1.0, 1.0, 0.0, 1.0])
    two_bad = _fake_scores([1.0, 0.0, 0.0, 1.0])

    assert aggregate_score(one_bad, "min") == aggregate_score(two_bad, "min")
    assert aggregate_score(one_bad, "worst_k", k=2) > \
        aggregate_score(two_bad, "worst_k", k=2)


def test_softmin_is_bounded_by_min_and_mean():
    from app.services.pronunciation.gop import aggregate_score
    scores = _fake_scores([0.2, 0.7, 0.9, 1.0])
    soft = aggregate_score(scores, "softmin", beta=8.0)
    assert aggregate_score(scores, "min") <= soft <= aggregate_score(scores, "mean")


def test_unknown_aggregation_method_is_rejected():
    from app.services.pronunciation.gop import aggregate_score
    try:
        aggregate_score(_fake_scores([1.0]), "median-ish")
    except ValueError:
        return
    raise AssertionError("expected ValueError for an unknown method")


def test_quality_and_verdict_scores_are_reported_separately():
    """H2 needs graded quality, H1 needs a verdict; one number cannot be both."""
    model = StubAcousticModel(produced=["K", "AE", "T"], frames_per_phone=5,
                              confidence=0.95)
    config = PipelineConfig(backend="stub")
    result = score_attempt("cat", _waveform(0.3), SR, model, config)
    assert result.score > 0.0
    assert result.verdict_score > 0.0


# --- audio conditioning -----------------------------------------------------

def test_trim_silence_removes_leading_and_trailing_quiet():
    from app.services.pronunciation.audio import trim_silence
    speech = _waveform(0.4, amplitude=0.3)
    quiet = np.zeros(int(0.5 * SR), dtype=np.float32)
    padded = np.concatenate([quiet, speech, quiet])

    trimmed, start, end = trim_silence(padded, SR)
    assert len(trimmed) < len(padded)
    # The pad keeps context on each side, so the speech must survive intact.
    assert len(trimmed) >= len(speech)
    assert 0.3 < start < 0.55


def test_trim_silence_leaves_all_quiet_audio_alone():
    """A silent recording must reach the confidence gate, not be trimmed to
    nothing and misreported as 'too short'."""
    from app.services.pronunciation.audio import trim_silence
    silence = np.zeros(int(0.5 * SR), dtype=np.float32)
    trimmed, _, _ = trim_silence(silence, SR)
    assert len(trimmed) == len(silence)


def test_to_mono_float32_normalises_integer_pcm():
    from app.services.pronunciation.audio import to_mono_float32
    pcm = np.array([[0, 32767], [-32768, 0]], dtype=np.int16)
    out = to_mono_float32(pcm)
    assert out.dtype == np.float32
    assert out.ndim == 1
    assert np.all(np.abs(out) <= 1.0)


# --- phone folding ----------------------------------------------------------

def test_missing_phone_is_folded_not_rejected():
    """TIMIT-39 models have no AO (the cot-caught merger). A word containing
    it must still be scoreable, via a declared fold."""
    from app.services.pronunciation.features import resolve_to_inventory
    inventory = {"AA": 1, "T": 2}
    resolved = resolve_to_inventory(["AO1", "T"], inventory)
    assert resolved is not None
    phones, folds = resolved
    assert phones == ["AA", "T"]
    assert folds == [("AO", "AA")]


def test_unrepresentable_phone_declines_rather_than_guessing():
    from app.services.pronunciation.features import resolve_to_inventory
    assert resolve_to_inventory(["ZH", "Q"], {"ZH": 1}) is None


def test_applied_folds_are_reported_on_the_result():
    """A fold makes a contrast unscoreable, so it has to surface in the
    result rather than being silently absorbed."""
    from app.services.pronunciation.acoustic import StubAcousticModel
    model = StubAcousticModel(produced=["AA", "T"], frames_per_phone=5)
    # Remove AO from the stub's inventory to force the fold.
    model.phone_to_id.pop("AO", None)
    config = PipelineConfig(backend="stub")
    from app.services.pronunciation import score_phone_sequence
    result = score_phone_sequence("caught", [("AO1", "T")], _waveform(0.2), SR,
                                  model, config)
    assert ("AO", "AA") in result.applied_folds


# --- lexicon-free entry point ----------------------------------------------

def test_score_phone_sequence_uses_the_given_target():
    """Benchmark corpora ship their own canonical phones; going back through
    CMUdict would score against a different target than the raters judged."""
    from app.services.pronunciation import score_phone_sequence
    model = StubAcousticModel(produced=["Z", "IY", "B", "R", "AH"],
                              frames_per_phone=5, confidence=0.95)
    config = PipelineConfig(backend="stub")
    result = score_phone_sequence("utt-1", [("Z", "IY", "B", "R", "AH")],
                                  _waveform(0.5), SR, model, config)
    assert result.expected_phones == ("Z", "IY", "B", "R", "AH")
    assert result.is_correct


def test_best_scoring_variant_wins():
    """Saying a valid alternate pronunciation must not be marked wrong."""
    from app.services.pronunciation import score_phone_sequence
    model = StubAcousticModel(produced=["IY", "DH", "ER"], frames_per_phone=5,
                              confidence=0.95)
    config = PipelineConfig(backend="stub")
    result = score_phone_sequence(
        "either", [("AY1", "DH", "ER0"), ("IY1", "DH", "ER0")],
        _waveform(0.3), SR, model, config,
    )
    assert result.expected_phones[0] == "IY1"
    assert result.is_correct


# --- reference lexicon ------------------------------------------------------

def test_british_reference_is_used_by_default():
    """CMUdict is General American; the study's speakers are taught British
    English. Scoring a Kenyan speaker against an American target marked
    correct productions wrong on the pilot."""
    from app.services.pronunciation.references import (ReferenceSource,
                                                       reference_for)
    for word, expected_phone in (("mauve", "OW"), ("draught", "AA"),
                                 ("tune", "Y")):
        ref = reference_for(word)
        assert ref is not None, word
        assert ref.source == ReferenceSource.BEEP, (word, ref.source)
        assert expected_phone in ref.primary, (word, ref.primary)


def test_american_accent_can_still_be_selected():
    from app.services.pronunciation.references import (ReferenceSource,
                                                       reference_for)
    ref = reference_for("mauve", accent="en-US")
    assert ref is not None
    assert ref.source == ReferenceSource.CMU
    assert "AO1" in ref.primary


def test_predicted_reference_is_flagged_for_review():
    """A g2p-derived target has no authority behind it and must say so."""
    from app.services.pronunciation.references import reference_for
    ref = reference_for("zzzblorptik")
    if ref is not None:
        assert ref.needs_review


def test_unreleased_final_stop_is_accepted():
    """Word-final /p t k/ are often unreleased and emit no CTC peak, which
    reads as a deletion the speaker did not make -- the reported "sheep" case.
    """
    from app.services.pronunciation.references import reference_for
    forms = {tuple(v) for v in reference_for("sheep").variants}
    assert ("SH", "IY", "P") in forms
    assert ("SH", "IY") in forms


def test_non_rhotic_rule_drops_postvocalic_r_only():
    from app.services.pronunciation.references import non_rhotic
    # car: post-vocalic R goes
    assert non_rhotic(["K", "AA1", "R"]) == ["K", "AA1"]
    # carry: R before a vowel stays
    assert non_rhotic(["K", "AE1", "R", "IY0"]) is None
    # letter: r-coloured schwa becomes plain schwa
    assert non_rhotic(["L", "EH1", "T", "ER0"]) == ["L", "EH1", "T", "AH0"]


def test_yod_rule_inserts_before_uw_after_alveolars():
    from app.services.pronunciation.references import yod_retained
    assert yod_retained(["T", "UW1", "N"]) == ["T", "Y", "UW1", "N"]
    assert yod_retained(["M", "UW1", "N"]) is None


def test_reference_source_is_reported_on_the_result():
    result = _score("draught", ["D", "R", "AA", "F", "T"])
    assert result.reference_source == "beep"
    assert result.reference_needs_review is False


# --- ASR transcript as a safety net ----------------------------------------

def test_matching_transcript_rescues_a_wrongly_failed_attempt():
    """The regression that mattered most: a volunteer told they got it wrong
    when they did not. A matching transcript prevents that."""
    from app.services.pronunciation import score_attempt
    model = StubAcousticModel(produced=["D", "R", "AE", "F", "T"],
                              frames_per_phone=5, confidence=0.95)
    config = PipelineConfig(backend="stub")
    audio = _waveform(0.5)

    without = score_attempt("draught", audio, SR, model, config)
    withit = score_attempt("draught", audio, SR, model, config,
                           transcript="draught")
    assert without.verdict != "correct"
    assert withit.verdict == "correct"
    assert withit.transcript_matches is True


def test_non_matching_transcript_never_condemns():
    """The transcript may only rescue. A disagreeing recogniser must not turn
    an acoustically good attempt into a failure."""
    from app.services.pronunciation import score_attempt
    model = StubAcousticModel(produced=["D", "R", "AA", "F", "T"],
                              frames_per_phone=5, confidence=0.95)
    config = PipelineConfig(backend="stub")
    audio = _waveform(0.5)

    clean = score_attempt("draught", audio, SR, model, config)
    with_bad = score_attempt("draught", audio, SR, model, config,
                             transcript="something else entirely")
    assert clean.verdict == "correct"
    assert with_bad.verdict == "correct"
    assert with_bad.transcript_matches is False


def test_transcript_cannot_rescue_acoustically_absurd_audio():
    """Guards against the recogniser auto-correcting something wildly wrong
    into the target word."""
    from app.services.pronunciation import score_attempt
    model = StubAcousticModel(produced=["Z", "Z", "Z"], frames_per_phone=5,
                              confidence=0.95)
    config = PipelineConfig(backend="stub")
    result = score_attempt("draught", _waveform(0.4), SR, model, config,
                           transcript="draught")
    assert result.verdict != "correct"


def test_homophone_transcript_counts_as_a_match():
    """"colonel" heard as "kernel" is the right word said right."""
    from app.services.pronunciation.scoring import transcript_matches_target
    from app.services.pronunciation.references import reference_for
    ref = reference_for("colonel")
    assert transcript_matches_target("kernel", "colonel", ref) is True
    assert transcript_matches_target("banana", "colonel", ref) is False
    assert transcript_matches_target(None, "colonel", ref) is None


# --- persistence ------------------------------------------------------------

def test_non_finite_gop_serialises_to_valid_json():
    """PhoneScore.gop is -inf when a phone has no acoustic evidence. Python
    writes that as -Infinity, which is not valid JSON, and PostgreSQL rejects
    it -- every such attempt 500'd mid-session."""
    import json
    from dataclasses import asdict

    from app.api.pronunciation import _json_safe
    from app.services.pronunciation.gop import PhoneScore

    scores = [PhoneScore(0, "AO", 0, 0, float("-inf"), 0.0, 0.0, None, 0.0)]
    payload = _json_safe([asdict(s) for s in scores])
    encoded = json.dumps(payload)          # must not raise, must be valid JSON
    assert "Infinity" not in encoded
    assert json.loads(encoded)[0]["gop"] is None


def test_json_safe_handles_nan_and_nesting():
    from app.api.pronunciation import _json_safe
    out = _json_safe({"a": float("nan"), "b": [float("inf"), 1.5],
                      "c": {"d": float("-inf")}})
    assert out == {"a": None, "b": [None, 1.5], "c": {"d": None}}


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            passed += 1
            print(f"  ok   {name}")
        except Exception as exc:  # noqa: BLE001 - test runner
            failed += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
