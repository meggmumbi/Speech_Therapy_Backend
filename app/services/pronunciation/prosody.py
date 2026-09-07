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
path and noted as a limitation. Duration and energy alone identify primary
stress reliably enough for feedback on citation-form single words, which is all
the confirmatory study needs -- but this should be validated against the rater
sample like everything else.
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
