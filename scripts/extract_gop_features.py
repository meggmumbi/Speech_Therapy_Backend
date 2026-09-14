"""Extract per-phone GOP features from Speechocean762 for supervised scoring.

    python scripts/extract_gop_features.py --split train
    python scripts/extract_gop_features.py --split test

Our pipeline currently implements what Vidal et al. (CACM 2024) call the **PR**
approach: phone posteriors from a model trained only on native speech, turned
into a score by the standard GOP formula. They measure that approach at
AUC 0.67-0.71 on EpaDB, against 0.80-0.83 for the **MD** approach -- a layer
trained on *non-native* speech with human pronunciation labels. El Kheir et al.
(EMNLP 2023) report the same ordering: GOP-HMM-DNN around 44-45% F1 versus
54-63% for supervised and SSL methods.

That gap is the one worth closing, and it does not need a bigger model or a
better lexicon: it needs supervision. Speechocean762 supplies it -- 5,000
utterances with expert 0-2 accuracy scores on every phone, five annotators each.

This script writes the features; train_md_layer.py fits the model. Features per
target phone, following the GOP-feature literature:

  * gop                 log-posterior ratio, the classical score
  * mean_log_post       mean log P(target | frame) over the span
  * mean_post           the same in probability space
  * margin              target minus best competitor, in log space
  * competitor_post     how strong the best rival phone was
  * entropy             mean frame entropy -- Shi et al. (2020) weight GOP by
                        this, since a confident frame is worth more than an
                        ambiguous one
  * min_log_post        worst single frame, which catches brief gross errors
                        that an average hides
  * n_frames            realised duration
  * duration_z          duration against that phone's own mean, so "too short"
                        is measurable rather than implied
  * evidence            total non-blank weight in the span
  * position            0 = word-initial, 1 = medial, 2 = final
  * phone_id            identity, so the model can learn per-phone difficulty
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
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
from app.services.pronunciation.gop import (blank_weights,  # noqa: E402
                                            phone_posteriors)
from app.services.pronunciation.md_features import (FEATURE_NAMES,  # noqa: E402
                                                    DurationStats,
                                                    phone_feature_vector)
from app.services.pronunciation.runtime import get_model, warmup  # noqa: E402

FEATURE_NAMES = list(FEATURE_NAMES)


def phone_features(phone_lp, weights, span, pid, phone, position):
    """Thin wrapper: the real implementation lives in the package, so the
    serving path computes exactly these features."""
    return phone_feature_vector(phone_lp, weights, span, pid, phone, position,
                                duration_stats=None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", default="train")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default="benchmarks")
    args = parser.parse_args()

    from benchmark_speechocean import decode_audio, load_corpus, word_boundaries

    warmup()
    model = get_model()
    config = PipelineConfig(backend="torch", max_audio_seconds=30.0)

    print(f"loading speechocean762 [{args.split}] ...")
    ds = load_corpus(args.split, args.limit)
    print(f"  {len(ds)} utterances")

    # Two passes: the first collects per-phone duration statistics so that
    # "unusually short" is measured against the phone's own norm rather than a
    # global one -- a /t/ and an /iy/ have very different expected lengths.
    durations: dict[str, list[int]] = defaultdict(list)
    rows: list[dict] = []

    for n, example in enumerate(ds):
        try:
            waveform, sr = decode_audio(example["audio"])
        except Exception:  # noqa: BLE001
            continue
        waveform, _, _ = trim_silence(waveform, sr)

        phones, golds = [], []
        positions = []
        for lo, hi, word in word_boundaries(example):
            word_phones = [str(p).upper() for p in (word.get("phones") or [])]
            accuracies = word.get("phones-accuracy") or []
            if len(accuracies) != len(word_phones):
                accuracies = [float("nan")] * len(word_phones)
            for i, (p, a) in enumerate(zip(word_phones, accuracies)):
                phones.append(p)
                golds.append(float(a))
                positions.append(0 if i == 0 else
                                 (2 if i == len(word_phones) - 1 else 1))
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
        spans = expand_spans(attach_phones(spans, segmental),
                             emissions.n_frames)
        phone_lp, p2i, _ = phone_posteriors(emissions.log_probs,
                                            emissions.phone_to_id)
        weights = blank_weights(emissions.log_probs, emissions.blank_id)

        for span, phone, gold, pos in zip(spans, segmental, golds, positions):
            if np.isnan(gold):
                continue
            # Compute now and keep only the numbers: holding 2,500 emission
            # matrices to defer this would cost hundreds of megabytes.
            feats = phone_features(phone_lp, weights, span, p2i[phone],
                                   phone, pos)
            if feats is None:
                continue
            durations[phone].append(span.end_frame - span.start_frame)
            rows.append({"feats": feats, "phone": phone, "gold": gold,
                         "n_frames": span.end_frame - span.start_frame,
                         "utt": n})

        if (n + 1) % 250 == 0:
            print(f"    {n + 1}/{len(ds)} utterances, {len(rows)} phones",
                  flush=True)

    stats = {p: (float(np.mean(v)), float(np.std(v)))
             for p, v in durations.items()}
    # duration_z at inference must use the same norms, so they ship with the
    # features and are saved into the model by train_md_layer.py.
    duration_means = np.array([stats[p][0] for p in sorted(stats)])
    duration_stds = np.array([stats[p][1] for p in sorted(stats)])

    X, y, phone_ids, utt_ids = [], [], [], []
    inventory = sorted(stats)
    index = {p: i for i, p in enumerate(inventory)}
    z_index = FEATURE_NAMES.index("duration_z")
    for row in rows:
        feats = list(row["feats"])
        # duration_z needs the phone's own mean, which is only known after the
        # full pass, so it is filled in here rather than in the loop.
        mean_dur, std_dur = stats[row["phone"]]
        feats[z_index] = ((row["n_frames"] - mean_dur) / std_dur
                          if std_dur > 0 else 0.0)
        X.append(feats)
        y.append(row["gold"])
        phone_ids.append(index[row["phone"]])
        utt_ids.append(row["utt"])

    out = Path(args.out) / f"gop-features-{args.split}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        X=np.asarray(X, dtype=np.float32),
        y=np.asarray(y, dtype=np.float32),
        phone_ids=np.asarray(phone_ids, dtype=np.int32),
        utt_ids=np.asarray(utt_ids, dtype=np.int32),
        feature_names=np.array(FEATURE_NAMES),
        inventory=np.array(inventory),
        duration_means=duration_means,
        duration_stds=duration_stds,
    )
    y_arr = np.asarray(y)
    print(f"\nwrote {out}")
    print(f"  {len(X)} phones, {len(FEATURE_NAMES)} features, "
          f"{len(inventory)} phone types")
    print(f"  gold 0-2: mean {y_arr.mean():.2f}, "
          f"mispronounced (<2): {(y_arr < 2).mean():.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
