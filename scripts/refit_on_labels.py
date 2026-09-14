"""Refit the verdict threshold on your own labelled recordings.

    1. python scripts/export_for_labelling.py      (writes the CSV)
    2. listen, fill the human_label column: 1 = said correctly, 0 = not
    3. python scripts/refit_on_labels.py

Why this exists: the threshold shipped in config.py is fitted on
Speechocean762, whose speakers are L1-Mandarin reading American English in a
corpus recording setup. Measured on the first study recordings, the whole
verdict-score distribution sits about 0.22 lower (median 0.588 against 0.811),
so the corpus-fitted threshold flags 51% of study attempts where it flags 16%
of corpus words.

Part of that gap is real -- the study words are harder -- and part is domain
shift. Nothing separates the two except labels from someone who heard the
audio. Tuning the threshold by eye on unlabelled recordings would be guessing
with extra steps.

This also doubles as a rehearsal for the rater validation the study needs
anyway (H6): same task, same artefacts, smaller sample.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_CSV = Path("benchmarks/pilot_to_label.csv")
OUT = Path("benchmarks/local_threshold.json")


def cost_at(scores, labels, threshold, fp_weight=2.0):
    """Cost = fp_weight * FPR + FNR, flagging below the threshold."""
    flagged = scores < threshold
    tp = float(np.sum(flagged & (labels == 1)))
    fp = float(np.sum(flagged & (labels == 0)))
    fn = float(np.sum(~flagged & (labels == 1)))
    tn = float(np.sum(~flagged & (labels == 0)))
    fpr = fp / max(fp + tn, 1.0)
    fnr = fn / max(fn + tp, 1.0)
    return fp_weight * fpr + fnr, fpr, fnr, float(flagged.mean())


def bootstrap_threshold(scores, labels, fp_weight, n=2000, seed=0):
    """Resample to show how unstable the threshold is at this sample size.

    With a few dozen labelled attempts the point estimate looks precise and is
    not. Reporting the interval keeps that visible.
    """
    rng = np.random.default_rng(seed)
    grid = np.arange(0.05, 0.96, 0.01)
    picks = []
    for _ in range(n):
        idx = rng.integers(0, len(scores), len(scores))
        s, l = scores[idx], labels[idx]
        if l.sum() == 0 or l.sum() == len(l):
            continue
        costs = [cost_at(s, l, t, fp_weight)[0] for t in grid]
        picks.append(float(grid[int(np.argmin(costs))]))
    if not picks:
        return None
    return float(np.percentile(picks, 5)), float(np.percentile(picks, 95))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--fp-weight", type=float, default=2.0)
    args = parser.parse_args()

    path = Path(args.csv)
    if not path.exists():
        raise SystemExit(f"{path} not found. Run scripts/export_for_labelling.py "
                         "first, then fill in the human_label column.")

    scores, labels, unlabelled = [], [], 0
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            raw = (row.get("human_label") or "").strip()
            if raw not in ("0", "1"):
                unlabelled += 1
                continue
            scores.append(float(row["verdict_score"]))
            # 1 = said correctly; the detector flags the opposite.
            labels.append(0 if raw == "1" else 1)

    scores, labels = np.asarray(scores), np.asarray(labels)
    print(f"{len(scores)} labelled, {unlabelled} still blank")
    if len(scores) < 20:
        raise SystemExit("Fewer than 20 labelled attempts: too few to fit a "
                         "threshold that means anything. Label more first.")
    if labels.sum() == 0 or labels.sum() == len(labels):
        raise SystemExit("All labels are the same class; a threshold cannot be "
                         "fitted from one class.")

    print(f"  mispronounced by human label: {labels.mean():.1%}")

    grid = np.arange(0.05, 0.96, 0.01)
    costs = [cost_at(scores, labels, t, args.fp_weight)[0] for t in grid]
    best_t = float(grid[int(np.argmin(costs))])
    cost, fpr, fnr, rate = cost_at(scores, labels, best_t, args.fp_weight)

    from app.services.pronunciation.config import Thresholds
    shipped = Thresholds().correct
    s_cost, s_fpr, s_fnr, s_rate = cost_at(scores, labels, shipped,
                                           args.fp_weight)

    print(f"\n{'threshold':<22}{'flags':<9}{'FPR':<8}{'FNR':<8}{'Cost'}")
    print("-" * 52)
    print(f"{'shipped (' + f'{shipped:.2f}' + ')':<22}{s_rate:<9.3f}"
          f"{s_fpr:<8.3f}{s_fnr:<8.3f}{s_cost:.3f}")
    print(f"{'fitted here (' + f'{best_t:.2f}' + ')':<22}{rate:<9.3f}"
          f"{fpr:<8.3f}{fnr:<8.3f}{cost:.3f}")

    interval = bootstrap_threshold(scores, labels, args.fp_weight)
    if interval:
        print(f"\n90% bootstrap interval for the threshold: "
              f"{interval[0]:.2f} to {interval[1]:.2f}")
        if interval[1] - interval[0] > 0.25:
            print("  That interval is wide. The point estimate is not worth "
                  "trusting on its own at this sample size -- label more "
                  "attempts before treating it as settled.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "n_labelled": int(len(scores)),
        "mispronounced_rate": float(labels.mean()),
        "fitted_threshold": best_t,
        "shipped_threshold": shipped,
        "fitted": {"cost": cost, "fpr": fpr, "fnr": fnr, "flag_rate": rate},
        "shipped_on_local_data": {"cost": s_cost, "fpr": s_fpr, "fnr": s_fnr,
                                  "flag_rate": s_rate},
        "bootstrap_90ci": interval,
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")
    print("This is fitted on YOUR recordings, so it reflects your speakers, "
          "microphone and word list.")
    print("Apply by setting Thresholds.correct in "
          "app/services/pronunciation/config.py, and record in the paper that "
          "the operating point was set on local labelled data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
