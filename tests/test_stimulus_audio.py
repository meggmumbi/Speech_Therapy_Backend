"""Stored model audio: what is accepted, and what it is turned into.

Every file is normalised to 16 kHz mono PCM at a fixed peak, so two
recordings made on different days at different distances from the microphone
play back the same. A stimulus that varies between presentations is not a
stimulus, which is the whole reason recordings replaced per-turn synthesis.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import stimulus_audio  # noqa: E402


def _wav(seconds: float, sr: int = 16_000, amplitude: float = 0.3, channels: int = 1) -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    tone = (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    data = tone if channels == 1 else np.stack([tone, tone * 0.5], axis=1)
    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def test_a_clean_recording_comes_back_at_16k_mono():
    waveform, duration = stimulus_audio.normalise(_wav(1.0))
    assert waveform.ndim == 1
    assert duration == pytest.approx(1.0, abs=0.01)


def test_a_48k_stereo_browser_recording_is_resampled_and_folded():
    """What MediaRecorder actually produces once decoded."""
    waveform, duration = stimulus_audio.normalise(_wav(1.0, sr=48_000, channels=2))
    assert waveform.ndim == 1
    assert len(waveform) == pytest.approx(16_000, rel=0.01)
    assert duration == pytest.approx(1.0, abs=0.02)


def test_level_is_normalised_so_two_takes_match():
    quiet, _ = stimulus_audio.normalise(_wav(1.0, amplitude=0.05))
    loud, _ = stimulus_audio.normalise(_wav(1.0, amplitude=0.6))
    assert float(np.max(np.abs(quiet))) == pytest.approx(0.9, abs=0.01)
    assert float(np.max(np.abs(loud))) == pytest.approx(0.9, abs=0.01)


def test_silence_is_refused():
    with pytest.raises(stimulus_audio.BadAudio, match="silent"):
        stimulus_audio.normalise(_wav(1.0, amplitude=0.0))


def test_a_blip_is_refused():
    with pytest.raises(stimulus_audio.BadAudio, match="too short"):
        stimulus_audio.normalise(_wav(0.05))


def test_a_long_file_is_refused():
    with pytest.raises(stimulus_audio.BadAudio, match="under"):
        stimulus_audio.normalise(_wav(20.0))


def test_garbage_is_refused_with_a_reason():
    with pytest.raises(stimulus_audio.BadAudio, match="could not decode"):
        stimulus_audio.normalise(b"not audio at all")


def test_store_writes_pcm16_at_16k(tmp_path, monkeypatch):
    monkeypatch.setattr(stimulus_audio, "STIMULUS_DIR", tmp_path)
    path, duration = stimulus_audio.store("item-1", _wav(0.5, sr=44_100))
    assert path.exists()
    info = sf.info(str(path))
    assert info.samplerate == 16_000
    assert info.channels == 1
    assert info.subtype == "PCM_16"
    assert duration == pytest.approx(0.5, abs=0.02)
    assert stimulus_audio.remove("item-1") is True
    assert not path.exists()


def test_the_url_is_relative():
    """The same stored value must work whichever host the backend runs on."""
    assert not stimulus_audio.url_for("abc").startswith("http")
