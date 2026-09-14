"""The supervised mispronunciation-detection layer, at inference time.

The pipeline's original scorer was the classical GOP: a posterior ratio, with
no supervision anywhere in it. Measured on Speechocean762 (47,368 test phones)
that reaches AUC 0.693 -- which is exactly where Vidal et al. (CACM 2024) place
the unsupervised "PR" approach, at 0.67-0.71. Their supervised "MD" approach,
a small layer fitted on non-native speech with human pronunciation labels,
reaches 0.80-0.83. Fitting one on Speechocean762's expert phone scores
reproduced that: **AUC 0.830, and Cost down from 0.839 to 0.678**.

Cost here is ``2 x FPR + FNR`` (Vidal et al.): a false correction counts twice
a missed error, because a tutor that corrects correct speech teaches the
learner to distrust it. That is the metric the threshold is fitted to.

The layer degrades gracefully: if no model file is present the pipeline falls
back to GOP scoring, which still works, just less well. Nothing here is
required for the system to run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .md_features import FEATURE_NAMES, DurationStats

log = logging.getLogger(__name__)

MODEL_PATH = Path("data/md_layer.joblib")


@dataclass
class MDLayer:
    """A fitted detector: features in, probability of correct pronunciation out."""

    model: object                 # sklearn classifier with predict_proba
    scaler: object                # sklearn StandardScaler
    inventory: tuple[str, ...]    # phone order for the identity one-hot
    duration_stats: DurationStats
    threshold: float              # global operating point, fitted on dev Cost
    per_phone_threshold: dict[str, float]
    metrics: dict                 # held-out numbers, for provenance

    def phone_index(self, phone: str) -> int | None:
        try:
            return self.inventory.index(phone)
        except ValueError:
            return None

    def score(self, features: list[float], phone: str) -> float | None:
        """Probability the phone was pronounced *correctly*, in ``[0, 1]``.

        Returns ``None`` for a phone outside the training inventory, so the
        caller can fall back to GOP rather than score it against a one-hot
        column that does not exist.
        """
        index = self.phone_index(phone)
        if index is None:
            return None
        row = np.zeros((1, len(FEATURE_NAMES) + len(self.inventory)))
        row[0, :len(FEATURE_NAMES)] = features
        row[0, len(FEATURE_NAMES) + index] = 1.0
        scaled = self.scaler.transform(row)
        # The classifier predicts P(mispronounced); the pipeline speaks in
        # terms of correctness everywhere else, so invert once, here.
        return float(1.0 - self.model.predict_proba(scaled)[0, 1])

    def threshold_for(self, phone: str) -> float:
        """Score at or below which the phone counts as mispronounced."""
        return 1.0 - self.per_phone_threshold.get(phone, self.threshold)


_layer: MDLayer | None = None
_attempted = False


def load_md_layer(path: Path = MODEL_PATH) -> MDLayer | None:
    """Load the fitted layer once, or ``None`` if it has not been trained.

    A missing model is not an error: the pipeline runs on GOP without it, and
    saying so once at start-up is more useful than failing.
    """
    global _layer, _attempted
    if _attempted:
        return _layer
    _attempted = True

    if not path.exists():
        log.info("no MD layer at %s; scoring with GOP only "
                 "(train one with scripts/train_md_layer.py)", path)
        return None
    try:
        import joblib
        payload = joblib.load(path)
        _layer = MDLayer(
            model=payload["model"],
            scaler=payload["scaler"],
            inventory=tuple(payload["inventory"]),
            duration_stats=DurationStats(payload["duration_means"],
                                         payload["duration_stds"]),
            threshold=float(payload["threshold"]),
            per_phone_threshold=dict(payload.get("per_phone_threshold", {})),
            metrics=dict(payload.get("metrics", {})),
        )
        log.info("MD layer loaded: %d phones, held-out AUC %.3f, Cost %.3f",
                 len(_layer.inventory),
                 _layer.metrics.get("auc", float("nan")),
                 _layer.metrics.get("cost", float("nan")))
    except Exception:  # noqa: BLE001 - a bad model must not stop the server
        log.exception("could not load the MD layer; falling back to GOP")
        _layer = None
    return _layer


def reset() -> None:
    """Forget the cached layer. For tests and for reloading a retrained model."""
    global _layer, _attempted
    _layer = None
    _attempted = False
