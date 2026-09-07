"""Print the robot's utterance for both conditions, on the study's own items.

    python scripts/demo_feedback.py

Uses the stub backend, so the "produced" phone sequence is stated rather than
recognised: this shows what the robot SAYS given a known production, not how
well it recognises one. Read it as a script review, not as evidence.

Worth checking here, because these are the exact strings participants hear and
the basis of the H5 feedback-quality ratings: that K and D open with the same
warmth marker, that both re-model the word, that D adds exactly one diagnosis
and one cue, and that no ARPAbet ever reaches the speaker.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pronunciation import (PipelineConfig,  # noqa: E402
                                        StubAcousticModel, score_attempt)
from app.services.pronunciation.feedback import (arpabet_tokens_in,  # noqa: E402
                                                 generate_feedback)

SR = 16_000

CASES = [
    ("think", ["T", "IH", "NG", "K"], 0.95, "TH -> T, the canonical L2 substitution"),
    ("draught", ["D", "R", "AW", "T"], 0.95, "wrong vowel"),
    ("very", ["W", "EH", "R", "IY"], 0.95, "V -> W"),
    ("cat", ["K", "AE", "T"], 0.95, "correct production"),
    ("draught", ["D", "R", "AE", "F", "T"], 0.05, "low recogniser confidence"),
]


def waveform(n_phones: int) -> np.ndarray:
    seconds = max(n_phones * 5 * 0.02, 0.25)
    t = np.arange(int(seconds * SR)) / SR
    return (0.2 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)


def main() -> int:
    config = PipelineConfig(backend="stub")
    leaks = 0

    for n, (word, produced, confidence, note) in enumerate(CASES):
        model = StubAcousticModel(produced=produced, frames_per_phone=5,
                                  confidence=confidence)
        result = score_attempt(word, waveform(len(produced)), SR, model, config)

        print(f"\n{word!r} — {note}")
        print(f"  verdict={result.verdict} score={result.score:.2f} "
              f"verdict_score={result.verdict_score:.2f} "
              f"confidence={result.confidence:.2f}")

        for condition in ("K", "D"):
            fb = generate_feedback(result, word, condition, attempt_index=n)
            found = arpabet_tokens_in(fb.speech)
            leaks += len(found)
            flag = f"  !! ARPAbet leak: {found}" if found else ""
            print(f"  [{condition}] ({fb.word_count:2d}w) {fb.speech}{flag}")

    print(f"\nARPAbet leaks: {leaks}")
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
