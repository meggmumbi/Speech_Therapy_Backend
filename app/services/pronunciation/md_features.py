"""Per-phone features for the supervised mispronunciation-detection layer.

Lives in the package, not in the training script, because training and
inference must compute features *identically*. A feature extractor duplicated
between an offline script and the serving path is one edit away from silently
scoring production audio with a different representation than the model was
fitted on, and nothing would fail loudly when it happened.

The feature set follows the GOP-feature literature (Hu et al. 2015; Shi et al.
2020; Vidal et al. 2024): the classical GOP plus the quantities it discards --
how confident the frames were, how close the runner-up phone came, how long the
phone actually lasted against its own norm, and how much acoustic evidence
there was at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .align import FrameSpan

FEATURE_NAMES: tuple[str, ...] = (
    "gop",              # log-posterior ratio: the classical score
    "mean_log_post",    # mean log P(target | frame)
    "mean_post",        # the same in probability space
    "margin",           # target minus best competitor, log space
    "competitor_post",  # how strong the best rival phone was
    "entropy",          # mean frame entropy; a confident frame is worth more
    "min_log_post",     # worst single frame, which an average hides
    "n_frames",         # realised duration
    "duration_z",       # duration against this phone's own mean
    "evidence",         # total non-blank weight in the span
    "position",         # 0 word-initial, 1 medial, 2 final
)


@dataclass(frozen=True)
class DurationStats:
    """Per-phone duration norms, fitted on the training corpus.

    Needed at inference so ``duration_z`` means the same thing it did during
    training. Saved alongside the model rather than recomputed.
    """

    means: dict[str, float]
    stds: dict[str, float]

    def z(self, phone: str, n_frames: int) -> float:
        std = self.stds.get(phone, 0.0)
        if std <= 0:
            return 0.0
        return (n_frames - self.means.get(phone, float(n_frames))) / std


def phone_feature_vector(
    phone_log_probs: np.ndarray,
    frame_weights: np.ndarray,
    span: FrameSpan,
    phone_id: int,
    phone: str,
    position: int,
    duration_stats: DurationStats | None = None,
) -> list[float] | None:
    """Features for one aligned phone, or ``None`` when it cannot be scored.

    ``phone_log_probs`` is the phone-only renormalised matrix from
    :func:`gop.phone_posteriors`; ``frame_weights`` is
    :func:`gop.blank_weights` on the full CTC matrix.
    """
    lo, hi = span.start_frame, span.end_frame
    if hi <= lo:
        return None
    window = phone_log_probs[lo:hi]
    weights = np.asarray(frame_weights[lo:hi], dtype=np.float64)
    evidence = float(weights.sum())
    if evidence < 1e-6:
        return None

    target_lp = window[:, phone_id]
    best_lp = window.max(axis=1)
    entropy = -np.sum(np.exp(window) * window, axis=1)

    # Best competitor excluding the target: "what else did it sound like",
    # which the plain GOP denominator conflates with the target itself.
    masked = window.copy()
    masked[:, phone_id] = -np.inf
    competitor_lp = masked.max(axis=1)

    def weighted(values: np.ndarray) -> float:
        return float(np.average(values, weights=weights))

    n_frames = hi - lo
    duration_z = duration_stats.z(phone, n_frames) if duration_stats else 0.0

    return [
        weighted(target_lp - best_lp),
        weighted(target_lp),
        weighted(np.exp(target_lp)),
        weighted(target_lp - competitor_lp),
        weighted(np.exp(competitor_lp)),
        weighted(entropy),
        float(target_lp.min()),
        float(n_frames),
        float(duration_z),
        evidence,
        float(position),
    ]


def word_positions(n_phones: int) -> list[int]:
    """Position code for each phone of a single word."""
    if n_phones <= 0:
        return []
    if n_phones == 1:
        return [0]
    return [0] + [1] * (n_phones - 2) + [2]
