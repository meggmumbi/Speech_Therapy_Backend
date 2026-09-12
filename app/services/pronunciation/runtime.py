"""Process-wide acoustic model, loaded once at start-up.

Model construction costs seconds and roughly 1.2 GB of resident memory for the
selected 300 M-parameter model. Doing it per request would put that on the
participant's first attempt of every session; doing it once at start-up and
warming it means the first real request is as fast as the hundredth.

The model is chosen by benchmark, not by default:
``slplab/wav2vec2-large-robust-L2-english-phoneme-recognition`` won on
Speechocean762 across word-level detection AUC (0.819), head precision
(P@100 0.730) and graded PCC (0.364), and at the study's ~1 s single-word
utterances costs ~210 ms against a 2.5 s budget. Override with
``PRONUNCIATION_MODEL_ID`` if a re-benchmark changes the answer.
"""

from __future__ import annotations

import logging
import os
import threading

# Load the model from the local cache without contacting HuggingFace.
#
# Two reasons, and both bite in practice. On a network with TLS inspection the
# freshness HEAD request fails certificate verification and retries five times
# per file, so the server takes minutes to start even though the weights are
# already on disk. And a study machine should not be reaching out mid-session
# at all: the model that scores an attempt must be the one that was validated,
# not whatever the hub is serving today.
#
# Set PRONUNCIATION_ALLOW_DOWNLOAD=1 to fetch a model the cache does not have;
# scripts/setup_resources.py does this for you.
if os.getenv("PRONUNCIATION_ALLOW_DOWNLOAD") != "1":
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
else:
    try:
        # The same proxy that breaks the freshness check breaks the download.
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

from .acoustic import AcousticModel, assert_phone_level, load_acoustic_model
from .config import PipelineConfig

log = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "slplab/wav2vec2-large-robust-L2-english-phoneme-recognition"

_lock = threading.Lock()
_model: AcousticModel | None = None
_config: PipelineConfig | None = None


def build_config() -> PipelineConfig:
    """Configuration for the live path, from environment with study defaults."""
    return PipelineConfig(
        model_id=os.getenv("PRONUNCIATION_MODEL_ID", DEFAULT_MODEL_ID),
        backend=os.getenv("PRONUNCIATION_BACKEND", "torch"),
        device=os.getenv("PRONUNCIATION_DEVICE", "cpu"),
    )


def get_config() -> PipelineConfig:
    global _config
    if _config is None:
        _config = build_config()
    return _config


def get_model() -> AcousticModel:
    """The loaded model, constructing it on first call.

    Prefer :func:`warmup` at start-up so this never blocks a request.
    """
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                config = get_config()
                log.info("loading acoustic model %s (%s)",
                         config.model_id, config.backend)
                model = load_acoustic_model(config)
                assert_phone_level(model)
                _model = model
    return _model


def warmup() -> None:
    """Load and exercise the model. Call from application start-up.

    Failures are logged rather than raised: a missing model should degrade the
    pronunciation endpoint, not stop the whole API from serving the rest of
    the study's traffic.
    """
    try:
        model = get_model()
        # Warm on roughly the length of a real attempt. The default warm pass
        # is half a second of silence, and the first real ~1 s word still ran
        # ~1000 ms against a ~215 ms steady state -- the first participant of
        # a session should not pay that.
        import numpy as np
        model.emissions(np.zeros(16_000, dtype=np.float32), 16_000)
        model.emissions(np.zeros(16_000, dtype=np.float32), 16_000)
        info = model.describe()
        log.info("acoustic model ready: %s, %d labels, %d mapped to ARPAbet",
                 info.model_id, info.n_labels, len(info.inventory))
    except Exception:  # noqa: BLE001 - start-up must not die on this
        log.exception(
            "acoustic model failed to load; scoring will be unavailable. "
            "If the cache is empty, run: "
            "python scripts/setup_resources.py --download-model")


def is_ready() -> bool:
    return _model is not None


def reset() -> None:
    """Drop the cached model. For tests only."""
    global _model, _config
    with _lock:
        _model = None
        _config = None
