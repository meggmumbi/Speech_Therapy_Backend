"""Waveform preparation: silence trimming and basic conditioning.

Leading and trailing silence has to go before forced alignment, for two
reasons. Acoustically, a model whose inventory has no explicit silence label
must assign those frames to *some* phone, which stretches the first and last
phone's span and depresses their GOP scores -- an artefact that looks exactly
like a real articulation error. Practically, compute is linear in duration, so
on the study laptop every trimmed second is a second not spent.

Energy-based rather than neural: this also has to run on the Pepper tablet as
the endpointer, and that hardware cannot afford a model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def rms_frames(waveform: np.ndarray, frame_length: int, hop: int) -> np.ndarray:
    if len(waveform) < frame_length:
        return np.array([float(np.sqrt(np.mean(waveform.astype(np.float64) ** 2)))])
    n = 1 + (len(waveform) - frame_length) // hop
    idx = np.arange(frame_length)[None, :] + hop * np.arange(n)[:, None]
    frames = waveform[idx].astype(np.float64)
    return np.sqrt(np.mean(frames ** 2, axis=1))


def trim_silence(
    waveform: np.ndarray,
    sample_rate: int,
    threshold_db: float = -40.0,
    pad_ms: float = 60.0,
    frame_ms: float = 20.0,
) -> tuple[np.ndarray, float, float]:
    """Trim leading/trailing silence relative to the loudest frame.

    The threshold is *relative* to the utterance peak, not absolute, so it
    adapts to how loudly a given participant speaks and to the room -- an
    absolute threshold would clip quiet speakers and keep the room tone of
    loud ones.

    ``pad_ms`` of context is kept on each side so that the release of a final
    stop and the onset of an initial one survive; trimming them would create
    the very deletions the pipeline is meant to detect.

    Returns ``(trimmed, start_seconds, end_seconds)``. If the whole signal is
    below threshold, the input is returned unchanged and the caller's
    confidence gate handles it.
    """
    if waveform.size == 0 or sample_rate <= 0:
        return waveform, 0.0, 0.0

    frame_length = max(int(sample_rate * frame_ms / 1000.0), 1)
    hop = max(frame_length // 2, 1)
    energies = rms_frames(waveform, frame_length, hop)
    peak = float(energies.max())
    if peak <= 0:
        return waveform, 0.0, len(waveform) / sample_rate

    threshold = peak * (10.0 ** (threshold_db / 20.0))
    voiced = np.flatnonzero(energies >= threshold)
    if voiced.size == 0:
        return waveform, 0.0, len(waveform) / sample_rate

    pad = int(sample_rate * pad_ms / 1000.0)
    start = max(int(voiced[0]) * hop - pad, 0)
    end = min(int(voiced[-1]) * hop + frame_length + pad, len(waveform))
    if end <= start:
        return waveform, 0.0, len(waveform) / sample_rate
    return waveform[start:end], start / sample_rate, end / sample_rate


def to_mono_float32(waveform: np.ndarray) -> np.ndarray:
    """Collapse channels and normalise integer PCM into ``[-1, 1]`` floats."""
    x = np.asarray(waveform)
    # Capture the input dtype first: averaging channels promotes integers to
    # float64, which would hide the fact that the samples are still in PCM
    # range and skip the normalisation entirely.
    scale = float(np.iinfo(x.dtype).max) if np.issubdtype(x.dtype, np.integer) else 1.0
    if x.ndim > 1:
        x = x.mean(axis=tuple(range(1, x.ndim)))
    if scale != 1.0:
        x = x.astype(np.float32) / scale
    return x.astype(np.float32)


# --- recording quality ------------------------------------------------------

@dataclass(frozen=True)
class AudioQuality:
    """How usable a recording is, judged before anything tries to score it.

    Distinct from the recogniser's confidence. Confidence answers "how sure was
    the acoustic model about what it heard"; this answers "was there a usable
    recording at all". A clipped or near-silent clip can still produce a
    confident, entirely wrong verdict, and on the 2026-09-15 pilot it did.
    """

    peak: float                 # 0..1, absolute peak sample
    rms_dbfs: float             # loudness of the loudest 20 ms window
    clipped_fraction: float     # samples at or beyond full scale
    duration_s: float
    verdict: str                # ok | silent | quiet | clipped | short | long

    @property
    def usable(self) -> bool:
        return self.verdict == "ok"

    @property
    def advice(self) -> str | None:
        """What to tell the researcher, in words they can act on."""
        return {
            "silent": "Nothing was recorded. Check the microphone.",
            "quiet": "Very quiet. Move the microphone closer or ask for more volume.",
            "clipped": "Too loud, the recording is distorting. Move back a little.",
            "short": "Too short to be a word. The recorder may have cut in late.",
            "long": "Longer than a single-word attempt. Something else may have been picked up.",
        }.get(self.verdict)


# Thresholds. Deliberately loose: this is a guard against recordings that are
# unusable, not a judgement of how well someone spoke, and a false alarm costs
# a participant a needless retake.
SILENT_DBFS = -55.0     # below this there is effectively no signal
QUIET_DBFS = -38.0      # audible, but the scorer degrades from here down
CLIP_FRACTION = 0.005   # 0.5% of samples at full scale is audible distortion
MIN_SPEECH_S = 0.25
MAX_SPEECH_S = 4.0


def assess_quality(
    waveform: np.ndarray,
    sample_rate: int,
    min_speech_s: float = MIN_SPEECH_S,
    max_speech_s: float = MAX_SPEECH_S,
) -> AudioQuality:
    """Judge one recording. Never raises; an empty buffer is 'silent'."""
    audio = to_mono_float32(np.asarray(waveform))
    duration = len(audio) / sample_rate if sample_rate else 0.0

    if audio.size == 0:
        return AudioQuality(0.0, -np.inf, 0.0, duration, "silent")

    peak = float(np.max(np.abs(audio)))
    # Fraction at full scale. int16 sources quantise to just under 1.0, so the
    # test is ">= 0.99" rather than "== 1.0".
    clipped = float(np.mean(np.abs(audio) >= 0.99))

    # Loudness of the loudest 20 ms window, not of the whole clip. A mean over
    # the whole recording is dominated by the silence around a short word, so
    # every correctly-recorded single word would read as too quiet.
    frame = max(int(0.02 * sample_rate), 1)
    frames = rms_frames(audio, frame, max(frame // 2, 1))
    loudest = float(np.max(frames)) if frames.size else 0.0
    rms_dbfs = 20.0 * float(np.log10(loudest)) if loudest > 0 else -np.inf

    # Order matters: a clipped clip is also loud, and a silent one is also
    # short. Report the cause, not the symptom.
    if rms_dbfs < SILENT_DBFS:
        verdict = "silent"
    elif clipped > CLIP_FRACTION:
        verdict = "clipped"
    elif duration < min_speech_s:
        verdict = "short"
    elif duration > max_speech_s:
        verdict = "long"
    elif rms_dbfs < QUIET_DBFS:
        verdict = "quiet"
    else:
        verdict = "ok"

    return AudioQuality(peak, rms_dbfs, clipped, duration, verdict)
