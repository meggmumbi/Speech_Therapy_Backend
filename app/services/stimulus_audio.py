"""Stored model audio for items: the fix for two problems at once.

The perception items ask which word was heard and had nothing to play. And a
pilot participant reported the pronunciation "different when it repeated",
because the model was synthesised fresh on every turn. One speaker, recorded
once, stored against the item, played back identically every time, answers
both.

Files are normalised on the way in to exactly what the tablet and the scorer
expect -- 16 kHz mono PCM WAV -- so the console can send whatever the
browser's recorder produced and nothing downstream has to care.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np

STIMULUS_DIR = Path("stimulus_audio")
TARGET_SR = 16_000
#: Longer than any word or carrier sentence; a file past this is a mistake,
#: not a stimulus.
MAX_SECONDS = 15.0
MIN_SECONDS = 0.2


class BadAudio(ValueError):
    """The upload could not be turned into a usable stimulus."""


def normalise(raw: bytes) -> tuple[np.ndarray, float]:
    """Decode any format soundfile reads into 16 kHz mono float32.

    Returns the waveform and its duration in seconds. Trailing and leading
    silence is left alone: for a stimulus the pause before the word is part of
    what the participant hears and should be the same on every presentation.
    """
    import soundfile as sf

    try:
        data, sample_rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same failure
        raise BadAudio(f"could not decode audio: {exc}") from exc

    waveform = np.asarray(data, dtype=np.float32)
    if waveform.ndim > 1:
        waveform = waveform.mean(axis=1)
    if sample_rate != TARGET_SR:
        try:
            import librosa
        except ImportError as exc:
            raise BadAudio(
                f"audio is {sample_rate} Hz and librosa is not installed to "
                f"resample it; send {TARGET_SR} Hz") from exc
        waveform = librosa.resample(waveform, orig_sr=sample_rate, target_sr=TARGET_SR)

    duration = len(waveform) / TARGET_SR
    if duration < MIN_SECONDS:
        raise BadAudio(f"recording is {duration:.2f}s, too short to be a word")
    if duration > MAX_SECONDS:
        raise BadAudio(f"recording is {duration:.1f}s; a stimulus is under {MAX_SECONDS:.0f}s")
    peak = float(np.max(np.abs(waveform))) if len(waveform) else 0.0
    if peak < 0.01:
        raise BadAudio("recording is silent")
    # Normalise to a fixed peak, so two recordings made on different days at
    # different distances from the microphone play back at the same level.
    waveform = waveform * (0.9 / peak)
    return waveform.astype(np.float32), duration


def path_for(item_id) -> Path:
    return STIMULUS_DIR / f"{item_id}.wav"


def store(item_id, raw: bytes) -> tuple[Path, float]:
    """Normalise and write. Returns the path and the duration."""
    import soundfile as sf

    waveform, duration = normalise(raw)
    STIMULUS_DIR.mkdir(parents=True, exist_ok=True)
    path = path_for(item_id)
    sf.write(str(path), waveform, TARGET_SR, subtype="PCM_16")
    return path, duration


def remove(item_id) -> bool:
    path = path_for(item_id)
    if path.exists():
        path.unlink()
        return True
    return False


def url_for(item_id) -> str:
    """The relative path the tablet and the console fetch. Relative, so the
    same stored value works whichever host the backend is running on."""
    return f"authoring/items/{item_id}/audio"
