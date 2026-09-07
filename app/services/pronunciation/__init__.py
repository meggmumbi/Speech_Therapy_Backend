"""Acoustic pronunciation scoring.

Replaces the text-only ``pronunciation_pipeline``, which compared the spelling
of an ASR transcript against the spelling of the target word and never touched
the learner's audio. Public surface:

    from app.services.pronunciation import score_attempt, load_acoustic_model

    model = load_acoustic_model(config)   # once, at start-up
    model.warmup()
    result = score_attempt("draught", waveform, 16_000, model, config)

The old module remains in place and untouched until this one is validated
against the rater-adjudicated sample; nothing is switched over on the strength
of it being newer.
"""

from .acoustic import (AcousticModel, Emissions, ModelInfo, StubAcousticModel,
                       assert_phone_level, load_acoustic_model)
from .align import PhoneOp, align_phones, ctc_forced_align, phone_error_rate
from .config import DEFAULT_CONFIG, PIPELINE_VERSION, PipelineConfig, Thresholds
from .features import differing_feature, phone_distance
from .feedback import (Condition, Feedback, arpabet_tokens_in, articulatory_cue,
                       generate_feedback, speakable_phone)
from .gop import PhoneScore, utterance_confidence
from .lexicon import normalize_text, pronunciations
from .prosody import StressAnalysis, analyse_stress
from .scoring import (AttemptScore, PhoneDiagnosis, Timings, score_attempt,
                      score_phone_sequence)

__all__ = [
    "AcousticModel", "AttemptScore", "Condition", "DEFAULT_CONFIG", "Emissions",
    "Feedback", "ModelInfo", "arpabet_tokens_in", "articulatory_cue",
    "generate_feedback", "speakable_phone",
    "PIPELINE_VERSION", "PhoneDiagnosis", "PhoneOp", "PhoneScore",
    "PipelineConfig", "StressAnalysis", "StubAcousticModel", "Thresholds",
    "Timings", "align_phones", "analyse_stress", "assert_phone_level",
    "ctc_forced_align", "differing_feature", "load_acoustic_model",
    "normalize_text", "phone_distance", "phone_error_rate", "pronunciations",
    "score_attempt", "score_phone_sequence", "utterance_confidence",
]
