"""Orchestration: one attempt's audio in, a scored diagnosis out.

Stage order, and why:

1. **Validate duration.** Reject recordings too short or too long to be a
   single-word attempt before spending any compute on them.
2. **Emissions.** One forward pass. This is the only expensive stage.
3. **Confidence gate.** If the model is not confident enough about *anything*
   it heard, stop here and ask the speaker to repeat. Everything downstream is
   arithmetic on the emission matrix, so gating first costs nothing and
   prevents the confidently-wrong feedback that is this system's worst failure
   mode.
4. **Forced alignment + GOP, per dictionary variant.** Score against every
   accepted pronunciation and keep the best; a learner who says the valid
   alternate pronunciation of ``mischievous`` is right, not wrong.
5. **Free phone decode + alignment.** What was actually produced, aligned to
   what was expected with articulatory substitution costs.
6. **Stress.** Separate from segmental scoring, because it is a separate
   pedagogical event with separate feedback.
7. **Classification.** Config-driven thresholds, no magic numbers.

Every stage is timed. The latency table this produces is what tells you
whether the p95 target holds on the study machine, rather than trusting an
estimate.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Literal, Sequence

import numpy as np

from .acoustic import AcousticModel, Emissions
from .audio import trim_silence
from .align import (PhoneOp, align_phones, attach_phones, ctc_forced_align,
                    expand_spans)
from .config import DEFAULT_CONFIG, PipelineConfig
from .features import resolve_to_inventory, strip_stress
from .gop import (PhoneScore, aggregate_score, compute_phone_scores,
                  greedy_phone_decode, phone_posteriors,
                  utterance_confidence, word_score)
from .lexicon import ResourceUnavailable, normalize_text, pronunciations
from .prosody import StressAnalysis, analyse_stress

Verdict = Literal["correct", "close", "stress_error", "incorrect", "gated", "unscorable"]


@dataclass
class Timings:
    """Per-stage wall-clock, milliseconds. Reported per attempt."""

    stages: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = (time.perf_counter() - started) * 1000.0

    @property
    def total_ms(self) -> float:
        return sum(self.stages.values())


@dataclass(frozen=True)
class PhoneDiagnosis:
    """One phone the learner is judged to have got wrong, and how."""

    index: int
    expected: str
    observed: str | None          # None for a deletion
    kind: Literal["substitution", "deletion", "insertion", "weak"]
    score: float                  # 0-1 acoustic score for the expected phone
    articulatory_distance: float  # 0-1; how far the observed phone is


@dataclass(frozen=True)
class AttemptScore:
    """Complete, persistable result of scoring one attempt."""

    word: str
    verdict: Verdict
    is_correct: bool
    score: float                          # 0-1 graded pronunciation quality (H2's DV)
    verdict_score: float                  # worst-phone aggregate; drives is_correct (H1's DV)
    confidence: float
    expected_phones: tuple[str, ...]      # best-matching dictionary variant
    observed_phones: tuple[str, ...]      # free decode
    phone_scores: tuple[PhoneScore, ...]
    alignment: tuple[PhoneOp, ...]
    diagnoses: tuple[PhoneDiagnosis, ...]
    stress: StressAnalysis | None
    n_variants_considered: int
    applied_folds: tuple[tuple[str, str], ...]   # phone contrasts the model cannot represent
    timings: Timings
    provenance: dict[str, str | None]
    note: str | None = None               # why an attempt was gated/unscorable


def _gated(word: str, verdict: Verdict, note: str, confidence: float,
           timings: Timings, config: PipelineConfig) -> AttemptScore:
    return AttemptScore(
        word=word, verdict=verdict, is_correct=False, score=0.0,
        verdict_score=0.0,
        confidence=confidence, expected_phones=(), observed_phones=(),
        phone_scores=(), alignment=(), diagnoses=(), stress=None,
        n_variants_considered=0, applied_folds=(), timings=timings,
        provenance=config.provenance(), note=note,
    )


def _score_variant(
    emissions: Emissions,
    variant: tuple[str, ...],
    config: PipelineConfig,
    phone_log_probs: np.ndarray,
    phone_to_id: dict[str, int],
) -> tuple[float, list[PhoneScore], list, list[tuple[str, str]]] | None:
    """Forced-align and GOP-score one dictionary variant. None if unalignable.

    Alignment runs on the full CTC matrix, because it needs the blank symbol.
    Scoring runs on the phone-only matrix, because GOP is defined over phone
    posteriors -- see gop.phone_posteriors.
    """
    resolution = resolve_to_inventory(list(variant), emissions.phone_to_id)
    if resolution is None:
        # A phone with no representation in the model's inventory, not even a
        # documented fold: decline rather than substitute something plausible.
        return None
    segmental, folds = resolution
    target_ids = [emissions.phone_to_id[p] for p in segmental]
    try:
        spans = ctc_forced_align(emissions.log_probs, [int(i) for i in target_ids],
                                 blank_id=emissions.blank_id)
    except ValueError:
        return None
    spans = attach_phones(spans, segmental)
    # CTC peaks are one frame wide; widen them to real phone segments before
    # averaging anything over them.
    spans = expand_spans(spans, emissions.n_frames)
    phone_scores = compute_phone_scores(
        phone_log_probs, spans, list(variant), phone_to_id, config.gop_tau,
    )
    return (
        word_score(phone_scores, config.duration_weighted_score),
        phone_scores,
        spans,
        folds,
    )


def _diagnose(
    phone_scores: Sequence[PhoneScore],
    ops: Sequence[PhoneOp],
    config: PipelineConfig,
) -> list[PhoneDiagnosis]:
    """Merge acoustic evidence with the alignment into per-phone diagnoses.

    Two independent signals have to agree before an error is reported:
    the expected phone scored badly *and* the alignment or the competitor says
    what replaced it. Requiring both is what keeps precision high enough for
    the feedback to be worth speaking aloud.
    """
    by_index = {s.index: s for s in phone_scores}
    diagnoses: list[PhoneDiagnosis] = []

    for op in ops:
        if op.kind == "match":
            continue
        if op.kind == "insertion":
            diagnoses.append(PhoneDiagnosis(
                index=op.actual_index if op.actual_index is not None else -1,
                expected="", observed=op.actual, kind="insertion",
                score=0.0, articulatory_distance=op.cost,
            ))
            continue
        idx = op.expected_index if op.expected_index is not None else -1
        acoustic = by_index.get(idx)
        score = acoustic.score if acoustic else 0.0
        kind: Literal["substitution", "deletion", "insertion", "weak"] = (
            "deletion" if op.kind == "deletion" else "substitution"
        )
        diagnoses.append(PhoneDiagnosis(
            index=idx, expected=op.expected or "", observed=op.actual,
            kind=kind, score=score, articulatory_distance=op.cost,
        ))

    # Phones the alignment matched but the acoustics scored badly: the learner
    # produced roughly the right phone, poorly. Reported as "weak" so feedback
    # can say "closer" rather than naming a substitution that did not happen.
    diagnosed = {d.index for d in diagnoses}
    for s in phone_scores:
        if s.index in diagnosed:
            continue
        if s.score < config.thresholds.phone_error:
            diagnoses.append(PhoneDiagnosis(
                index=s.index, expected=s.phone, observed=s.competitor,
                kind="weak", score=s.score, articulatory_distance=0.0,
            ))

    diagnoses.sort(key=lambda d: d.index)
    return diagnoses


def _classify(
    score: float,
    diagnoses: Sequence[PhoneDiagnosis],
    stress: StressAnalysis | None,
    config: PipelineConfig,
) -> Verdict:
    t = config.thresholds
    segmental_errors = [d for d in diagnoses if d.kind != "weak"]

    if score >= t.correct and not segmental_errors:
        # Correct segmentally; a stress error still makes the word wrong, and
        # is the one the learner most needs told.
        if stress is not None and stress.is_error:
            return "stress_error"
        return "correct"
    if stress is not None and stress.is_error and not segmental_errors:
        return "stress_error"
    if score >= t.close:
        return "close"
    return "incorrect"


def score_attempt(
    word: str,
    waveform: np.ndarray,
    sample_rate: int,
    model: AcousticModel,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> AttemptScore:
    """Score one spoken attempt at ``word``.

    ``waveform`` is mono float32 in ``[-1, 1]`` at ``sample_rate``. Decoding and
    resampling belong to the transport layer, not here, so that this function
    stays testable without an audio codec.
    """
    timings = Timings()
    target = normalize_text(word)

    try:
        with timings.stage("lexicon"):
            variants = pronunciations(target)
    except ResourceUnavailable as exc:
        return _gated(target, "unscorable", str(exc), 0.0, timings, config)
    if not variants:
        return _gated(target, "unscorable",
                      f"no pronunciation known for {target!r}", 0.0, timings, config)

    return score_phone_sequence(target, variants, waveform, sample_rate,
                                model, config, timings)


def score_phone_sequence(
    label: str,
    variants: Sequence[Sequence[str]],
    waveform: np.ndarray,
    sample_rate: int,
    model: AcousticModel,
    config: PipelineConfig = DEFAULT_CONFIG,
    timings: Timings | None = None,
) -> AttemptScore:
    """Score audio against an explicit set of accepted phone sequences.

    The lexicon-free core of :func:`score_attempt`. Split out because
    benchmark corpora (Speechocean762 among them) ship their own canonical
    phone annotation, and going back through CMUdict would score the pipeline
    against a *different* target than the one the human raters judged --
    turning a lexicon mismatch into an apparent scoring error.

    ``variants`` is one or more accepted pronunciations; the best-scoring one
    is kept.
    """
    timings = timings or Timings()
    target = label
    variants = tuple(tuple(v) for v in variants)
    if not variants:
        return _gated(target, "unscorable", "no target phone sequence given",
                      0.0, timings, config)

    if config.trim_silence:
        with timings.stage("trim"):
            waveform, _, _ = trim_silence(
                waveform, sample_rate,
                threshold_db=config.silence_threshold_db,
            )

    duration = len(waveform) / sample_rate if sample_rate else 0.0
    if duration < config.min_audio_seconds:
        return _gated(target, "unscorable",
                      f"recording too short ({duration:.2f}s)", 0.0, timings, config)
    if duration > config.max_audio_seconds:
        return _gated(target, "unscorable",
                      f"recording too long ({duration:.2f}s)", 0.0, timings, config)

    with timings.stage("acoustic"):
        emissions = model.emissions(waveform, sample_rate)

    with timings.stage("confidence"):
        # Everything downstream of here scores over phone posteriors, not the
        # raw CTC matrix in which blank wins nearly every frame.
        phone_log_probs, phone_to_id, _ = phone_posteriors(
            emissions.log_probs, emissions.phone_to_id)
        confidence = utterance_confidence(phone_log_probs)
    if confidence < config.thresholds.confidence_gate:
        return _gated(target, "gated",
                      f"recogniser confidence {confidence:.2f} below gate",
                      confidence, timings, config)

    with timings.stage("forced_align"):
        best = None
        for variant in variants:
            scored = _score_variant(emissions, variant, config,
                                    phone_log_probs, phone_to_id)
            if scored is None:
                continue
            if best is None or scored[0] > best[0]:
                best = (scored[0], scored[1], scored[2], variant, scored[3])
    if best is None:
        return _gated(target, "unscorable",
                      "no dictionary variant could be aligned to the audio",
                      confidence, timings, config)
    utterance_score, phone_scores, spans, expected, folds = best

    with timings.stage("decode"):
        observed = greedy_phone_decode(
            emissions.log_probs, emissions.id_to_phone, emissions.blank_id,
        )

    with timings.stage("align_phones"):
        ops = align_phones([strip_stress(p) for p in expected], observed,
                           gap_cost=config.gap_cost)

    with timings.stage("stress"):
        stress = analyse_stress(
            waveform, sample_rate, spans, list(expected), emissions.frame_stride_s,
        )

    with timings.stage("classify"):
        verdict_score = aggregate_score(
            phone_scores, config.verdict_aggregation,
            duration_weighted=config.duration_weighted_score,
            quantile=config.verdict_quantile, k=config.verdict_worst_k,
        )
        diagnoses = _diagnose(phone_scores, ops, config)
        verdict = _classify(verdict_score, diagnoses, stress, config)

    return AttemptScore(
        word=target,
        verdict=verdict,
        is_correct=verdict == "correct",
        score=round(utterance_score, 4),
        verdict_score=round(verdict_score, 4),
        confidence=round(confidence, 4),
        expected_phones=tuple(expected),
        observed_phones=tuple(observed),
        phone_scores=tuple(phone_scores),
        alignment=tuple(ops),
        diagnoses=tuple(diagnoses),
        stress=stress,
        n_variants_considered=len(variants),
        applied_folds=tuple(folds),
        timings=timings,
        provenance=config.provenance(),
    )
