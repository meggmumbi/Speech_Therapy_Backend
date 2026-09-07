"""Alignment primitives: phone-sequence alignment and CTC forced alignment.

Two distinct alignments are needed, and conflating them is what broke the
original pipeline:

* ``align_phones`` aligns the *expected* phone sequence against the *observed*
  one to say which phones were substituted, dropped or inserted. The original
  code compared the two sequences position by position over ``range(min_len)``,
  so a single inserted phone misaligned everything after it and produced a
  cascade of phantom substitutions, while any error past ``min_len`` was
  silently dropped. Edit-distance alignment with articulatory substitution
  costs fixes both.

* ``ctc_forced_align`` aligns the expected phone sequence against the acoustic
  model's frame posteriors to say *where in the audio* each expected phone was
  realised. Those frame spans are what GOP scoring is computed over.

Both are pure NumPy; neither needs a model loaded, so both are unit-testable
without the acoustic backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np

from .features import VOWELS, phone_distance, strip_stress

_VOWEL_SET = frozenset(VOWELS)

OpKind = Literal["match", "substitution", "deletion", "insertion"]

# Cost of leaving a phone unaligned. Chosen so that deletion+insertion (2 x
# 0.6 = 1.2) costs slightly more than the worst possible substitution (1.0):
# the aligner prefers to call a wildly wrong phone a substitution, but will
# split it into a deletion plus an insertion when that yields a better global
# alignment elsewhere in the word.
DEFAULT_GAP_COST = 0.6


@dataclass(frozen=True)
class PhoneOp:
    """One edit operation in an expected-vs-observed phone alignment."""

    kind: OpKind
    expected: str | None          # stress-marked expected phone, None on insertion
    actual: str | None            # observed phone, None on deletion
    expected_index: int | None    # position in the expected sequence
    actual_index: int | None      # position in the observed sequence
    cost: float

    @property
    def is_error(self) -> bool:
        return self.kind != "match"


def align_phones(
    expected: Sequence[str],
    actual: Sequence[str],
    gap_cost: float = DEFAULT_GAP_COST,
) -> list[PhoneOp]:
    """Needleman-Wunsch alignment with articulatory substitution costs.

    Stress digits are preserved in the returned ops (feedback needs them) but
    ignored when computing distances, so a stress-only difference aligns as a
    ``match`` here and is reported by the separate stress check.
    """
    n, m = len(expected), len(actual)
    # dp[i][j] = cost of aligning expected[:i] against actual[:j]
    dp = np.zeros((n + 1, m + 1), dtype=np.float64)
    dp[:, 0] = np.arange(n + 1) * gap_cost
    dp[0, :] = np.arange(m + 1) * gap_cost

    for i in range(1, n + 1):
        e = expected[i - 1]
        for j in range(1, m + 1):
            sub = dp[i - 1, j - 1] + phone_distance(e, actual[j - 1])
            dele = dp[i - 1, j] + gap_cost
            ins = dp[i, j - 1] + gap_cost
            dp[i, j] = min(sub, dele, ins)

    # Traceback. Ties resolve toward substitution, then deletion, then
    # insertion, so the same input always yields the same alignment.
    ops: list[PhoneOp] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            d = phone_distance(expected[i - 1], actual[j - 1])
            if np.isclose(dp[i, j], dp[i - 1, j - 1] + d):
                kind: OpKind = "match" if d == 0.0 else "substitution"
                ops.append(PhoneOp(kind, expected[i - 1], actual[j - 1],
                                   i - 1, j - 1, d))
                i, j = i - 1, j - 1
                continue
        if i > 0 and np.isclose(dp[i, j], dp[i - 1, j] + gap_cost):
            ops.append(PhoneOp("deletion", expected[i - 1], None,
                               i - 1, None, gap_cost))
            i -= 1
            continue
        ops.append(PhoneOp("insertion", None, actual[j - 1],
                           None, j - 1, gap_cost))
        j -= 1

    ops.reverse()
    return ops


def alignment_cost(ops: Sequence[PhoneOp]) -> float:
    return float(sum(op.cost for op in ops))


def phone_error_rate(ops: Sequence[PhoneOp]) -> float:
    """Standard PER: (S + D + I) / N_expected, for benchmark reporting."""
    errors = sum(1 for op in ops if op.is_error)
    n_expected = sum(1 for op in ops if op.expected is not None)
    return errors / n_expected if n_expected else 0.0


@dataclass(frozen=True)
class FrameSpan:
    """Frames ``[start, end)`` of the audio assigned to one expected phone."""

    token_index: int
    phone: str
    start_frame: int
    end_frame: int

    @property
    def n_frames(self) -> int:
        return self.end_frame - self.start_frame

    def seconds(self, frame_stride_s: float) -> tuple[float, float]:
        return self.start_frame * frame_stride_s, self.end_frame * frame_stride_s


def ctc_forced_align(
    log_probs: np.ndarray,
    target_ids: Sequence[int],
    blank_id: int = 0,
) -> list[FrameSpan]:
    """Viterbi-align ``target_ids`` to frames under the CTC topology.

    ``log_probs`` is ``(T, V)`` log-softmax output from the acoustic model.
    Returns one :class:`FrameSpan` per target token, in order. Tokens the
    Viterbi path never emits get a zero-width span at the position where they
    would have occurred; callers treat those as deletions.

    Raises ``ValueError`` when the audio is too short to host the target
    sequence, which is the honest answer for a truncated recording -- the
    caller should ask the speaker to repeat rather than invent a score.
    """
    if log_probs.ndim != 2:
        raise ValueError(f"log_probs must be (T, V), got shape {log_probs.shape}")
    T = log_probs.shape[0]
    L = len(target_ids)
    if L == 0:
        raise ValueError("empty target sequence")

    # Extended sequence: blank, t0, blank, t1, ..., blank  (length 2L + 1)
    ext: list[int] = [blank_id]
    for tid in target_ids:
        ext.append(tid)
        ext.append(blank_id)
    S = len(ext)

    if T < L:
        raise ValueError(
            f"audio too short for target: {T} frames for {L} phones"
        )

    neg_inf = -np.inf
    dp = np.full((T, S), neg_inf, dtype=np.float64)
    backptr = np.zeros((T, S), dtype=np.int8)  # 0 stay, 1 from s-1, 2 from s-2

    dp[0, 0] = log_probs[0, ext[0]]
    if S > 1:
        dp[0, 1] = log_probs[0, ext[1]]

    for t in range(1, T):
        for s in range(S):
            best, arg = dp[t - 1, s], 0
            if s > 0 and dp[t - 1, s - 1] > best:
                best, arg = dp[t - 1, s - 1], 1
            # A skip over a blank is legal only between distinct labels.
            if (
                s > 1
                and ext[s] != blank_id
                and ext[s] != ext[s - 2]
                and dp[t - 1, s - 2] > best
            ):
                best, arg = dp[t - 1, s - 2], 2
            if best == neg_inf:
                continue
            dp[t, s] = best + log_probs[t, ext[s]]
            backptr[t, s] = arg

    # Terminate on the final blank or the final label, whichever scored better.
    end_state = S - 1 if dp[T - 1, S - 1] >= dp[T - 1, S - 2] else S - 2
    if dp[T - 1, end_state] == neg_inf:
        raise ValueError("no valid CTC alignment for this target sequence")

    # Walk the path back, recording which frames landed on each label state.
    path = np.empty(T, dtype=np.int64)
    s = end_state
    for t in range(T - 1, -1, -1):
        path[t] = s
        s -= int(backptr[t, s])

    spans: list[FrameSpan] = []
    for k, tid in enumerate(target_ids):
        state = 2 * k + 1  # label states are the odd indices of ``ext``
        frames = np.flatnonzero(path == state)
        if frames.size:
            start, end = int(frames[0]), int(frames[-1]) + 1
        else:
            # Never emitted: zero-width span anchored after the previous phone.
            start = end = spans[-1].end_frame if spans else 0
        spans.append(FrameSpan(k, str(tid), start, end))
    return spans


def attach_phones(spans: Sequence[FrameSpan], phones: Sequence[str]) -> list[FrameSpan]:
    """Replace the token ids carried by ``ctc_forced_align`` with phone labels."""
    return [
        FrameSpan(sp.token_index, phones[sp.token_index], sp.start_frame, sp.end_frame)
        for sp in spans
    ]


def stress_errors(expected: Sequence[str], observed_stress: Sequence[int | None]
                  ) -> list[tuple[int, int, int]]:
    """Compare realised stress against CMUdict marks on the expected vowels.

    Returns ``(vowel_index, expected_stress, observed_stress)`` for each
    mismatch. Stress is the primary error mode for the study's own stimuli
    (HYperbole, misCHIEvous, onoMAtoPOEia), which the original pipeline could
    not detect at all because it stripped nothing and measured nothing.
    """
    errors: list[tuple[int, int, int]] = []
    vowel_idx = 0
    for phone in expected:
        if strip_stress(phone) not in _VOWEL_SET:
            continue
        exp = phone[-1]
        if exp in "012" and vowel_idx < len(observed_stress):
            obs = observed_stress[vowel_idx]
            if obs is not None and obs != int(exp):
                errors.append((vowel_idx, int(exp), obs))
        vowel_idx += 1
    return errors
