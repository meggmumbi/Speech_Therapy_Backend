"""Does the verdict aggregation punish words for being long?

Run this whenever the aggregation or the acoustic model changes.

The question it answers cannot be answered by AUC or Cost on the whole
corpus, which is why it needs its own script. 70% of Speechocean762 is
two- and three-phone words, so an aggregation can fail long words twice as
often as short ones and still win the aggregate metric. That is exactly what
happened: ``scripts/sweep_aggregation.py`` chose ``worst_k`` with k=2 on
2026-09-03, and the bias went unnoticed until the study moved to
undergraduates and advanced polysyllabic stimuli.

The test is simple. Take only the words human raters scored a **perfect 10**.
Every flag on those words is the pipeline being wrong. If the false-alarm rate
climbs with word length, the aggregation is measuring length, not
pronunciation.

Reads ``benchmarks/raw-<model>.npz`` written by ``scripts/benchmark_speechocean.py``
(per-phone scores plus word groupings plus expert word accuracy), so it costs
a file read rather than another pass over the corpus.

**Those are PRE-MD-layer GOP scores, and the ranking here does not transfer.**
Run on 2026-09-14 this script ranked quantile 0.15 above worst_k on both Cost
(0.683 vs 0.708) and length spread, and the switch was made on that basis.
Refitting through the full production path -- which applies the supervised MD
layer on top of these per-phone scores -- reversed the Cost ranking (worst_k
0.655, quantile 0.719) and the change was reverted. See the aggregation
comment in ``config.py``.

So treat this script as a *screen*, not a verdict: it is the cheap way to spot
that an aggregation might be length-biased, over many candidates, without an
hour-long corpus pass each. Confirm anything it suggests with
``scripts/fit_verdict_thresholds.py --aggregation ...``, which scores through
the real path and can be pointed at two candidates without either run
overwriting the other.

    python scripts/check_length_bias.py
    python scripts/check_length_bias.py --npz benchmarks/raw-other-model.npz
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_GLOB = "benchmarks/raw-*.npz"
# Cost = FP_WEIGHT * FPR + FNR, weighting a false correction twice a missed
# error. Matches config and Vidal et al. (CACM 2024).
FP_WEIGHT = 2.0


def worst_k(scores: np.ndarray, k: int) -> float:
    return float(np.mean(np.sort(scores)[:min(k, len(scores))]))


AGGREGATIONS = {
    "worst_k=1 (min)": lambda w: worst_k(w, 1),
    "worst_k=2": lambda w: worst_k(w, 2),
    "worst_k=3": lambda w: worst_k(w, 3),
    "quantile 0.15": lambda w: float(np.quantile(w, 0.15)),
    "quantile 0.25": lambda w: float(np.quantile(w, 0.25)),
    "worst 20% of phones": lambda w: worst_k(w, max(1, round(0.20 * len(w)))),
    "worst 25% of phones": lambda w: worst_k(w, max(1, round(0.25 * len(w)))),
    "mean": lambda w: float(np.mean(w)),
}

LENGTH_BANDS = [(1, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 40)]
MIN_BAND = 30


def cost_at(scores, labels, threshold, fp_weight=FP_WEIGHT):
    flagged = scores < threshold
    fp = float(np.sum(flagged & (labels == 0)))
    tn = float(np.sum(~flagged & (labels == 0)))
    fn = float(np.sum(~flagged & (labels == 1)))
    tp = float(np.sum(flagged & (labels == 1)))
    fpr = fp / max(fp + tn, 1.0)
    fnr = fn / max(fn + tp, 1.0)
    return fp_weight * fpr + fnr, fpr, fnr


def band_label(lo: int, hi: int) -> str:
    if lo == hi:
        return str(lo)
    return f"{lo}-{hi}" if hi < 40 else f"{lo}+"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npz", default=None,
                        help="raw benchmark archive (default: the archive for "
                             "the model in config, NOT merely the newest -- "
                             "benchmarks/ holds archives for rejected "
                             "candidates too)")
    parser.add_argument("--fp-weight", type=float, default=FP_WEIGHT)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    path = Path(args.npz) if args.npz else None
    if path is None:
        matches = sorted(glob.glob(DEFAULT_GLOB))
        if not matches:
            raise SystemExit(f"no {DEFAULT_GLOB} found. Run "
                             "scripts/benchmark_speechocean.py first.")
        # Pick the archive belonging to the model that actually ships, not the
        # newest file. benchmarks/ also holds archives for candidates that were
        # evaluated and rejected, and silently analysing one of those would
        # answer the question about the wrong model.
        # runtime.get_config() is the authority: PipelineConfig defaults to
        # model_id=None with the stub backend, and the real id comes from
        # runtime's DEFAULT_MODEL_ID or PRONUNCIATION_MODEL_ID.
        from app.services.pronunciation.runtime import get_config

        model_id = get_config().model_id
        if model_id:
            slug = model_id.replace("/", "__")
            wanted = [m for m in matches if slug in m]
            if not wanted:
                raise SystemExit(
                    "no benchmark archive for the configured model "
                    + str(model_id) + ". Found: "
                    + ", ".join(Path(m).name for m in matches)
                    + ". Run scripts/benchmark_speechocean.py for it, "
                      "or pass --npz explicitly.")
            path = Path(wanted[0])
        else:
            raise SystemExit("runtime resolved no model_id; pass --npz "
                             "explicitly.")

    d = np.load(path)
    missing = {"group_flat", "group_offsets", "word_gold"} - set(d.files)
    if missing:
        raise SystemExit(f"{path} lacks {sorted(missing)}; it was not written "
                         "with per-word groupings.")

    flat = d["group_flat"]
    offsets = d["group_offsets"].astype(int)
    gold = d["word_gold"]
    words = [flat[offsets[i]:offsets[i + 1]] for i in range(len(gold))]
    n_phones = np.array([len(w) for w in words])
    # Speechocean762 word accuracy is 0-10; below 10 means raters heard an
    # error somewhere in the word.
    mispronounced = (gold < 10).astype(int)
    perfect = gold >= 10

    print(f"{path.name}")
    print("NOTE: pre-MD-layer GOP scores. The MD layer has reversed this "
          "ranking before; confirm with")
    print("      scripts/fit_verdict_thresholds.py --aggregation before acting on this table.")
    print(f"{len(gold)} human-scored words, "
          f"{mispronounced.mean():.1%} judged mispronounced, "
          f"{perfect.sum()} scored a perfect 10\n")

    # Fit each aggregation's threshold on half the words and report on the
    # other half, so the comparison is not each method marking its own work.
    rng = np.random.default_rng(args.seed)
    idx = rng.permutation(len(gold))
    fit, ev = idx[:len(idx) // 2], idx[len(idx) // 2:]
    grid = np.arange(0.05, 0.99, 0.01)

    bands = [(lo, hi) for lo, hi in LENGTH_BANDS
             if int((perfect & (n_phones >= lo) & (n_phones <= hi)).sum()) >= MIN_BAND]
    headers = "".join(f"{band_label(lo, hi):<8}" for lo, hi in bands)

    print("Cost and FPR/FNR are on the held-out half. The length columns are "
          "the\nfalse-alarm rate on perfect-10 words only, so every flag "
          "counted is wrong.\n")
    print(f"{'aggregation':<22}{'thr':<6}{'Cost':<7}{'FPR':<7}{'FNR':<7}"
          f"{headers}{'spread'}")
    print("-" * (49 + 8 * len(bands) + 8))

    rows = []
    for name, fn in AGGREGATIONS.items():
        s = np.array([fn(w) for w in words])
        costs = [cost_at(s[fit], mispronounced[fit], t, args.fp_weight)[0]
                 for t in grid]
        t = float(grid[int(np.argmin(costs))])
        cost, fpr, fnr = cost_at(s[ev], mispronounced[ev], t, args.fp_weight)

        rates = []
        for lo, hi in bands:
            m = perfect & (n_phones >= lo) & (n_phones <= hi)
            rates.append(float((s[m] < t).mean()))
        spread = max(rates) - min(rates)
        rows.append((name, cost, spread))
        cells = "".join(f"{r:<8.1%}" for r in rates)
        print(f"{name:<22}{t:<6.2f}{cost:<7.3f}{fpr:<7.3f}{fnr:<7.3f}"
              f"{cells}{spread:+.1%}")

    print(f"\ncorrelation between score and phone count "
          f"(human raters: {np.corrcoef(n_phones, gold)[0, 1]:+.3f})")
    for name, fn in AGGREGATIONS.items():
        s = np.array([fn(w) for w in words])
        print(f"  {name:<22}r = {np.corrcoef(n_phones, s)[0, 1]:+.3f}")

    # Recommend on both axes at once. An aggregation that wins on Cost while
    # failing long words is the trap this script exists to catch.
    best_cost = min(rows, key=lambda r: r[1])
    balanced = [r for r in rows if r[2] < 0.10]
    print(f"\nlowest Cost:        {best_cost[0]} ({best_cost[1]:.3f}, "
          f"spread {best_cost[2]:+.1%})")
    if balanced:
        pick = min(balanced, key=lambda r: r[1])
        print(f"lowest Cost with a length spread under 10%: {pick[0]} "
              f"({pick[1]:.3f}, spread {pick[2]:+.1%})")
        if pick[0] != best_cost[0]:
            print("  These disagree. Prefer the second: an aggregation that "
                  "wins on Cost\n  by failing long words is measuring length, "
                  "not pronunciation.")
    else:
        print("No aggregation here keeps the length spread under 10%. That is "
              "a finding\nabout the per-phone scores, not about the "
              "aggregation -- report it rather\nthan picking the least bad row.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
