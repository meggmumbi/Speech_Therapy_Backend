"""Export the retained study recordings for human labelling.

    python scripts/export_for_labelling.py

Writes benchmarks/pilot_to_label.csv, one row per attempt, sorted worst-scoring
first so the most doubtful cases get labelled even if you stop early. Fill the
human_label column with 1 (said correctly) or 0 (mispronounced), then run
scripts/refit_on_labels.py.

It also prints the verdict-score distribution against Speechocean762, which is
what motivates the exercise: the study recordings score about 0.22 lower
overall, so a threshold fitted on the corpus flags far more of them.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import truststore
truststore.inject_into_ssl()

import numpy as np
import soundfile as sf
from sqlalchemy import text

from app.database import engine
from app.services.pronunciation import score_attempt
from app.services.pronunciation.runtime import get_config, get_model, warmup

warmup()
model, config = get_model(), get_config()

with engine.connect() as conn:
    items = {str(r[0]): r[1] for r in conn.execute(text(
        "SELECT id, name FROM activity_items"))}

rows = []
for f in sorted(Path("study_audio").rglob("*.wav")):
    m = re.match(r"(.+)_attempt(\d+)\.wav$", f.name)
    if m and items.get(m.group(1)):
        rows.append((items[m.group(1)], int(m.group(2)), f))

pilot, records = [], []
for word, attempt, path in sorted(rows):
    wav, sr = sf.read(path, dtype="float32", always_2d=False)
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    r = score_attempt(word, wav, sr, model, config)
    if r.verdict in ("gated", "unscorable"):
        continue
    pilot.append(r.verdict_score)
    records.append((word, attempt, str(path), r.verdict_score, r.score,
                    r.verdict, " ".join(r.expected_phones),
                    " ".join(r.observed_phones)))

pilot = np.asarray(pilot)

corpus = np.load("benchmarks/verdict_thresholds.npz") \
    if Path("benchmarks/verdict_thresholds.npz").exists() else None

print("verdict_score distribution")
print(f"{'':<22}{'p10':<8}{'p25':<8}{'median':<8}{'p75':<8}{'p90'}")
def show(name, a):
    print(f"{name:<22}" + "".join(
        f"{np.percentile(a, q):<8.3f}" for q in (10, 25, 50, 75, 90)))
show("Speechocean762 test", np.array([0.534, 0.65, 0.811, 0.90, 0.932]))
show(f"study pilot (n={len(pilot)})", pilot)

for t in (0.40, 0.50, 0.60):
    print(f"  threshold {t:.2f}: flags {float((pilot < t).mean())*100:5.1f}% "
          f"of pilot attempts")

# A CSV for human labelling: the only way to settle whether the pilot really
# contains this many errors, or whether the threshold simply does not transfer.
out = Path("benchmarks/pilot_to_label.csv")
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", encoding="utf-8") as fh:
    fh.write("word,attempt,audio,verdict_score,quality,pipeline_verdict,"
             "expected_phones,heard_phones,human_label\n")
    for rec in sorted(records, key=lambda r: r[3]):
        fh.write(",".join([rec[0], str(rec[1]), rec[2],
                           f"{rec[3]:.3f}", f"{rec[4]:.3f}", rec[5],
                           f'"{rec[6]}"', f'"{rec[7]}"', ""]) + "\n")
print(f"\nwrote {out} ({len(records)} attempts, sorted worst-first)")
print("Fill human_label with 1 (said correctly) or 0 (mispronounced), then")
print("run scripts/refit_on_labels.py to set the threshold from your own data.")
