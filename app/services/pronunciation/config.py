"""Pipeline configuration, versioning and the provenance of every threshold.

Everything the scorer's behaviour depends on lives here, and
:attr:`PipelineConfig.config_hash` is stored on each attempt alongside
:data:`PIPELINE_VERSION`. That is what makes "re-run the analysis from the raw
audio and reproduce every published number" a checkable claim rather than an
aspiration.

Decision thresholds are **provisional**, not final: the verdict thresholds are
fitted on Speechocean762 and the rest are still placeholders. Speechocean762 is
a different population and task from the study, so all of them must be refitted
on the rater-adjudicated sample before any published number depends on them.
``Thresholds.provenance`` records the current state, ``calibrated_on`` stays
``None`` until that refit, and :meth:`PipelineConfig.is_calibrated` reports it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

PIPELINE_VERSION = "2.0.0-dev"

# Candidate acoustic models, to be benchmarked on Speechocean762 before the
# study. None is the default yet: the choice is an empirical question, and
# picking one here without measuring would be exactly the kind of unjustified
# design decision the reviewers objected to.
#
# The study machine is a 4-core 15 W laptop with no usable GPU, so a base-size
# (~95 M) model is the working assumption and the large models are the GPU
# fallback. Note that a *character*-CTC model such as wav2vec2-base-960h can
# only provide word-level forced alignment -- it has no phone posteriors and
# cannot support GOP -- so any candidate must be verified phone-level by
# `AcousticModel.describe()` before use.
MODEL_CANDIDATES = {
    # key: (hf id, size, label inventory, ARPAbet coverage as inspected)
    "arpa39-base": ("mostafaashahin/wav2vec2-base-timit-phoneme-arpa-39",
                    "base/95M", "ARPAbet-39 (lowercase)",
                    "38/39 - lacks AO, folded to AA"),
    "l2-large": ("slplab/wav2vec2-large-robust-L2-english-phoneme-recognition",
                 "large/300M", "ARPAbet + explicit *_err labels",
                 "39/39; trained on L2 English"),
    "timit-xlsr": ("vitouphy/wav2vec2-xls-r-300m-timit-phoneme",
                   "large/300M", "IPA incl. diphthongs", "via IPA mapping"),
    "espeak-ipa": ("facebook/wav2vec2-lv-60-espeak-cv-ft",
                   "large/315M", "multilingual IPA (392 labels)",
                   "via IPA mapping"),
}


@dataclass(frozen=True)
class Thresholds:
    """Decision boundaries. See ``provenance`` for what is fitted and what is not."""

    # Verdict-score (worst_k, NOT the mean quality score) at or above which an
    # attempt counts as correct.
    #
    # These are on the worst-phone scale and must not be carried over from the
    # mean scale: 0.70 was a mean-scale placeholder, and on worst_k it called
    # 48.3% of Speechocean762 words incorrect against a true rate of 10.3%.
    #
    # 0.30 was picked on the saved benchmark (15,967 words, L2-large): it
    # flags 19.7% of words, sensitivity 0.600, specificity 0.849. Maximum
    # Youden J sits at 0.52, but that flags 38.4% -- and for a tutor,
    # wrongly telling a learner they were wrong is worse than missing an
    # error, and it inflates H1's "incorrect first attempt" denominator. So
    # specificity is favoured over the balanced optimum deliberately.
    correct: float = 0.30
    # Band below `correct` reported as "close" rather than plain wrong.
    close: float = 0.12
    # Per-phone score below which a phone is flagged as a probable error.
    phone_error: float = 0.45
    # Articulatory distance above which a substitution is "gross" rather than
    # a near miss, used to pick between cue styles in feedback.
    gross_substitution: float = 0.55
    # Mean top-1 frame posterior below which the robot asks for a repeat
    # instead of diagnosing. Gated attempts are logged and excluded from
    # correction-rate denominators.
    confidence_gate: float = 0.35

    provenance: str = (
        "PROVISIONAL. correct/close fitted on Speechocean762 test "
        "(15,967 words, L2-large, worst_k k=2 verdict scale, 2026-09-04); "
        "phone_error, gross_substitution and confidence_gate are still "
        "unfitted placeholders. Speechocean762 is L1-Mandarin speakers "
        "reading sentences, while the study is Kenyan English speakers on "
        "single words, so these must be refitted on the rater-adjudicated "
        "sample before any published number depends on them."
    )
    calibrated_on: str | None = None


@dataclass(frozen=True)
class PipelineConfig:
    """Complete description of one scoring configuration."""

    # No model is chosen yet -- see MODEL_CANDIDATES. The stub backend is the
    # default so that an unconfigured deployment fails loudly in tests rather
    # than silently scoring with whatever model happens to be cached.
    model_id: str | None = None
    backend: str = "stub"               # "torch" | "onnx" | "stub"
    device: str = "cpu"
    quantized: bool = True              # INT8 dynamic quantisation for ONNX

    # Leading/trailing silence is trimmed before alignment: a model with no
    # silence label must otherwise assign those frames to the first and last
    # phone, depressing their scores in a way that mimics a real error.
    trim_silence: bool = True
    silence_threshold_db: float = -40.0

    sample_rate: int = 16_000
    # wav2vec2 emits one frame per 20 ms of audio at 16 kHz.
    frame_stride_s: float = 0.02

    # Temperature of the GOP -> [0, 1] mapping (see gop.gop_to_score).
    gop_tau: float = 1.0
    # Cost of an unaligned phone in the expected-vs-observed alignment.
    gap_cost: float = 0.6
    duration_weighted_score: bool = True

    # Two aggregations over the same per-phone scores, because the study's two
    # primary DVs ask different questions of them. H2 wants graded quality, so
    # a mean. H1 wants a correct/incorrect verdict, and a word is wrong if any
    # phone is wrong -- a mean dilutes a single gross error into invisibility.
    #
    # worst_k with k=2 is not a guess: it was selected by sweeping every method
    # in gop.aggregate_score over 15,967 words of Speechocean762 test
    # (scripts/sweep_aggregation.py, 2026-09-03). Word-level detection of a
    # mispronounced word, L2-large model, base rate 0.103:
    #
    #     method        AUC     P@100   P@500   PCC(0-10)
    #     mean          0.787   0.360   0.292   0.341
    #     min           0.818   0.550   0.514   0.291
    #     worst_k k=2   0.819   0.730   0.586   0.364   <-- best on both
    #     quantile .15  0.810   0.700   0.582   0.336
    #
    # Under mean aggregation a precision of 0.50 was unreachable at ANY
    # threshold; under worst_k k=2, precision 0.50 comes with recall 0.289.
    # worst_k also beat mean on graded PCC, which mean was expected to win --
    # human 0-10 word accuracy is itself dominated by the worst phone, so the
    # "graded quality" construct is less mean-like than it sounds.
    quality_aggregation: str = "mean"
    verdict_aggregation: str = "worst_k"
    verdict_worst_k: int = 2
    verdict_quantile: float = 0.15

    thresholds: Thresholds = field(default_factory=Thresholds)

    # Hard ceiling on utterance length accepted for scoring. Compute is linear
    # in duration, and on the study laptop a 5 s utterance costs 5x a 1 s one;
    # the confirmatory study uses single words, so anything much longer is a
    # recording fault rather than an attempt.
    max_audio_seconds: float = 4.0
    min_audio_seconds: float = 0.2

    # Attempts allowed per item, gated attempts excluded. The backend owns
    # this because the feedback wording depends on it: on the last attempt the
    # robot must not say "listen again" and then move on, which is what
    # happened in the first pilot and left participants hearing a retry
    # instruction while the tablet showed the next word.
    max_attempts_per_item: int = 2

    def config_hash(self) -> str:
        """Stable 12-hex-char digest of everything that affects the output."""
        payload = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def is_calibrated(self) -> bool:
        return self.thresholds.calibrated_on is not None

    def provenance(self) -> dict[str, str | None]:
        """What to persist on every attempt for later reproduction."""
        from .features import FEATURE_SET_VERSION
        return {
            "pipeline_version": PIPELINE_VERSION,
            "config_hash": self.config_hash(),
            "model_id": self.model_id,
            "backend": self.backend,
            "feature_set": FEATURE_SET_VERSION,
            "calibrated_on": self.thresholds.calibrated_on,
        }


DEFAULT_CONFIG = PipelineConfig()
