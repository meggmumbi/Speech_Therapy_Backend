"""Inter-rater agreement, computed rather than described.

Percent agreement is easy to read and inflated by chance; kappa corrects for
chance and is what a reviewer expects. Both are reported, because a kappa of
0.6 next to 92% agreement tells a different story from a kappa of 0.6 next
to 70%.
"""

from __future__ import annotations

from collections import Counter
from typing import Hashable, Sequence


def percent_agreement(a: Sequence[Hashable], b: Sequence[Hashable]) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    return round(100.0 * sum(1 for x, y in pairs if x == y) / len(pairs), 1)


def cohen_kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> float | None:
    """Two raters, any number of categories."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(1 for x, y in pairs if x == y) / n
    cats = {c for pair in pairs for c in pair}
    pa = Counter(x for x, _ in pairs)
    pb = Counter(y for _, y in pairs)
    expected = sum((pa[c] / n) * (pb[c] / n) for c in cats)
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return round((observed - expected) / (1 - expected), 3)


def fleiss_kappa(table: Sequence[Sequence[Hashable]]) -> float | None:
    """Any number of raters; every subject rated by the same number of raters.

    `table` is one row per subject, each row the ratings that subject got.
    Rows with a different number of ratings from the first are dropped, since
    the statistic assumes equal n per subject: a subject two raters saw and a
    subject three raters saw are not the same kind of observation.
    """
    rows = [list(r) for r in table if r and all(x is not None for x in r)]
    if not rows:
        return None
    n = len(rows[0])
    rows = [r for r in rows if len(r) == n]
    if n < 2 or len(rows) < 2:
        return None
    cats = sorted({c for r in rows for c in r}, key=str)
    if len(cats) < 2:
        return 1.0
    N = len(rows)
    counts = [[r.count(c) for c in cats] for r in rows]
    p_j = [sum(row[j] for row in counts) / (N * n) for j in range(len(cats))]
    P_i = [(sum(x * x for x in row) - n) / (n * (n - 1)) for row in counts]
    P_bar = sum(P_i) / N
    P_e = sum(p * p for p in p_j)
    if P_e == 1.0:
        return 1.0
    return round((P_bar - P_e) / (1 - P_e), 3)


def mean_absolute_difference(a: Sequence[float | None], b: Sequence[float | None]) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    return round(sum(abs(x - y) for x, y in pairs) / len(pairs), 2)


def describe_kappa(k: float | None) -> str:
    """Landis & Koch bands, so the number comes with the word a reader will
    want to attach to it, and the same word every time."""
    if k is None:
        return "not computable"
    if k < 0:
        return "poor"
    if k < 0.21:
        return "slight"
    if k < 0.41:
        return "fair"
    if k < 0.61:
        return "moderate"
    if k < 0.81:
        return "substantial"
    return "almost perfect"
