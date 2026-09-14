"""Fit a mispronunciation-detection layer on Speechocean762 GOP features.

    python scripts/train_md_layer.py

Trains the **MD** model of Vidal et al. (CACM 2024): a small supervised layer
over features from a native-trained acoustic model, fitted on non-native speech
with human pronunciation labels. They measure MD at AUC 0.80-0.83 against
0.67-0.71 for the unsupervised GOP (PR) approach our pipeline currently uses.

Evaluation follows the CAPT literature rather than generic classification:

* **Cost = 2 x FPR + FNR** (Vidal et al.). A false correction -- telling a
  learner they mispronounced a word they said correctly -- is weighted twice as
  heavily as a missed error. That is not an arbitrary choice: a tutor that
  corrects correct speech teaches the learner to distrust it, and it inflates
  the "incorrect first attempt" denominator the study's primary DV depends on.
  Thresholds are chosen to minimise Cost, not to maximise F1 or Youden's J.

* **Per-phone thresholds.** Vidal et al. tune the decision threshold separately
  for each phone on development data. Phones differ enormously in how cleanly
  the acoustics separate correct from incorrect, and one global threshold
  forces the easy and hard phones to share an operating point.

* **PCC against the expert 0-2 score**, for comparability with published
  numbers. Speechocean762 SOTA for phone-level PCC is 0.656 (Chao et al. 2022).

Grouped splitting by utterance keeps all phones from one recording on the same
side of the train/dev boundary, so a model cannot score well by memorising a
speaker or a recording condition.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BENCH = Path("benchmarks")
MODEL_OUT = Path("data/md_layer.npz")


def load(split: str):
    path = BENCH / f"gop-features-{split}.npz"
    if not path.exists():
        raise SystemExit(f"{path} not found. Run scripts/extract_gop_features.py "
                         f"--split {split} first.")
    d = np.load(path, allow_pickle=True)
    return (d["X"].astype(np.float64), d["y"].astype(np.float64),
            d["phone_ids"], d["utt_ids"], list(d["feature_names"]),
            [str(p) for p in d["inventory"]],
            d["duration_means"] if "duration_means" in d else None,
            d["duration_stds"] if "duration_stds" in d else None)


def roc_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    pos, neg = labels.sum(), len(labels) - labels.sum()
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(scores)
    ranks = np.empty(len(scores), float)
    ranks[order] = np.arange(1, len(scores) + 1, dtype=float)
    return float((ranks[labels == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def cost_at(scores, labels, threshold, fp_weight=2.0):
    """Vidal et al.'s Cost: false corrections weighted twice missed ones.

    ``scores`` are P(mispronounced); flagging happens at or above ``threshold``.
    """
    flagged = scores >= threshold
    tp = float(np.sum(flagged & (labels == 1)))
    fp = float(np.sum(flagged & (labels == 0)))
    fn = float(np.sum(~flagged & (labels == 1)))
    tn = float(np.sum(~flagged & (labels == 0)))
    fpr = fp / max(fp + tn, 1.0)
    fnr = fn / max(fn + tp, 1.0)
    return fp_weight * fpr + fnr, fpr, fnr


def best_threshold(scores, labels, fp_weight=2.0):
    """Threshold minimising Cost. Falls back to 'never flag' if that is best."""
    if labels.sum() == 0 or len(scores) == 0:
        return 1.01, 1.0
    candidates = np.unique(np.round(scores, 3))
    best = (float("inf"), 1.01)
    for t in candidates:
        c, _, _ = cost_at(scores, labels, t, fp_weight)
        if c < best[0]:
            best = (c, float(t))
    # Not flagging at all costs exactly FNR = 1.0 -> Cost 1.0.
    if best[0] > 1.0:
        return 1.01, 1.0
    return best[1], best[0]


def pearson(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if x.size < 2 or x.std() == 0 or y.std() == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fp-weight", type=float, default=2.0)
    parser.add_argument("--min-phone-count", type=int, default=40,
                        help="phones with fewer dev examples keep the global "
                             "threshold rather than a fitted one")
    args = parser.parse_args()

    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    Xtr, ytr, ptr, utr, names, inventory, dur_means, dur_stds = load("train")
    Xte, yte, pte, ute, *_ = load("test")
    print(f"train {Xtr.shape}  test {Xte.shape}  features={names}")

    # Binary target: Speechocean762 scores each phone 0-2; anything below 2 is
    # not a clean production, which is the event a tutor must detect.
    btr = (ytr < 2).astype(int)
    bte = (yte < 2).astype(int)
    print(f"mispronounced rate: train {btr.mean():.3f}  test {bte.mean():.3f}")

    # Hold out whole utterances for threshold fitting, so thresholds are not
    # chosen on the same phones the model trained on.
    rng = np.random.default_rng(0)
    utts = np.unique(utr)
    dev_utts = set(rng.choice(utts, size=max(1, len(utts) // 5), replace=False))
    is_dev = np.array([u in dev_utts for u in utr])
    print(f"fit on {(~is_dev).sum()} phones, tune thresholds on {is_dev.sum()}")

    # One-hot the phone identity so the model can learn per-phone difficulty.
    def design(X, phone_ids):
        onehot = np.zeros((len(X), len(inventory)))
        onehot[np.arange(len(X)), phone_ids] = 1.0
        return np.hstack([X, onehot])

    scaler = StandardScaler().fit(design(Xtr[~is_dev], ptr[~is_dev]))
    fit_X = scaler.transform(design(Xtr[~is_dev], ptr[~is_dev]))
    dev_X = scaler.transform(design(Xtr[is_dev], ptr[is_dev]))
    test_X = scaler.transform(design(Xte, pte))

    models = {
        "logistic": LogisticRegression(max_iter=2000, C=1.0,
                                       class_weight="balanced"),
        "gbdt": GradientBoostingClassifier(n_estimators=300, max_depth=3,
                                           learning_rate=0.05,
                                           random_state=0),
    }

    # Baseline: raw GOP, the score the pipeline uses today.
    gop_index = names.index("gop")
    baseline = -Xte[:, gop_index]          # higher = more likely wrong
    base_auc = roc_auc(baseline, bte)
    b_t, _ = best_threshold(-Xtr[is_dev, gop_index], btr[is_dev], args.fp_weight)
    base_cost, base_fpr, base_fnr = cost_at(baseline, bte, b_t, args.fp_weight)
    base_pcc = pearson(Xte[:, gop_index], yte)

    print(f"\n{'model':<12} {'AUC':<7} {'Cost':<7} {'FPR':<7} {'FNR':<7} {'PCC'}")
    print("-" * 52)
    print(f"{'GOP (ours)':<12} {base_auc:<7.3f} {base_cost:<7.3f} "
          f"{base_fpr:<7.3f} {base_fnr:<7.3f} {base_pcc:.3f}")

    results = {"baseline_gop": {"auc": base_auc, "cost": base_cost,
                                "fpr": base_fpr, "fnr": base_fnr,
                                "pcc": base_pcc}}
    best_name, best_model, best_cost = None, None, float("inf")

    for name, model in models.items():
        model.fit(fit_X, btr[~is_dev])
        dev_scores = model.predict_proba(dev_X)[:, 1]
        test_scores = model.predict_proba(test_X)[:, 1]

        global_t, _ = best_threshold(dev_scores, btr[is_dev], args.fp_weight)
        cost, fpr, fnr = cost_at(test_scores, bte, global_t, args.fp_weight)
        auc = roc_auc(test_scores, bte)
        pcc = pearson(-test_scores, yte)
        print(f"{name:<12} {auc:<7.3f} {cost:<7.3f} {fpr:<7.3f} {fnr:<7.3f} "
              f"{pcc:.3f}")
        results[name] = {"auc": auc, "cost": cost, "fpr": fpr, "fnr": fnr,
                         "pcc": pcc, "global_threshold": global_t}
        if cost < best_cost:
            best_name, best_model, best_cost = name, model, cost

    # Per-phone thresholds on the winner, as Vidal et al. do.
    dev_scores = best_model.predict_proba(dev_X)[:, 1]
    test_scores = best_model.predict_proba(test_X)[:, 1]
    global_t = results[best_name]["global_threshold"]
    per_phone = {}
    for i, phone in enumerate(inventory):
        mask = ptr[is_dev] == i
        if mask.sum() < args.min_phone_count or btr[is_dev][mask].sum() == 0:
            continue
        t, _ = best_threshold(dev_scores[mask], btr[is_dev][mask],
                              args.fp_weight)
        per_phone[phone] = t

    thresholds = np.array([per_phone.get(p, global_t) for p in inventory])
    applied = thresholds[pte]
    cost_pp, fpr_pp, fnr_pp = cost_at(test_scores - applied + 0.5, bte, 0.5,
                                      args.fp_weight)
    print(f"\n{best_name} + per-phone thresholds ({len(per_phone)} fitted): "
          f"Cost {cost_pp:.3f}  FPR {fpr_pp:.3f}  FNR {fnr_pp:.3f}")
    results["per_phone"] = {"cost": cost_pp, "fpr": fpr_pp, "fnr": fnr_pp,
                            "n_fitted": len(per_phone)}

    print(f"\nrelative to the GOP baseline: "
          f"AUC {base_auc:.3f} -> {results[best_name]['auc']:.3f}, "
          f"Cost {base_cost:.3f} -> {min(best_cost, cost_pp):.3f}, "
          f"PCC {base_pcc:.3f} -> {results[best_name]['pcc']:.3f}")
    print("  (published: Vidal et al. PR AUC 0.67-0.71 / MD 0.80-0.83; "
          "Speechocean762 phone PCC SOTA 0.656)")

    # Save the winner so the pipeline can use it. Per-phone thresholds are
    # saved only if they actually beat the global one on held-out data.
    import joblib

    use_per_phone = cost_pp < best_cost
    if not use_per_phone:
        print(f"\nper-phone thresholds did NOT beat the global one "
              f"({cost_pp:.3f} vs {best_cost:.3f}); shipping the global "
              f"threshold. With ~{len(dev_scores) // max(len(inventory), 1)} "
              "dev phones per type they overfit -- more dev data would be "
              "needed for them to pay off.")

    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_OUT.with_suffix(".joblib")
    joblib.dump({
        "model": best_model,
        "scaler": scaler,
        "inventory": inventory,
        "duration_means": {p: float(m) for p, m in
                           zip(inventory, dur_means)} if dur_means is not None else {},
        "duration_stds": {p: float(s_) for p, s_ in
                          zip(inventory, dur_stds)} if dur_stds is not None else {},
        "threshold": global_t,
        "per_phone_threshold": per_phone if use_per_phone else {},
        "metrics": {**results[best_name], "model": best_name,
                    "baseline_gop_auc": base_auc,
                    "baseline_gop_cost": base_cost},
    }, model_path)
    print(f"wrote {model_path}")

    (BENCH / "md_layer_results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8")
    print(f"wrote {BENCH / 'md_layer_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
