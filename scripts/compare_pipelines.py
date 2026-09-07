"""Side-by-side: the text pipeline vs the acoustic pipeline on study items.

Run:  python scripts/compare_pipelines.py

The acoustic side uses the stub backend, which synthesises emissions from a
stated phone sequence. That means this script demonstrates *what each pipeline
does with a known production* -- it is not evidence about real audio, and no
number here belongs in a paper. It exists to make the behavioural difference
concrete, and each case below is drawn from the study's own stimuli.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pronunciation import (PipelineConfig, StubAcousticModel,  # noqa: E402
                                        score_attempt)

SR = 16_000

# (target, transcript the ASR would return, phones actually produced, why it matters)
CASES = [
    ("draught", "drought", ["D", "R", "AW", "T"],
     "different vowel; spelling is nearly identical"),
    ("colonel", "kernel", ["K", "ER", "N", "AH", "L"],
     "homophone: pronounced correctly, spelled nothing alike"),
    ("think", "tink", ["T", "IH", "NG", "K"],
     "TH -> T, the canonical L2 substitution"),
    ("mischievous", "mischievious", ["M", "IH", "S", "CH", "IY", "V", "IY", "AH", "S"],
     "extra syllable: localised vowel errors plus one insertion, "
     "not a cascade over every following phone"),
    ("cat", "cat", ["K", "AE", "T"],
     "control: correct production"),
]


def waveform(n_phones: int) -> np.ndarray:
    seconds = max(n_phones * 5 * 0.02, 0.25)
    t = np.arange(int(seconds * SR)) / SR
    return (0.2 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)


def main() -> int:
    from app.services.pronunciation_pipeline import analyse_pronunciation

    config = PipelineConfig(backend="stub")
    print(f"{'target':<13} {'said':<14} {'TEXT pipeline':<28} {'ACOUSTIC pipeline'}")
    print("-" * 100)

    for target, transcript, produced, note in CASES:
        old = analyse_pronunciation(target, transcript)
        old_desc = (f"{old['similarity_score']:.2f} "
                    f"{'correct' if old['is_correct'] else old['error_type']}")

        model = StubAcousticModel(produced=produced, frames_per_phone=5,
                                  confidence=0.95)
        new = score_attempt(target, waveform(len(produced)), SR, model, config)
        detail = ""
        if new.diagnoses:
            d = new.diagnoses[0]
            detail = f" [{d.expected}->{d.observed or '-'} {d.kind}]"
        new_desc = f"{new.score:.2f} {new.verdict}{detail}"

        print(f"{target:<13} {transcript:<14} {old_desc:<28} {new_desc}")
        print(f"{'':<28}{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
