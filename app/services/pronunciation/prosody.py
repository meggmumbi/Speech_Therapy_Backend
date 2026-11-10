"""Lexical stress estimation from forced-alignment spans.

The original pipeline measured nothing about stress, yet the study's own
stimuli -- HYperbole, misCHIEvous, onoMAtoPOEia -- are mispronounced primarily
by putting the stress on the wrong syllable. Those errors were invisible to it
by construction.

This module estimates which vowel carried primary stress from the two acoustic
correlates that forced alignment makes free: **duration** (how many frames the
aligner gave the vowel) and **energy** (RMS of the waveform over those frames).
Pitch is the third correlate and the strongest of the three, but extracting F0
costs another pass over the audio; it is deliberately left out of the real-time
path and noted as a limitation.

Raw RMS must be declination-corrected before it can be compared across an
utterance, and originally it was not. A speaker's amplitude falls steadily from
the start of an utterance to the end -- subglottal pressure drops as the lungs
empty -- so a late stressed vowel is quieter than an early unstressed one in
plain RMS terms. Measured on 50 study attempts (2026-09-15): the last vowel's
RMS was lower than the first's in **94%** of them, median ratio 0.40. Multiplied
into prominence, that swamped duration and made this a first-vowel detector: it
called vowel 0 the stressed one in **88%** of attempts, where duration alone
spread across positions (32% / 44% / 6% / 16% / 2%).

The visible damage was a false "stress error" on every word whose stress is not
initial -- receipt, debut, debris, hyperbole -- which is exactly the advanced
vocabulary the study needs. "Receipt" was failed on stress while its segmental
score was 0.904: the weakest component in the pipeline overriding the strongest
evidence in it.

Energy is now divided by a fitted amplitude trend before it is used, so what
enters prominence is how loud a vowel is *relative to where it sits in the
utterance*. That brought the first-vowel rate to 70% -- better, still not a
stress detector. It remains unvalidated against human stress judgements, and
until it is, ``analyse_stress`` must not be the sole reason an attempt is called
wrong (see ``PipelineConfig.stress_can_fail_verdict``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .align import FrameSpan
from .features import is_vowel


@dataclass(frozen=True)
class VowelProminence:
    vowel_index: int          # index among vowels, not among all phones
    phone: str
    duration_frames: int
    rms_energy: float
    prominence: float         # normalised duration x energy, 0-1 within word


@dataclass(frozen=True)
class StressAnalysis:
    prominences: tuple[VowelProminence, ...]
    realised_primary: int | None      # vowel index judged to carry main stress
    expected_primary: int | None      # vowel index marked 1 in CMUdict
    is_error: bool
    margin: float                     # gap to the runner-up; low = uncertain


def _declination(waveform: np.ndarray, sample_rate: int,
                 frame_ms: float = 20.0) -> tuple[float, float] | None:
    """Least-squares fit of log RMS against time, over the voiced frames.

    Returns ``(slope, intercept)`` in the log domain with time in 20 ms frames,
    or None when there is too little signal to fit. Only frames within 35 dB
    of the peak are used, so silence and room tone cannot drag the line.
    """
    n = max(int(sample_rate * frame_ms / 1000.0), 1)
    if waveform.size < n * 4:
        return None
    frames = waveform[:len(waveform) - len(waveform) % n].reshape(-1, n)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    peak = float(rms.max()) if rms.size else 0.0
    if peak <= 0:
        return None
    voiced = rms > peak * (10 ** (-35.0 / 20.0))
    if int(voiced.sum()) < 4:
        return None
    t = np.arange(len(rms), dtype=np.float64)[voiced]
    y = np.log(np.maximum(rms[voiced], 1e-9))
    if float(t.max() - t.min()) < 1.0:
        return None
    slope, intercept = np.polyfit(t, y, 1)
    return float(slope), float(intercept)


def _rms(waveform: np.ndarray, start: int, end: int, frame_stride_s: float,
         sample_rate: int) -> float:
    lo = int(start * frame_stride_s * sample_rate)
    hi = int(end * frame_stride_s * sample_rate)
    lo, hi = max(0, lo), min(len(waveform), hi)
    if hi <= lo:
        return 0.0
    segment = waveform[lo:hi].astype(np.float64)
    return float(np.sqrt(np.mean(segment ** 2)))


def analyse_stress(
    waveform: np.ndarray,
    sample_rate: int,
    spans: Sequence[FrameSpan],
    expected_phones: Sequence[str],
    frame_stride_s: float,
    min_margin: float = 0.10,
) -> StressAnalysis:
    """Compare realised prominence against the expected CMUdict stress mark.

    ``min_margin`` guards against over-calling: when the top two vowels are
    within that fraction of each other the realised stress is treated as
    undetermined and no stress error is reported. Silence is better than a
    confident wrong diagnosis, which is the failure mode this whole pipeline
    revision exists to remove.
    """
    prominences: list[VowelProminence] = []
    vowel_index = 0
    expected_primary: int | None = None

    for span, phone in zip(spans, expected_phones):
        if not is_vowel(phone):
            continue
        if phone[-1] == "1" and expected_primary is None:
            expected_primary = vowel_index
        prominences.append(VowelProminence(
            vowel_index=vowel_index,
            phone=phone,
            duration_frames=span.n_frames,
            rms_energy=_rms(waveform, span.start_frame, span.end_frame,
                            frame_stride_s, sample_rate),
            prominence=0.0,
        ))
        vowel_index += 1

    if not prominences:
        return StressAnalysis((), None, expected_primary, False, 0.0)

    durations = np.array([p.duration_frames for p in prominences], dtype=np.float64)
    energies = np.array([p.rms_energy for p in prominences], dtype=np.float64)

    # Divide out the utterance's amplitude trend, so energy says how loud a
    # vowel is for its position rather than how early it is. See the module
    # docstring: without this the whole measure collapses to "the first vowel".
    trend = _declination(waveform, sample_rate)
    if trend is not None:
        slope, intercept = trend
        # Span frames are in the model's stride; the trend was fitted in 20 ms
        # frames. Convert span midpoints onto the trend's time axis.
        to_trend_frames = max(frame_stride_s, 1e-9) / 0.020
        expected = []
        for span, phone in zip(spans, expected_phones):
            if not is_vowel(phone):
                continue
            midpoint = (span.start_frame + span.end_frame) / 2.0 * to_trend_frames
            expected.append(float(np.exp(slope * midpoint + intercept)))
        expected_arr = np.asarray(expected, dtype=np.float64)
        if expected_arr.shape == energies.shape and np.all(expected_arr > 0):
            energies = energies / expected_arr

    raw = durations * np.maximum(energies, 1e-9)
    total = raw.sum()
    normalised = raw / total if total > 0 else np.zeros_like(raw)

    prominences = [
        VowelProminence(p.vowel_index, p.phone, p.duration_frames,
                        p.rms_energy, float(normalised[i]))
        for i, p in enumerate(prominences)
    ]

    order = np.argsort(normalised)[::-1]
    top = int(order[0])
    margin = float(normalised[top] - normalised[order[1]]) if len(order) > 1 else 1.0

    if len(prominences) < 2 or margin < min_margin:
        return StressAnalysis(tuple(prominences), None, expected_primary,
                              False, margin)

    is_error = expected_primary is not None and top != expected_primary
    return StressAnalysis(tuple(prominences), top, expected_primary,
                          is_error, margin)
