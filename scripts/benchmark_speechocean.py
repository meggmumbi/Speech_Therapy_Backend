"""Benchmark candidate acoustic models on Speechocean762.

Speechocean762 (Zhang et al., 2021) is an open L2-English corpus with expert
phone-level accuracy scores (0-2) and utterance-level scores (0-10). It is the
standard yardstick for GOP and mispronunciation-detection systems, which is
exactly what makes it useful here: it lets the model be chosen on measured
agreement with human raters instead of on assertion, and it gives the paper a
comparison against published baselines that is independent of our own data.

    python scripts/benchmark_speechocean.py --model charsiu/en_w2v2_fc_10ms
    python scripts/benchmark_speechocean.py --model A --model B --limit 300

Reports, per model:

* **Utterance PCC** -- Pearson correlation of our 0-1 score against the expert
  0-10 accuracy score. This is the number published GOP baselines report.
* **Phone-level detection** -- ROC AUC and best-F1 for "is this phone
  mispronounced", under both binarisations used in the literature
  (accuracy < 2, and accuracy == 0).
* **Latency** -- p50/p95 milliseconds per utterance and per second of audio,
  measured on this machine. This is what decides whether the p95 < 2.5 s
  interaction budget survives on the study laptop.

Nothing here selects a threshold for production use: the operating point for
the study must be fitted on the rater-adjudicated sample, not on this corpus.
The best-F1 reported below is an upper bound on achievable performance, and is
labelled as such.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    # This machine sits behind a TLS-inspecting proxy whose root CA is in the
    # Windows certificate store but not in certifi's bundle, so huggingface.co
    # fails certificate verification without this. Optional: absent elsewhere.
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from app.services.pronunciation import PipelineConfig  # noqa: E402
from app.services.pronunciation.acoustic import (HFCTCAcousticModel,  # noqa: E402
                                                 assert_phone_level)
from app.services.pronunciation.features import resolve_to_inventory  # noqa: E402
from app.services.pronunciation.scoring import score_phone_sequence  # noqa: E402

DATASET_ID = "mispeech/speechocean762"
TARGET_SR = 16_000


@dataclass
class Collected:
    """Paired model output and human labels, accumulated over the corpus."""

    utt_pred: list[float] = field(default_factory=list)
    utt_gold: list[float] = field(default_factory=list)
    phone_pred: list[float] = field(default_factory=list)
    phone_gold: list[float] = field(default_factory=list)
    # Raw GOP alongside the calibrated 0-1 score. Published baselines
    # correlate on GOP itself; our exp() mapping is monotone but non-linear,
    # so it can only lose Pearson correlation. Reporting both separates "the
    # acoustic evidence is weak" from "the score mapping is badly shaped".
    utt_pred_gop: list[float] = field(default_factory=list)
    phone_pred_gop: list[float] = field(default_factory=list)
    # Word level. This, not phone level, is the granularity the study's
    # primary DV runs at: H1 counts whether the *word* was corrected on the
    # second attempt. Phone-level detection only has to be good enough to
    # justify what the robot says after the verdict.
    word_pred: list[float] = field(default_factory=list)
    word_gold: list[float] = field(default_factory=list)
    # Per-word phone scores, kept so aggregation methods can be swept offline
    # in seconds instead of costing a 20-minute model re-run each.
    word_groups: list[list[float]] = field(default_factory=list)
    # Diagnosis accuracy: of the substitutions we name, how many match the
    # phone pair the raters recorded.
    diag_attempted: int = 0
    diag_correct_phone: int = 0
    diag_correct_pair: int = 0
    latency_ms: list[float] = field(default_factory=list)
    audio_seconds: list[float] = field(default_factory=list)
    stage_ms: dict[str, list[float]] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


def _pearson(x: list[float], y: list[float]) -> float:
    if len(x) < 2:
        return float("nan")
    a, b = np.asarray(x, float), np.asarray(y, float)
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _spearman(x: list[float], y: list[float]) -> float:
    if len(x) < 2:
        return float("nan")
    def rank(v: list[float]) -> np.ndarray:
        order = np.argsort(np.asarray(v, float))
        ranks = np.empty(len(v), float)
        ranks[order] = np.arange(len(v), dtype=float)
        return ranks
    return _pearson(list(rank(x)), list(rank(y)))


def _roc_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """AUC via the rank-sum identity; no sklearn dependency needed."""
    pos, neg = labels.sum(), len(labels) - labels.sum()
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(scores)
    ranks = np.empty(len(scores), float)
    ranks[order] = np.arange(1, len(scores) + 1, dtype=float)
    return float((ranks[labels == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def _at_precision(scores: np.ndarray, labels: np.ndarray, floor: float
                  ) -> tuple[float, float]:
    """Best recall achievable while holding precision at or above ``floor``.

    This, not best-F1, is the number that decides whether a diagnosis is safe
    to speak aloud. A tutor that flags a correct phone as wrong teaches the
    learner to distrust it, so the operating point has to be chosen for
    precision and the recall cost accepted -- "I did not catch that, try
    again" is a fine fallback; "you said T instead of TH" when they did not is
    not. Returns ``(recall, threshold)``, or ``(nan, nan)`` if the floor is
    unreachable.
    """
    best = (float("nan"), float("nan"))
    best_recall = -1.0
    for threshold in np.unique(scores):
        predicted = scores <= threshold
        tp = float(np.sum(predicted & (labels == 1)))
        fp = float(np.sum(predicted & (labels == 0)))
        fn = float(np.sum(~predicted & (labels == 1)))
        if tp == 0:
            continue
        precision = tp / (tp + fp)
        if precision < floor:
            continue
        recall = tp / (tp + fn)
        if recall > best_recall:
            best_recall, best = recall, (recall, float(threshold))
    return best


def _best_f1(scores: np.ndarray, labels: np.ndarray) -> tuple[float, float, float, float]:
    """Best achievable F1 over all thresholds, with its precision and recall.

    An *upper bound*: the threshold is chosen on the same data it is scored
    on. Reported to show headroom, never as an operating point.
    """
    if labels.sum() == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")
    best = (0.0, 0.0, 0.0, 0.0)
    for threshold in np.unique(scores):
        predicted = scores <= threshold          # low score => mispronounced
        tp = float(np.sum(predicted & (labels == 1)))
        fp = float(np.sum(predicted & (labels == 0)))
        fn = float(np.sum(~predicted & (labels == 1)))
        if tp == 0:
            continue
        precision = tp / (tp + fp)
        recall = tp / (tp + fn)
        f1 = 2 * precision * recall / (precision + recall)
        if f1 > best[0]:
            best = (f1, precision, recall, float(threshold))
    return best


def load_corpus(split: str, limit: int | None):
    """Load the corpus with audio decoding left to us.

    ``datasets`` 4.x decodes audio through torchcodec, which needs a system
    FFmpeg that the study machine does not have. Speechocean762 ships plain
    16 kHz WAV, so ``decode=False`` plus soundfile sidesteps the dependency
    entirely -- one less thing to install on the machine that will run the
    study.
    """
    from datasets import Audio, load_dataset

    ds = load_dataset(DATASET_ID, split=split)
    ds = ds.cast_column("audio", Audio(decode=False))
    if limit:
        ds = ds.select(range(min(limit, len(ds))))
    return ds


def decode_audio(entry: dict) -> tuple[np.ndarray, int]:
    """Undecoded ``Audio`` entry -> mono float32 waveform at 16 kHz."""
    import io

    import soundfile as sf

    from app.services.pronunciation.audio import to_mono_float32

    raw = entry.get("bytes")
    source = io.BytesIO(raw) if raw else entry["path"]
    data, sample_rate = sf.read(source, dtype="float32", always_2d=False)
    waveform = to_mono_float32(data)
    if sample_rate != TARGET_SR:
        import librosa
        waveform = librosa.resample(waveform, orig_sr=sample_rate,
                                    target_sr=TARGET_SR)
        sample_rate = TARGET_SR
    return waveform, sample_rate


def word_boundaries(example: dict) -> list[tuple[int, int, dict]]:
    """Index ranges into the flattened phone sequence, one per word."""
    spans: list[tuple[int, int, dict]] = []
    cursor = 0
    for word in example.get("words", []):
        n = len(word.get("phones") or [])
        spans.append((cursor, cursor + n, word))
        cursor += n
    return spans


def gold_mispronounced_pairs(word: dict) -> set[tuple[str, str]]:
    """(canonical, pronounced) phone pairs the raters recorded for one word."""
    pairs: set[tuple[str, str]] = set()
    for m in word.get("mispronunciations") or []:
        canonical = str(m.get("canonical-phone", "")).upper().rstrip("012")
        pronounced = str(m.get("pronounced-phone", "")).upper().rstrip("012")
        if canonical:
            pairs.add((canonical, pronounced))
    return pairs


def expected_phones_and_gold(example: dict) -> tuple[list[str], list[float]]:
    """Flatten the per-word annotation into one phone sequence plus labels.

    Speechocean762 annotates each word with its canonical phones and an expert
    accuracy score per phone. Using the corpus's own canonical sequence rather
    than a CMUdict lookup matters: scoring against a different target than the
    raters judged would show up as model error that is really a lexicon
    mismatch.
    """
    phones: list[str] = []
    gold: list[float] = []
    for word in example.get("words", []):
        word_phones = word.get("phones") or []
        accuracies = word.get("phones-accuracy") or []
        if len(accuracies) != len(word_phones):
            # Annotation gaps exist; keep the phones for alignment context but
            # exclude them from the phone-level metrics.
            accuracies = [float("nan")] * len(word_phones)
        phones.extend(str(p).upper() for p in word_phones)
        gold.extend(float(a) for a in accuracies)
    return phones, gold


def run_model(model_id: str, ds, config: PipelineConfig, progress_every: int
              ) -> Collected:
    model = HFCTCAcousticModel(model_id, device=config.device,
                               frame_stride_s=config.frame_stride_s)
    assert_phone_level(model)
    info = model.describe()
    print(f"  inventory: {info.n_labels} labels, "
          f"{len(info.inventory)} mapped to ARPAbet")
    model.warmup()

    collected = Collected()
    for n, example in enumerate(ds):
        try:
            waveform, sample_rate = decode_audio(example["audio"])
        except Exception as exc:  # noqa: BLE001 - a corrupt file must not stop the run
            collected.skip(f"audio decode failed: {type(exc).__name__}")
            continue

        phones, gold = expected_phones_and_gold(example)
        if not phones:
            collected.skip("no phone annotation")
            continue
        # The model's inventory is stress-free; the corpus marks stress.
        # Folding (e.g. AO -> AA on TIMIT-39 models) is allowed here for the
        # same reason it is allowed live -- but it is counted, because every
        # fold is a contrast the model cannot be credited with detecting.
        if resolve_to_inventory(phones, model.phone_to_id) is None:
            collected.skip("phone outside model inventory")
            continue

        started = time.perf_counter()
        result = score_phone_sequence(
            example.get("text", f"utt{n}"), [phones], waveform, sample_rate,
            model, config,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        if result.verdict in ("unscorable", "gated"):
            collected.skip(result.note or result.verdict)
            continue

        collected.latency_ms.append(elapsed_ms)
        collected.audio_seconds.append(len(waveform) / sample_rate)
        for stage, ms in result.timings.stages.items():
            collected.stage_ms.setdefault(stage, []).append(ms)

        finite = [s for s in result.phone_scores if np.isfinite(s.gop)]
        weights = np.array([max(s.end_frame - s.start_frame, 1) for s in finite],
                           dtype=float)
        utt_gop = (float(np.average([s.gop for s in finite], weights=weights))
                   if finite else float("nan"))

        human = example.get("accuracy")
        if human is not None and np.isfinite(utt_gop):
            collected.utt_pred.append(result.score)
            collected.utt_pred_gop.append(utt_gop)
            collected.utt_gold.append(float(human))

        for score, label in zip(result.phone_scores, gold):
            if not np.isnan(label) and np.isfinite(score.gop):
                collected.phone_pred.append(score.score)
                collected.phone_pred_gop.append(score.gop)
                collected.phone_gold.append(label)

        by_index = {d.index: d for d in result.diagnoses}
        for lo, hi, word in word_boundaries(example):
            window = [s for s in result.phone_scores[lo:hi] if np.isfinite(s.gop)]
            word_accuracy = word.get("accuracy")
            if window and word_accuracy is not None:
                weights = np.array([max(s.end_frame - s.start_frame, 1)
                                    for s in window], dtype=float)
                collected.word_pred.append(
                    float(np.average([s.score for s in window], weights=weights)))
                collected.word_gold.append(float(word_accuracy))
                collected.word_groups.append([float(s.score) for s in window])

            gold_pairs = gold_mispronounced_pairs(word)
            if not gold_pairs:
                continue
            gold_phones = {c for c, _ in gold_pairs}
            for idx in range(lo, hi):
                d = by_index.get(idx)
                if d is None or d.kind not in ("substitution", "weak"):
                    continue
                collected.diag_attempted += 1
                expected = d.expected.upper().rstrip("012")
                observed = (d.observed or "").upper().rstrip("012")
                if expected in gold_phones:
                    collected.diag_correct_phone += 1
                    if (expected, observed) in gold_pairs:
                        collected.diag_correct_pair += 1

        if progress_every and (n + 1) % progress_every == 0:
            print(f"    {n + 1}/{len(ds)} utterances", flush=True)

    return collected


def report(model_id: str, c: Collected) -> dict:
    pred = np.asarray(c.phone_pred, float)
    gold = np.asarray(c.phone_gold, float)
    latency = np.asarray(c.latency_ms, float)
    seconds = np.asarray(c.audio_seconds, float)

    out: dict = {
        "model": model_id,
        "n_utterances": len(c.latency_ms),
        "n_phones": int(len(pred)),
        "skipped": c.skipped,
        "utterance_pcc": _pearson(c.utt_pred, c.utt_gold),
        "utterance_pcc_raw_gop": _pearson(c.utt_pred_gop, c.utt_gold),
        "utterance_spearman": _spearman(c.utt_pred, c.utt_gold),
        "phone_pcc": _pearson(list(pred), list(gold)),
        "phone_pcc_raw_gop": _pearson(c.phone_pred_gop, list(gold)),
        "n_words": len(c.word_pred),
        "word_pcc": _pearson(c.word_pred, c.word_gold),
        "diagnosis": {
            "attempted": c.diag_attempted,
            "correct_phone_rate": (c.diag_correct_phone / c.diag_attempted
                                   if c.diag_attempted else float("nan")),
            "correct_pair_rate": (c.diag_correct_pair / c.diag_attempted
                                  if c.diag_attempted else float("nan")),
        },
    }

    word_pred = np.asarray(c.word_pred, float)
    word_gold = np.asarray(c.word_gold, float)
    for name, labels in (("word_lt_10", (word_gold < 10).astype(int)),
                         ("word_le_7", (word_gold <= 7).astype(int))):
        f1, precision, recall, threshold = _best_f1(word_pred, labels)
        r80, _ = _at_precision(word_pred, labels, 0.80)
        r70, _ = _at_precision(word_pred, labels, 0.70)
        out[f"detect_{name}"] = {
            "positive_rate": float(labels.mean()) if len(labels) else float("nan"),
            "roc_auc": _roc_auc(-word_pred, labels),
            "best_f1_upper_bound": f1,
            "precision_at_best": precision,
            "recall_at_best": recall,
            "recall_at_precision_80": r80,
            "recall_at_precision_70": r70,
        }

    for name, labels in (("acc_lt_2", (gold < 2).astype(int)),
                         ("acc_eq_0", (gold == 0).astype(int))):
        f1, precision, recall, threshold = _best_f1(pred, labels)
        r80, t80 = _at_precision(pred, labels, 0.80)
        r60, t60 = _at_precision(pred, labels, 0.60)
        out[f"detect_{name}"] = {
            "positive_rate": float(labels.mean()) if len(labels) else float("nan"),
            "roc_auc": _roc_auc(-pred, labels),   # low score => positive
            "best_f1_upper_bound": f1,
            "precision_at_best": precision,
            "recall_at_best": recall,
            "threshold_at_best": threshold,
            "recall_at_precision_80": r80,
            "threshold_at_precision_80": t80,
            "recall_at_precision_60": r60,
            "threshold_at_precision_60": t60,
        }

    if len(latency):
        out["latency"] = {
            "p50_ms": float(np.percentile(latency, 50)),
            "p95_ms": float(np.percentile(latency, 95)),
            "mean_ms_per_audio_second": float(latency.sum() / max(seconds.sum(), 1e-9)),
            "mean_audio_seconds": float(seconds.mean()),
            "stage_mean_ms": {k: float(np.mean(v)) for k, v in c.stage_ms.items()},
        }
    return out


def print_report(r: dict) -> None:
    print(f"\n  {r['model']}")
    print(f"    utterances scored : {r['n_utterances']}  "
          f"phones scored: {r['n_phones']}")
    if r["skipped"]:
        for reason, count in sorted(r["skipped"].items(), key=lambda kv: -kv[1])[:4]:
            print(f"    skipped           : {count}x {reason}")
    print(f"    utterance PCC     : {r['utterance_pcc']:.3f} mapped / "
          f"{r['utterance_pcc_raw_gop']:.3f} raw GOP  "
          f"(Spearman {r['utterance_spearman']:.3f})")
    print(f"    phone-level PCC   : {r['phone_pcc']:.3f} mapped / "
          f"{r['phone_pcc_raw_gop']:.3f} raw GOP")
    for name in ("acc_lt_2", "acc_eq_0"):
        d = r[f"detect_{name}"]
        print(f"    detect {name:<9}: AUC {d['roc_auc']:.3f}  "
              f"best-F1 {d['best_f1_upper_bound']:.3f} (upper bound, "
              f"P {d['precision_at_best']:.2f} / R {d['recall_at_best']:.2f}, "
              f"base rate {d['positive_rate']:.2f})")
    print(f"    WORD level        : n={r['n_words']}  PCC {r['word_pcc']:.3f}")
    for name in ("word_lt_10", "word_le_7"):
        d = r.get(f"detect_{name}")
        if not d:
            continue
        print(f"      {name:<11}: AUC {d['roc_auc']:.3f}  "
              f"best-F1 {d['best_f1_upper_bound']:.3f} (ub)  "
              f"recall@P.80 {d['recall_at_precision_80']:.3f}  "
              f"recall@P.70 {d['recall_at_precision_70']:.3f}  "
              f"base {d['positive_rate']:.3f}")
    dg = r["diagnosis"]
    print(f"    diagnosis         : {dg['attempted']} named; "
          f"right phone {dg['correct_phone_rate']:.3f}, "
          f"right phone+substitute {dg['correct_pair_rate']:.3f}")
    for name in ("acc_lt_2",):
        d = r[f"detect_{name}"]
        print(f"    safe operating pt : recall {d['recall_at_precision_80']:.3f} "
              f"@ precision 0.80  |  recall {d['recall_at_precision_60']:.3f} "
              f"@ precision 0.60")
    lat = r.get("latency")
    if lat:
        print(f"    latency           : p50 {lat['p50_ms']:.0f} ms, "
              f"p95 {lat['p95_ms']:.0f} ms  "
              f"({lat['mean_ms_per_audio_second']:.0f} ms per audio second, "
              f"mean utterance {lat['mean_audio_seconds']:.2f} s)")
        stages = sorted(lat["stage_mean_ms"].items(), key=lambda kv: -kv[1])
        print("    stage breakdown   : " +
              ", ".join(f"{k} {v:.0f}ms" for k, v in stages))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True,
                        help="HuggingFace model id; repeat to compare several")
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=None,
                        help="score only the first N utterances (for a smoke run)")
    parser.add_argument("--out", default="benchmarks",
                        help="directory for the JSON results")
    parser.add_argument("--progress-every", type=int, default=100)
    args = parser.parse_args()

    print(f"Loading {DATASET_ID} [{args.split}] ...")
    ds = load_corpus(args.split, args.limit)
    print(f"  {len(ds)} utterances")

    # Speechocean762 is sentence-length; the 4 s cap that protects the live
    # single-word path would reject most of the corpus.
    config = PipelineConfig(backend="torch", max_audio_seconds=30.0)

    results = []
    raw: dict[str, Collected] = {}
    for model_id in args.model:
        print(f"\nScoring with {model_id} ...")
        try:
            collected = run_model(model_id, ds, config, args.progress_every)
        except Exception as exc:  # noqa: BLE001 - one bad model must not stop the sweep
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            results.append({"model": model_id, "error": f"{type(exc).__name__}: {exc}"})
            continue
        raw[model_id] = collected
        r = report(model_id, collected)
        print_report(r)
        results.append(r)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Save the raw paired arrays: re-running the sweep to answer a new
    # question about the operating point costs 20 minutes of laptop; reloading
    # an .npz costs nothing.
    for model_id, collected in raw.items():
        np.savez_compressed(
            out_dir / f"raw-{model_id.replace('/', '__')}.npz",
            phone_pred=np.asarray(collected.phone_pred, float),
            phone_pred_gop=np.asarray(collected.phone_pred_gop, float),
            phone_gold=np.asarray(collected.phone_gold, float),
            utt_pred=np.asarray(collected.utt_pred, float),
            utt_pred_gop=np.asarray(collected.utt_pred_gop, float),
            utt_gold=np.asarray(collected.utt_gold, float),
            word_pred=np.asarray(collected.word_pred, float),
            word_gold=np.asarray(collected.word_gold, float),
            group_flat=np.asarray(
                [v for g in collected.word_groups for v in g], float),
            group_offsets=np.cumsum(
                [0] + [len(g) for g in collected.word_groups]).astype(np.int64),
            latency_ms=np.asarray(collected.latency_ms, float),
            audio_seconds=np.asarray(collected.audio_seconds, float),
        )
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"speechocean762-{args.split}-{stamp}.json"
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
