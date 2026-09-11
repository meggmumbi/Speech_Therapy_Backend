"""Fetch and convert the BEEP British English pronunciation dictionary.

    python scripts/fetch_beep.py

BEEP (Cambridge, ~238,000 words) is the British counterpart to CMUdict. It is
needed because CMUdict is General American and the study's speakers are Kenyan
English speakers, taught on British English. Measured on the pilot recordings,
a vowel was the phone that sank the word in 16 of 27 attempts, and the vowels
concerned -- AO, ER, AE -- are exactly where the two accents diverge:

    word        CMUdict (GA)            BEEP (British)
    mauve       M AO1 V                 m ow v
    gaucherie   G AW1 K Y ER0 IY0       g ow sh ax r iy
    draught     D R AE1 F T             d r aa f t
    tune        T UW1 N                 t y uw n

On mauve and gaucherie the pilot participants were marked wrong for being
right.

Writes ``data/beep.tsv.gz``: one line per pronunciation, word TAB phones.
Cambridge's own host fails TLS verification behind some corporate proxies, so
the openslr mirror is used.
"""

from __future__ import annotations

import gzip
import io
import sys
import tarfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import requests  # noqa: E402

from app.services.pronunciation.features import ARPABET_PHONES  # noqa: E402

SOURCE = "https://www.openslr.org/resources/14/beep.tar.gz"
OUT = Path("data/beep.tsv.gz")

# BEEP uses ARPAbet plus two symbols CMUdict lacks.
#
#   ax  schwa /@/            -> AH, which is where CMUdict already puts schwa
#   oh  LOT vowel /D/        -> no ARPAbet equivalent. Emitted as BOTH AA and
#                               AO as alternative variants, because the split
#                               is real in British English but the American
#                               phone set cannot express it and the acoustic
#                               model cannot hear it. Accepting either is the
#                               honest treatment; claiming to score the
#                               contrast would not be.
#   ia  NEAR /I@/   10,272 entries
#   ea  SQUARE /e@/   3,608
#   ua  CURE /U@/     2,785
#       The British centring diphthongs, which General American renders as
#       vowel + R. Emitted BOTH ways -- vowel+schwa (the non-rhotic Kenyan
#       form) and vowel+R (what an American-trained acoustic model expects) --
#       so whichever the model can actually hear will match. Dropping them
#       instead cost 16,665 entries including "-shire" and every "-arian".
DIRECT = {"ax": ["AH"]}
SPLIT: dict[str, tuple[list[str], ...]] = {
    "oh": (["AA"], ["AO"]),
    "ia": (["IH", "AH"], ["IH", "R"]),
    "ea": (["EH", "AH"], ["EH", "R"]),
    "ua": (["UH", "AH"], ["UH", "R"]),
}

# Cap the combinatorial blow-up: a word with three split symbols would
# otherwise produce eight variants, each costing a forced-alignment pass.
MAX_VARIANTS = 8

SKIP_SYMBOLS = {"sil"}


def convert(phones: list[str]) -> list[list[str]]:
    """BEEP phone string -> one or more ARPAbet variants."""
    variants: list[list[str]] = [[]]
    for raw in phones:
        p = raw.lower().strip()
        if not p or p in SKIP_SYMBOLS:
            continue
        if p in SPLIT:
            variants = [v + list(alt) for v in variants for alt in SPLIT[p]]
            if len(variants) > MAX_VARIANTS:
                variants = variants[:MAX_VARIANTS]
            continue
        mapped = DIRECT.get(p, [p.upper()])
        if any(m not in ARPABET_PHONES for m in mapped):
            return []          # unknown symbol: drop the entry rather than guess
        variants = [v + mapped for v in variants]
    return [v for v in variants if v]


def main() -> int:
    print(f"downloading {SOURCE} ...")
    response = requests.get(SOURCE, timeout=300)
    response.raise_for_status()
    print(f"  {len(response.content) / 1e6:.1f} MB")

    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as tf:
        member = max((m for m in tf.getmembers() if m.isfile()),
                     key=lambda m: m.size)
        print(f"  using {member.name} ({member.size / 1e6:.1f} MB)")
        raw = tf.extractfile(member).read().decode("latin-1")

    entries: list[tuple[str, list[str]]] = []
    dropped = Counter()
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        # BEEP marks homograph variants as WORD%1, WORD%2.
        word = parts[0].lower().split("%")[0]
        if word.startswith("#") or word.startswith("<"):
            continue           # header and <pause> lines
        if not word.replace("'", "").replace("-", "").replace(".", "").isalpha():
            dropped["non-alphabetic"] += 1
            continue
        converted = convert(parts[1:])
        if not converted:
            dropped["unmappable phones"] += 1
            continue
        for variant in converted:
            entries.append((word, variant))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as out:
        for word, phones in entries:
            out.write(f"{word}\t{' '.join(phones)}\n")

    words = {w for w, _ in entries}
    print(f"\nwrote {OUT} -- {len(words)} words, {len(entries)} pronunciations, "
          f"{OUT.stat().st_size / 1e6:.1f} MB")
    if dropped:
        print("  dropped:", dict(dropped))

    # Spot-check the words the pilot got wrong.
    index: dict[str, list[str]] = {}
    for word, phones in entries:
        index.setdefault(word, []).append(" ".join(phones))
    print()
    for w in ("mauve", "gaucherie", "draught", "tune", "turquoise", "niche",
              "banana", "sheep", "orange"):
        print(f"  {w:<11} {index.get(w, ['-- absent --'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
