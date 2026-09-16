"""Server-side word recognition, used only as the false-rejection safety net.

The verdict logic in :mod:`scoring` lets a matching ASR transcript *rescue* an
attempt the acoustics called wrong -- never the reverse -- because telling a
volunteer they mispronounced a word they said correctly is the worst failure
this system can have. That design assumed the tablet would send its on-device
recogniser's output. It cannot: the PCM recorder that captures the attempt and
Android's ``SpeechRecognizer`` both want the microphone, so ``transcript`` was
NULL on every one of the 78 pilot attempts of 2026-09-15 and the safety net had
never fired.

So the server recognises the word itself, from the WAV it already holds, with
`faster-whisper <https://github.com/SYSTRAN/faster-whisper>`_ (CTranslate2,
INT8, CPU). Two properties matter and are deliberate:

* **It is not the scorer.** It never sees phone scores and never lowers a
  verdict. Whisper is a word recogniser with a strong lexical prior, which is
  exactly what makes it good at "was the right word said?" and exactly what
  would make it a poor judge of *how well* it was said.
* **It is lazy.** :func:`scoring.score_phone_sequence` calls it only after the
  acoustic verdict has come out as not correct and no client transcript
  exists. A correct attempt never pays for it. The extra latency lands on the
  attempts where the alternative is a possibly-wrong "incorrect".

The target word is **not** passed as a prompt. Priming Whisper with the answer
would make it hear the answer, and the rescue would stop being evidence.

Models are fetched from the Hugging Face hub on first use, unless
``HF_HUB_OFFLINE`` is set (which :mod:`runtime` does by default); download
them once with ``python scripts/setup_resources.py --download-asr``.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

WHISPER_SAMPLE_RATE = 16_000

_lock = threading.Lock()
_models: dict[str, object] = {}
_failed: set[str] = set()


def _load(model_name: str):
    """Load one faster-whisper model once per process, or None if it cannot be."""
    if model_name in _models:
        return _models[model_name]
    if model_name in _failed:
        return None
    with _lock:
        if model_name in _models:
            return _models[model_name]
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
        except Exception:  # noqa: BLE001 - a missing ASR must not stop scoring
            log.exception(
                "server-side ASR %r unavailable; the transcript safety net is "
                "OFF. Install faster-whisper and run "
                "scripts/setup_resources.py --download-asr", model_name)
            _failed.add(model_name)
            return None
        _models[model_name] = model
        log.info("server-side ASR loaded: faster-whisper %s (int8, cpu)", model_name)
        return model


def is_available(model_name: str | None) -> bool:
    return bool(model_name) and _load(model_name) is not None


def warmup(model_name: str | None) -> None:
    """Load and run once so the first participant does not pay the cold start."""
    if not model_name:
        return
    if _load(model_name) is not None:
        transcribe(np.zeros(WHISPER_SAMPLE_RATE // 2, dtype=np.float32),
                   WHISPER_SAMPLE_RATE, model_name)


def transcribe(waveform: np.ndarray, sample_rate: int,
               model_name: str) -> str | None:
    """Recognise the words in ``waveform``; None if the recogniser is unavailable.

    ``waveform`` is mono float32 in ``[-1, 1]``. Resampled to 16 kHz here if
    needed. Returns the raw text; matching against the target is the caller's
    business (:func:`scoring.transcript_matches_target`).
    """
    model = _load(model_name)
    if model is None:
        return None
    audio = np.asarray(waveform, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sample_rate != WHISPER_SAMPLE_RATE:
        import librosa
        audio = librosa.resample(audio, orig_sr=sample_rate,
                                 target_sr=WHISPER_SAMPLE_RATE)
    segments, _info = model.transcribe(
        audio,
        language="en",
        beam_size=5,
        # Single citation-form words: no prior context, no cross-segment
        # conditioning, and no VAD (the attempt is already endpointed by the
        # client and trimmed by the pipeline; VAD on a 0.6 s word drops it).
        condition_on_previous_text=False,
        vad_filter=False,
        without_timestamps=True,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    return text or None


def provider_for(model_name: str | None,
                 ) -> Callable[[np.ndarray, int], str | None] | None:
    """A ``(waveform, sample_rate) -> text`` callable for scoring to invoke
    lazily on the trimmed audio, or None if server-side ASR is disabled."""
    if not model_name:
        return None
    return lambda waveform, sample_rate: transcribe(waveform, sample_rate,
                                                    model_name)
