"""Goodness of Pronunciation scoring from frame posteriors.

This replaces the original ``compute_similarity``, which ran Levenshtein over
*orthographic strings* -- the spelling of the ASR transcript against the
spelling of the target. That metric scores ``draught``/``drought`` at 0.86
despite a whole different vowel, and ``colonel``/``kernel`` at 0.14 despite
their being homophones. It measures how a recogniser spells, not how a learner
speaks.

The GOP formulation here is the posterior approximation of Witt & Young (2000):
for each expected phone p aligned to frames F,

    GOP(p) = (1/|F|) * sum_{t in F} [ log P(p | o_t) - max_q log P(q | o_t) ]

which is <= 0, with 0 meaning the acoustic model considered p the most likely
phone at every frame it was supposed to occupy.

The GOP -> ``[0, 1]`` mapping and every threshold downstream of it are
*uncalibrated placeholders* until they are fitted on Speechocean762 and on the
rater-adjudicated sample. They are kept in ``config.py`` with provenance, not
scattered as magic numbers, precisely so that calibration is a config change
and the published operating point is auditable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from .align import FrameSpan


@dataclass(frozen=True)
class PhoneScore:
    """Per-phone acoustic evidence for one expected phone."""

    index: int
    phone: str                  # expected phone, stress digit retained
    start_frame: int
    end_frame: int
    gop: float                  # log-posterior-ratio, <= 0
    score: float                # calibrated 0-1
    mean_posterior: float       # mean P(expected phone | frame) over the span
    competitor: str | None      # phone the model found most likely instead
    competitor_posterior: float

    @property
    def realised(self) -> bool:
        """False when forced alignment gave this phone no frames at all."""
        return self.end_frame > self.start_frame


def gop_to_score(gop: float, tau: float) -> float:
    """Map a GOP value (<= 0) onto ``[0, 1]``.

    ``exp(gop / tau)`` is monotone, bounded, and has no free intercept, so the
    only fitted quantity is the temperature ``tau``. Calibrate it on
    Speechocean762 against expert 0-2 phone scores before reporting anything.
    """
    if not math.isfinite(gop):
        return 0.0
    return float(min(1.0, math.exp(gop / tau)))


def compute_phone_scores(
    log_probs: np.ndarray,
    spans: Sequence[FrameSpan],
    expected_phones: Sequence[str],
    phone_to_id: Mapping[str, int],
    tau: float,
) -> list[PhoneScore]:
    """Score every expected phone over the frames forced alignment gave it.

    ``log_probs`` is the ``(T, V)`` log-softmax emission matrix; ``spans`` come
    from :func:`align.ctc_forced_align` on the same matrix, so the two are
    guaranteed to be frame-compatible.
    """
    id_to_phone = {i: p for p, i in phone_to_id.items()}
    frame_best = log_probs.argmax(axis=1)
    scores: list[PhoneScore] = []

    for span, phone in zip(spans, expected_phones):
        pid = phone_to_id.get(_lookup_key(phone, phone_to_id))
        if pid is None:
            # Expected phone outside the model's inventory: no acoustic
            # evidence is possible, so say so rather than scoring it 0.
            scores.append(PhoneScore(
                span.token_index, phone, span.start_frame, span.end_frame,
                float("-inf"), 0.0, 0.0, None, 0.0,
            ))
            continue

        if span.n_frames <= 0:
            # Deleted phone: the aligner never emitted it.
            scores.append(PhoneScore(
                span.token_index, phone, span.start_frame, span.end_frame,
                float("-inf"), 0.0, 0.0, None, 0.0,
            ))
            continue

        window = log_probs[span.start_frame:span.end_frame]
        target_lp = window[:, pid]
        best_lp = window.max(axis=1)
        gop = float(np.mean(target_lp - best_lp))
        mean_post = float(np.mean(np.exp(target_lp)))

        # The competitor is the phone the model preferred across this span --
        # "what it heard instead" -- which diagnoses the error independently of
        # the free phone decode.
        competitor_id = int(np.bincount(frame_best[span.start_frame:span.end_frame],
                                        minlength=log_probs.shape[1]).argmax())
        competitor = id_to_phone.get(competitor_id)
        if competitor_id == pid:
            competitor = None
        comp_post = float(np.mean(np.exp(window[:, competitor_id])))

        scores.append(PhoneScore(
            span.token_index, phone, span.start_frame, span.end_frame,
            gop, gop_to_score(gop, tau), mean_post, competitor, comp_post,
        ))
    return scores


def _lookup_key(phone: str, phone_to_id: Mapping[str, int]) -> str:
    """Resolve an expected phone against the model's label inventory.

    Acoustic models are trained on stress-free labels, so ``AH0`` must map to
    the model's ``AH``. Tries the phone as given, then stress-stripped.
    """
    if phone in phone_to_id:
        return phone
    from .features import strip_stress
    return strip_stress(phone)


def word_score(phone_scores: Sequence[PhoneScore], duration_weighted: bool = True) -> float:
    """Mean aggregation: the graded *pronunciation quality* of an attempt.

    Duration weighting is on by default so a long stressed vowel counts for
    more than a 20 ms stop burst, which matches how raters weight errors. The
    unweighted mean is available for comparability with published GOP
    baselines that report it.

    This is the right aggregation for H2, whose DV is a graded improvement in
    pronunciation score. It is the *wrong* aggregation for a correct/incorrect
    verdict -- see :func:`aggregate_score` and ``verdict_score``.
    """
    if not phone_scores:
        return 0.0
    if not duration_weighted:
        return float(np.mean([s.score for s in phone_scores]))
    weights = np.array([max(s.end_frame - s.start_frame, 1) for s in phone_scores],
                       dtype=np.float64)
    values = np.array([s.score for s in phone_scores], dtype=np.float64)
    return float(np.average(values, weights=weights))


def aggregate_score(
    phone_scores: Sequence[PhoneScore],
    method: str = "worst_k",
    *,
    duration_weighted: bool = True,
    quantile: float = 0.15,
    k: int = 2,
    beta: float = 8.0,
) -> float:
    """Aggregate phone scores into one utterance score by ``method``.

    A word is mispronounced if *any* phone is wrong, so a mean is the wrong
    summary for a verdict: one bad phone in a five-phone word barely moves the
    average, and a correct word and a word with a single gross error end up
    near-indistinguishable. Measured on Speechocean762, mean aggregation gave
    *worse* word-level head precision (~0.40) than the phone-level scores it
    was built from (~0.68), which is the signature of exactly this dilution.

    Methods:

    ``mean``      duration-weighted mean -- graded quality (H2's DV).
    ``min``       the single worst phone. Maximally sensitive, and to a single
                  noisy frame as much as to a real error.
    ``quantile``  the ``quantile``-th percentile; robust min for long words.
    ``worst_k``   mean of the ``k`` lowest-scoring phones. The default: keeps
                  min's sensitivity to a localised error while needing two
                  bad phones rather than one to bottom out, which is what
                  makes it less trigger-happy on a single bad frame.
    ``softmin``   smooth minimum, differentiable, ``beta`` controls sharpness.
    """
    if not phone_scores:
        return 0.0
    values = np.array([s.score for s in phone_scores], dtype=np.float64)

    if method == "mean":
        return word_score(phone_scores, duration_weighted)
    if method == "min":
        return float(values.min())
    if method == "quantile":
        return float(np.quantile(values, quantile))
    if method == "worst_k":
        n = max(1, min(k, len(values)))
        return float(np.sort(values)[:n].mean())
    if method == "softmin":
        # -log(mean(exp(-beta * s))) / beta; shifted for numerical stability.
        shifted = -beta * (values - values.min())
        return float(values.min() - np.log(np.mean(np.exp(shifted))) / beta)
    raise ValueError(f"unknown aggregation method {method!r}")


def utterance_confidence(log_probs: np.ndarray) -> float:
    """Mean top-1 frame posterior: the input to the confidence gate.

    When this falls below the configured threshold the robot should ask the
    speaker to repeat rather than diagnose. Confidently wrong feedback is the
    single worst failure mode for a tutoring system, and the participants in
    the first study were already hinting at it in their accent complaints.
    """
    if log_probs.size == 0:
        return 0.0
    return float(np.mean(np.exp(log_probs.max(axis=1))))


def greedy_phone_decode(
    log_probs: np.ndarray,
    id_to_phone: Mapping[int, str],
    blank_id: int = 0,
) -> list[str]:
    """Unconstrained CTC decode: what the model heard, ignoring the target.

    Deliberately free -- forced alignment tells us how well the *expected*
    phones fit, but only an unconstrained decode can say what was actually
    produced, which is what diagnostic feedback needs to report back to the
    learner. Greedy rather than beam search: on single words the difference is
    negligible and the cost is zero.
    """
    best = log_probs.argmax(axis=1)
    out: list[str] = []
    previous = -1
    for token in best:
        token = int(token)
        if token != previous and token != blank_id:
            phone = id_to_phone.get(token)
            if phone:
                out.append(phone)
        previous = token
    return out
