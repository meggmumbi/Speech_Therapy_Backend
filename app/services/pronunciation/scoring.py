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
from .gop import (PhoneScore, aggregate_score, blank_weights,
                  compute_phone_scores, greedy_phone_decode, phone_posteriors,
                  utterance_confidence, word_score)
from .lexicon import ResourceUnavailable, normalize_text
from .references import Reference, ReferenceSource, reference_for
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
    reference_source: str | None = None   # which lexicon layer supplied the target
    reference_needs_review: bool = False  # true when the target is a g2p prediction
    transcript: str | None = None         # ASR transcript, when the client sent one
    transcript_matches: bool | None = None


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
    frame_weights: np.ndarray,
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
        phone_log_probs, spans, list(variant), phone_to_id, config.gop_floor,
        frame_weights=frame_weights,
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


def transcript_matches_target(transcript: str | None, target: str,
                              reference: Reference | None) -> bool | None:
    """Did the client's ASR hear the target word?

    ``None`` when no transcript was sent. Matching is on normalised text, and
    also accepts a transcript that is a homophone of the target under the
    reference lexicon -- "colonel" heard as "kernel" is the right word said
    right, and marking it wrong is the kind of failure that makes participants
    stop trusting the robot.
    """
    if transcript is None:
        return None
    heard = normalize_text(transcript)
    if not heard:
        return False
    if heard == target:
        return True
    # A single-word target heard as one word: compare pronunciations.
    if reference is not None and len(heard.split()) == 1:
        try:
            heard_ref = reference_for(heard, accent="en-GB")
        except Exception:  # noqa: BLE001 - lexicon trouble must not fail scoring
            heard_ref = None
        if heard_ref is not None:
            target_forms = {tuple(strip_stress(x) for x in v)
                            for v in reference.variants}
            heard_forms = {tuple(strip_stress(x) for x in v)
                           for v in heard_ref.variants}
            if target_forms & heard_forms:
                return True
    return False


def _classify(
    score: float,
    diagnoses: Sequence[PhoneDiagnosis],
    stress: StressAnalysis | None,
    config: PipelineConfig,
    transcript_match: bool | None = None,
    phone_scores: Sequence[PhoneScore] = (),
) -> Verdict:
    """Decide the verdict from the acoustic evidence, with an ASR safety net.

    The acoustic path decides on its own merits first. A matching ASR
    transcript can then *rescue* an attempt the acoustics called wrong, but a
    non-matching transcript can never push one toward wrong.

    That asymmetry is deliberate. Telling a volunteer they mispronounced a word
    they said correctly is the worst failure this system can have -- it makes
    them stop trusting the feedback, and it inflates H1's "incorrect first
    attempt" denominator with attempts that were never incorrect. The client's
    recogniser is good at word identity, so when it agrees the right word was
    said and the acoustics are not catastrophic, the attempt counts as correct.

    Letting the transcript rescue but not condemn also keeps the acoustic
    measure primary: the graded score reported for H2 is untouched by this, and
    the agreement rate between the two signals is itself worth reporting as
    part of validating the instrument.
    """
    t = config.thresholds
    segmental_errors = [d for d in diagnoses if d.kind != "weak"]

    if score >= t.correct and not segmental_errors:
        # Correct segmentally; a stress error still makes the word wrong, and
        # is the one the learner most needs told.
        if stress is not None and stress.is_error:
            return "stress_error"
        return "correct"

    supported = 0.0
    if phone_scores:
        supported = sum(
            1 for p in phone_scores if p.score >= t.phone_error
        ) / len(phone_scores)

    if (config.trust_transcript and transcript_match
            and supported >= config.transcript_rescue_min_phone_fraction):
        # The recogniser heard the target word and the audio supports most of
        # its phones: do not call this wrong.
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
    transcript: str | None = None,
) -> AttemptScore:
    """Score one spoken attempt at ``word``.

    ``waveform`` is mono float32 in ``[-1, 1]`` at ``sample_rate``. Decoding and
    resampling belong to the transport layer, not here, so that this function
    stays testable without an audio codec.

    ``transcript`` is the client's ASR output, when available. It is used only
    as a guard against false negatives -- never to lower a score. See
    :func:`_classify`.
    """
    timings = Timings()
    target = normalize_text(word)

    try:
        with timings.stage("lexicon"):
            reference = reference_for(target, accent=config.accent)
    except ResourceUnavailable as exc:
        return _gated(target, "unscorable", str(exc), 0.0, timings, config)
    if reference is None:
        return _gated(target, "unscorable",
                      f"no pronunciation known for {target!r}", 0.0, timings, config)

    return score_phone_sequence(target, reference.variants, waveform,
                                sample_rate, model, config, timings,
                                reference=reference, transcript=transcript)


def score_phone_sequence(
    label: str,
    variants: Sequence[Sequence[str]],
    waveform: np.ndarray,
    sample_rate: int,
    model: AcousticModel,
    config: PipelineConfig = DEFAULT_CONFIG,
    timings: Timings | None = None,
    reference: Reference | None = None,
    transcript: str | None = None,
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
        # How much phone evidence each frame carries, from the FULL matrix --
        # the blank column is gone from phone_log_probs by construction.
        frame_weights = blank_weights(emissions.log_probs, emissions.blank_id)
        confidence = utterance_confidence(phone_log_probs, frame_weights)
    if confidence < config.thresholds.confidence_gate:
        return _gated(target, "gated",
                      f"recogniser confidence {confidence:.2f} below gate",
                      confidence, timings, config)

    with timings.stage("forced_align"):
        best = None
        for variant in variants:
            scored = _score_variant(emissions, variant, config,
                                    phone_log_probs, phone_to_id,
                                    frame_weights)
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
        # BEEP variants carry no stress marks, so the expected stress pattern
        # comes from the reference's CMUdict-derived sequence when its length
        # matches the aligned variant. Without that check a length mismatch
        # would silently pair the wrong vowels together.
        stress_reference = list(expected)
        if reference is not None and reference.stress is not None:
            if len(reference.stress) == len(expected):
                stress_reference = list(reference.stress)
        stress = analyse_stress(
            waveform, sample_rate, spans, stress_reference,
            emissions.frame_stride_s,
        )

    with timings.stage("classify"):
        verdict_score = aggregate_score(
            phone_scores, config.verdict_aggregation,
            duration_weighted=config.duration_weighted_score,
            quantile=config.verdict_quantile, k=config.verdict_worst_k,
        )
        diagnoses = _diagnose(phone_scores, ops, config)
        heard_target = transcript_matches_target(transcript, target, reference)
        verdict = _classify(verdict_score, diagnoses, stress, config,
                            transcript_match=heard_target,
                            phone_scores=phone_scores)

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
        reference_source=reference.source.value if reference else None,
        reference_needs_review=bool(reference and reference.needs_review),
        transcript=transcript,
        transcript_matches=heard_target,
        timings=timings,
        provenance=config.provenance(),
    )
