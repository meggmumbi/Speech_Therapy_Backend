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
