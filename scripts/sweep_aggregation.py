"""Compare word-score aggregation methods on saved benchmark output.

    python scripts/sweep_aggregation.py

Reads the per-word phone-score groups saved by ``benchmark_speechocean.py``
and re-aggregates them every supported way. No model inference, so a sweep
costs a second rather than a 20-minute re-run.

The question being answered: a word is mispronounced if *any* phone is wrong,
so summarising its phones by a mean should dilute a single gross error into
invisibility. The full-corpus run showed word-level head precision (~0.40)
*below* the phone-level scores it was built from (~0.68), which is what that
dilution looks like. If the reasoning is right, worst-phone aggregations
should beat the mean on detection while the mean stays the better graded
quality score.

Two aggregations are reported against two different targets on purpose:

* **detection** (AUC, precision on the confident head) -- H1's DV, a
  correct/incorrect verdict.
* **PCC against the 0-10 word accuracy** -- H2's DV, graded quality.

A method can and probably will win one and lose the other. That is the point:
they are different questions, and the pipeline computes both.
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

METHODS: list[tuple[str, dict]] = [
    ("mean", {}),
    ("min", {}),
    ("worst_k k=2", {"method": "worst_k", "k": 2}),
    ("worst_k k=3", {"method": "worst_k", "k": 3}),
    ("quantile .15", {"method": "quantile", "quantile": 0.15}),
    ("quantile .25", {"method": "quantile", "quantile": 0.25}),
    ("softmin b=8", {"method": "softmin", "beta": 8.0}),
    ("softmin b=16", {"method": "softmin", "beta": 16.0}),
]


def aggregate_raw(values: np.ndarray, method: str, quantile: float = 0.15,
                  k: int = 2, beta: float = 8.0) -> float:
    """Aggregation over bare score arrays.

    Mirrors ``gop.aggregate_score`` but takes plain floats, because the saved
    benchmark output has scores without the PhoneScore objects around them.
    The duration weighting the real ``mean`` applies is unavailable here, so
    this ``mean`` is unweighted -- close enough for ranking methods against
    each other, and flagged rather than glossed.
    """
    if values.size == 0:
        return 0.0
    if method == "mean":
        return float(values.mean())
    if method == "min":
        return float(values.min())
    if method == "quantile":
        return float(np.quantile(values, quantile))
    if method == "worst_k":
        n = max(1, min(k, values.size))
        return float(np.sort(values)[:n].mean())
    if method == "softmin":
        shifted = -beta * (values - values.min())
        return float(values.min() - np.log(np.mean(np.exp(shifted))) / beta)
    raise ValueError(method)


def roc_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    pos, neg = labels.sum(), len(labels) - labels.sum()
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(scores)
    ranks = np.empty(len(scores), float)
    ranks[order] = np.arange(1, len(scores) + 1, dtype=float)
    return float((ranks[labels == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def head_precision(scores: np.ndarray, labels: np.ndarray, n: int) -> float:
    """Precision among the ``n`` lowest-scoring (most suspect) words."""
    if n > len(scores):
        return float("nan")
    order = np.argsort(scores)
    return float(labels[order][:n].mean())


def best_f1(scores: np.ndarray, labels: np.ndarray) -> float:
    if labels.sum() == 0:
        return float("nan")
    order = np.argsort(scores)
    ys = labels[order]
    tp = np.cumsum(ys)
    k = np.arange(1, len(ys) + 1)
    precision = tp / k
    recall = tp / ys.sum()
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    return float(np.nanmax(f1))


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 2 or x.std() == 0 or y.std() == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def load_groups(path: str) -> tuple[list[np.ndarray], np.ndarray] | None:
    data = np.load(path)
    if "group_flat" not in data or "group_offsets" not in data:
        return None
    flat, offsets = data["group_flat"], data["group_offsets"]
    groups = [flat[offsets[i]:offsets[i + 1]] for i in range(len(offsets) - 1)]
    return groups, data["word_gold"]


def main() -> int:
    paths = sorted(glob.glob("benchmarks/raw-*.npz"))
    if not paths:
        print("No benchmark output found. Run scripts/benchmark_speechocean.py first.")
        return 1

    any_groups = False
    for path in paths:
        loaded = load_groups(path)
        if loaded is None:
            continue
        any_groups = True
        groups, gold = loaded
        name = Path(path).stem.replace("raw-", "").split("__")[0]
        labels = (gold < 10).astype(int)

        print(f"\n{name}   n_words={len(groups)}  "
              f"mispronounced base rate={labels.mean():.3f}")
        print(f"  {'method':<15} {'AUC':<8} {'bestF1':<8} {'P@100':<8} "
              f"{'P@500':<8} {'P@1000':<8} {'PCC(0-10)':<10}")
        print("  " + "-" * 72)

        for label, spec in METHODS:
            # Copy: this loop runs once per model file, and popping from the
            # shared METHODS entries would strip the method name after the
            # first model.
            kwargs = dict(spec)
            method = kwargs.pop("method", label)
            scores = np.array([aggregate_raw(g, method, **kwargs) for g in groups])
            print(f"  {label:<15} {roc_auc(-scores, labels):<8.3f} "
                  f"{best_f1(scores, labels):<8.3f} "
                  f"{head_precision(scores, labels, 100):<8.3f} "
                  f"{head_precision(scores, labels, 500):<8.3f} "
                  f"{head_precision(scores, labels, 1000):<8.3f} "
                  f"{pearson(scores, gold):<10.3f}")

    if not any_groups:
        print("Benchmark output predates per-word group saving. Re-run "
              "scripts/benchmark_speechocean.py to regenerate.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
