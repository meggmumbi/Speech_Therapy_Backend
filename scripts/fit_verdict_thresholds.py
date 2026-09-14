"""Fit the correct/close verdict thresholds on the current score scale.

    python scripts/fit_verdict_thresholds.py

The verdict runs off ``verdict_score`` -- the worst-phone aggregate of the
per-phone scores. When those scores came from GOP through a clipped linear
mapping, 0.50 was the right boundary. The supervised MD layer emits calibrated
probabilities with an entirely different distribution, so the inherited
threshold is meaningless on it: that is why attempts that should read correct
were sitting at "close".

Method, deliberately matching the rest of the calibration work:

* Thresholds are fitted on the **train** split and reported on **test**. A
  threshold chosen on the data it is then evaluated against flatters itself.
* The objective is **Cost = 2 x FPR + FNR** (Vidal et al., CACM 2024). A false
  correction counts twice a missed error, because telling a learner they
  mispronounced a word they said correctly is the failure that makes them stop
  trusting the tutor -- and it inflates the denominator of H1's DV.
* Two bands against two gold definitions: ``correct`` separates clean words
  (Speechocean762 word accuracy 10) from the rest; ``close`` separates words
  with a *severe* problem (accuracy <= 7) from merely imperfect ones. So
  "close" means measurably imperfect but not badly wrong, rather than being an
  arbitrary band between two numbers.

This scores whole utterances through the real pipeline -- forced alignment,
blank weighting, the MD layer, worst_k aggregation -- rather than replaying
cached features, so what is calibrated is what actually runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from app.services.pronunciation.align import (attach_phones,  # noqa: E402
                                              ctc_forced_align, expand_spans)
from app.services.pronunciation.audio import trim_silence  # noqa: E402
from app.services.pronunciation.config import PipelineConfig  # noqa: E402
from app.services.pronunciation.features import resolve_to_inventory  # noqa: E402
from app.services.pronunciation.gop import (aggregate_score,  # noqa: E402
                                            blank_weights,
                                            compute_phone_scores,
                                            phone_posteriors)
from app.services.pronunciation.md_features import word_positions  # noqa: E402
from app.services.pronunciation.md_scorer import load_md_layer  # noqa: E402
from app.services.pronunciation.runtime import get_model, warmup  # noqa: E402

OUT = Path("benchmarks/verdict_thresholds.json")


def cost_at(scores, labels, threshold, fp_weight=2.0):
    """Cost of calling everything below ``threshold`` a problem."""
    flagged = scores < threshold
    tp = float(np.sum(flagged & (labels == 1)))
    fp = float(np.sum(flagged & (labels == 0)))
    fn = float(np.sum(~flagged & (labels == 1)))
    tn = float(np.sum(~flagged & (labels == 0)))
    fpr = fp / max(fp + tn, 1.0)
    fnr = fn / max(fn + tp, 1.0)
    return fp_weight * fpr + fnr, fpr, fnr, float(flagged.mean())


def fit_threshold(scores, labels, fp_weight=2.0):
    best = (float("inf"), 0.0)
    for t in np.arange(0.01, 1.00, 0.01):
        c, _, _, _ = cost_at(scores, labels, t, fp_weight)
        if c < best[0]:
            best = (c, float(t))
    return best[1], best[0]


def score_split(split: str, config: PipelineConfig, limit: int | None):
    """Word-level verdict scores and gold, through the production path."""
    from benchmark_speechocean import (decode_audio, load_corpus,
                                       word_boundaries)

    model = get_model()
    md_layer = load_md_layer() if config.use_md_layer else None
    ds = load_corpus(split, limit)
    print(f"  {len(ds)} utterances in {split}")

    verdict_scores: list[float] = []
    word_accuracy: list[float] = []

    for n, example in enumerate(ds):
        try:
            waveform, sr = decode_audio(example["audio"])
        except Exception:  # noqa: BLE001
            continue
        waveform, _, _ = trim_silence(waveform, sr)

        spans_meta = word_boundaries(example)
        phones = [str(p).upper()
                  for _, _, w in spans_meta for p in (w.get("phones") or [])]
        if not phones:
            continue
        resolved = resolve_to_inventory(phones, model.phone_to_id)
        if resolved is None:
            continue
        segmental, _ = resolved

        emissions = model.emissions(waveform, sr)
        try:
            spans = ctc_forced_align(
                emissions.log_probs,
                [emissions.phone_to_id[p] for p in segmental],
                blank_id=emissions.blank_id)
        except ValueError:
            continue
        spans = expand_spans(attach_phones(spans, segmental), emissions.n_frames)
        phone_lp, p2i, _ = phone_posteriors(emissions.log_probs,
                                            emissions.phone_to_id)
        weights = blank_weights(emissions.log_probs, emissions.blank_id)

        # Position codes per word, concatenated, so the MD layer sees the same
        # word-initial/medial/final signal it was trained with.
        positions: list[int] = []
        for _, _, w in spans_meta:
            positions.extend(word_positions(len(w.get("phones") or [])))

        scores = compute_phone_scores(
            phone_lp, spans, segmental, p2i, config.gop_floor,
            frame_weights=weights, md_layer=md_layer, positions=positions)

        for lo, hi, word in spans_meta:
            accuracy = word.get("accuracy")
            window = [s for s in scores[lo:hi] if np.isfinite(s.gop)]
            if accuracy is None or not window:
                continue
            verdict_scores.append(aggregate_score(
                window, config.verdict_aggregation,
                duration_weighted=config.duration_weighted_score,
                quantile=config.verdict_quantile, k=config.verdict_worst_k))
            word_accuracy.append(float(accuracy))

        if (n + 1) % 500 == 0:
            print(f"    {n + 1}/{len(ds)}", flush=True)

    return np.asarray(verdict_scores), np.asarray(word_accuracy)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fp-weight", type=float, default=2.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-md", action="store_true",
                        help="calibrate pure GOP instead, for comparison")
    args = parser.parse_args()

    warmup()
    config = PipelineConfig(backend="torch", max_audio_seconds=30.0,
                            use_md_layer=not args.no_md)
    print(f"scoring with use_md_layer={config.use_md_layer}")

    print("fitting on train ...")
    fit_scores, fit_acc = score_split("train", config, args.limit)
    print("evaluating on test ...")
    test_scores, test_acc = score_split("test", config, args.limit)

    results = {"use_md_layer": config.use_md_layer,
               "fp_weight": args.fp_weight,
               "n_fit_words": int(len(fit_scores)),
               "n_test_words": int(len(test_scores))}

    print(f"\nfitted on {len(fit_scores)} words, evaluated on {len(test_scores)}")
    print(f"verdict_score distribution (test): "
          f"p10 {np.percentile(test_scores, 10):.3f}  "
          f"median {np.median(test_scores):.3f}  "
          f"p90 {np.percentile(test_scores, 90):.3f}")

    bands = {
        # "correct" separates clean words from anything imperfect.
        "correct": (fit_acc < 10, test_acc < 10, "word accuracy < 10"),
        # "close" separates severe problems from merely imperfect ones, so the
        # middle band means something rather than being an arbitrary gap.
        "close": (fit_acc <= 7, test_acc <= 7, "word accuracy <= 7"),
    }

    print(f"\n{'band':<9} {'thresh':<8} {'base':<7} {'flagged':<9} "
          f"{'FPR':<7} {'FNR':<7} {'Cost'}")
    print("-" * 58)
    for name, (fit_labels, test_labels, gold) in bands.items():
        t, fit_cost = fit_threshold(fit_scores, fit_labels.astype(int),
                                    args.fp_weight)
        cost, fpr, fnr, rate = cost_at(test_scores, test_labels.astype(int), t,
                                       args.fp_weight)
        print(f"{name:<9} {t:<8.2f} {test_labels.mean():<7.3f} {rate:<9.3f} "
              f"{fpr:<7.3f} {fnr:<7.3f} {cost:.3f}")
        results[name] = {"threshold": t, "gold": gold,
                         "base_rate": float(test_labels.mean()),
                         "flag_rate": rate, "fpr": fpr, "fnr": fnr,
                         "cost": cost, "fit_cost": fit_cost}

    if results["close"]["threshold"] >= results["correct"]["threshold"]:
        print("\n!  close >= correct: the bands have collapsed. Report the "
              "verdict as a two-way correct/incorrect split rather than "
              "inventing a middle band the data does not support.")
        results["bands_collapsed"] = True

    # Keep the raw arrays: re-asking a threshold question should cost a file
    # read, not another full pass over the corpus.
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        OUT.with_suffix(".npz"),
        fit_scores=fit_scores, fit_accuracy=fit_acc,
        test_scores=test_scores, test_accuracy=test_acc,
    )
    print(f"wrote {OUT.with_suffix('.npz')} (raw scores for re-analysis)")
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")
    print("Apply by setting Thresholds.correct / Thresholds.close in "
          "app/services/pronunciation/config.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
