"""Where the expected pronunciation of a word comes from.

A layered lookup, most authoritative first:

  1. **overrides** -- ``data/pronunciation_overrides.json``, hand-set by the
     researcher. For items where the dictionary is wrong, contested, or where
     the study is deliberately teaching one particular form.
  2. **BEEP** -- 236,818 British English words. The workhorse.
  3. **CMUdict + British rules** -- non-rhotic /r/ deletion and yod retention
     applied to the American entry, unioned with the American form.
  4. **g2p** -- grapheme-to-phoneme prediction for genuinely novel words
     (``quinoa`` is absent from BEEP). Flagged ``needs_review``, because a
     predicted reference has no authority behind it.

Hand-setting the top layer does not limit coverage: coverage comes from layers
2-4, and any item a therapist adds through the app gets a British reference
automatically. The override table exists to *correct* the automatic answer.

Why not CMUdict alone: it is General American, and Kenyan English is taught on
British English. On the pilot recordings a vowel was the phone that sank the
word in 16 of 27 attempts, and on ``mauve`` (``M AO1 V`` vs BEEP's ``M OW V``)
and ``gaucherie`` (``G AW1 K Y ER0 IY0`` vs ``G OW SH AH R IY``) the
participants were marked wrong for being right.

Every reference carries its :class:`ReferenceSource`, and that is persisted per
attempt -- so analysis can check whether items scored against a predicted
reference behaved differently from those scored against BEEP.
"""

from __future__ import annotations

import gzip
import json
import logging
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

from .features import is_vowel, strip_stress
from .lexicon import (ResourceUnavailable, in_cmudict, normalize_text,
                      pronunciations)

log = logging.getLogger(__name__)

BEEP_PATH = Path("data/beep.tsv.gz")
OVERRIDES_PATH = Path("data/pronunciation_overrides.json")

# Bound the work: each variant costs a forced-alignment and GOP pass.
MAX_VARIANTS = 8


class ReferenceSource(str, Enum):
    OVERRIDE = "override"
    BEEP = "beep"
    CMU_ADAPTED = "cmudict+gb-rules"
    CMU = "cmudict"
    G2P = "g2p"


@dataclass(frozen=True)
class Reference:
    """The accepted pronunciations of one word, and where they came from."""

    word: str
    variants: tuple[tuple[str, ...], ...]
    source: ReferenceSource
    # CMUdict's stress-marked sequence, when available. BEEP carries no stress
    # marks, so prosody scoring keeps using CMUdict as its stress reference --
    # sound for most words, but wrong exactly where the accents differ in
    # stress placement (``debris``), which is a documented limitation.
    stress: tuple[str, ...] | None = None
    needs_review: bool = False

    @property
    def primary(self) -> tuple[str, ...]:
        return self.variants[0]


# --- British adaptations of an American entry -------------------------------

def non_rhotic(phones: list[str]) -> list[str] | None:
    """Drop post-vocalic /r/; unstressed ``ER0`` becomes schwa.

    A reliable phonological rule, unlike the BATH/TRAP split, which is
    lexically determined and must not be rule-generated.

    Stressed ``ER`` is left alone: British /3:/ (NURSE) has no ARPAbet symbol
    of its own, so ``ER`` remains its best available approximation.
    """
    out: list[str] = []
    changed = False
    for i, phone in enumerate(phones):
        bare = strip_stress(phone)
        if bare == "R":
            previous_is_vowel = bool(out) and is_vowel(out[-1])
            next_is_vowel = i + 1 < len(phones) and is_vowel(phones[i + 1])
            if previous_is_vowel and not next_is_vowel:
                changed = True
                continue                      # post-vocalic R: not pronounced
        if bare == "ER" and phone.endswith("0"):
            out.append("AH0")                 # r-coloured schwa -> plain schwa
            changed = True
            continue
        out.append(phone)
    return out if changed else None


# Alveolars that keep a yod before /u:/ in British English: tune, duty, news,
# pseudonym, ingenuity. Over-generation only makes scoring more permissive
# (it adds an accepted variant), never stricter.
_YOD_AFTER = {"T", "D", "N", "S", "L", "TH"}


def yod_retained(phones: list[str]) -> list[str] | None:
    out: list[str] = []
    changed = False
    for i, phone in enumerate(phones):
        out.append(phone)
        if strip_stress(phone) not in _YOD_AFTER:
            continue
        nxt = phones[i + 1] if i + 1 < len(phones) else None
        if nxt and strip_stress(nxt) == "UW":
            out.append("Y")
            changed = True
    return out if changed else None


def optional_final_stop(phones: list[str]) -> list[str] | None:
    """Accept a word-final voiceless stop being unreleased.

    Word-final /p t k/ are frequently unreleased, realised as a closure with
    no burst, and a CTC phone recogniser often emits no peak for them. That
    reads as a deletion the speaker did not make -- the reported case was
    "sheep" scoring badly on its /p/.

    Emitted as an *additional accepted* variant, so the word still scores well
    when the stop is released. The cost is that a genuinely dropped final stop
    is no longer detected; that is the right trade for a tutor, and it is
    stated rather than hidden.
    """
    if len(phones) < 2:
        return None
    if strip_stress(phones[-1]) in ("P", "T", "K"):
        return phones[:-1]
    return None


def british_variants(phones: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Every British-adapted form derivable from an American entry."""
    out: list[tuple[str, ...]] = []
    base = list(phones)
    for rule in (non_rhotic, yod_retained):
        derived = rule(base)
        if derived:
            out.append(tuple(derived))
    # Compose the two rules as well: "ingenuity" needs both.
    both = non_rhotic(base)
    if both:
        composed = yod_retained(both)
        if composed:
            out.append(tuple(composed))
    return out


def _collapse_repeats(phones: list[str]) -> list[str]:
    """Drop an immediately repeated identical phone."""
    out: list[str] = []
    for phone in phones:
        if not out or strip_stress(out[-1]) != strip_stress(phone):
            out.append(phone)
    return out


# --- the layers -------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_beep() -> dict[str, tuple[tuple[str, ...], ...]]:
    if not BEEP_PATH.exists():
        log.warning("%s not found; run scripts/fetch_beep.py to enable the "
                    "British lexicon. Falling back to CMUdict + rules.",
                    BEEP_PATH)
        return {}
    index: dict[str, list[tuple[str, ...]]] = {}
    with gzip.open(BEEP_PATH, "rt", encoding="utf-8") as handle:
        for line in handle:
            word, _, phones = line.partition("\t")
            if not phones:
                continue
            # Collapse adjacent duplicates: expanding a centring diphthong
            # into vowel+R next to BEEP's own linking /r/ produced "B IH R R"
            # for "beer".
            seq = tuple(_collapse_repeats(phones.split()))
            index.setdefault(word, []).append(seq)
    log.info("BEEP loaded: %d words", len(index))
    return {w: tuple(v) for w, v in index.items()}


@lru_cache(maxsize=1)
def _load_overrides() -> dict[str, tuple[tuple[str, ...], ...]]:
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        raw = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.exception("could not read %s; ignoring overrides", OVERRIDES_PATH)
        return {}
    out: dict[str, tuple[tuple[str, ...], ...]] = {}
    for word, value in raw.items():
        if word.startswith("_"):
            continue                          # comment keys
        forms = [value] if isinstance(value, str) else value
        parsed = tuple(tuple(f.upper().split()) for f in forms if f.strip())
        if parsed:
            out[word.lower().strip()] = parsed
    log.info("pronunciation overrides loaded: %d words", len(out))
    return out


def reload_sources() -> None:
    """Drop cached lexicons, so an edited override file takes effect."""
    _load_beep.cache_clear()
    _load_overrides.cache_clear()
    reference_for.cache_clear()


@lru_cache(maxsize=8192)
def reference_for(word: str, accent: str = "en-GB") -> Reference | None:
    """Accepted pronunciations for ``word``, from the most authoritative layer.

    ``accent="en-US"`` skips BEEP and the British rules, for comparison runs.
    Returns ``None`` when no layer can supply a reference at all.
    """
    target = normalize_text(word)
    if not target:
        return None

    # CMUdict is consulted regardless, purely for its stress marks.
    real_entry = in_cmudict(target)
    try:
        cmu = pronunciations(target)
    except ResourceUnavailable:
        cmu = ()
    # Only a genuine dictionary entry carries usable stress marks; a g2p
    # prediction does not, and treating one as a stress reference would have
    # the prosody check comparing against a guess.
    stress = cmu[0] if (cmu and real_entry) else None

    def finish(variants, source, needs_review=False):
        unique: list[tuple[str, ...]] = []
        for v in variants:
            if v and v not in unique:
                unique.append(v)
        if not unique:
            return None
        return Reference(target, tuple(unique[:MAX_VARIANTS]), source,
                         stress, needs_review)

    override = _load_overrides().get(target)
    if override:
        return finish(override, ReferenceSource.OVERRIDE)

    if accent == "en-GB":
        beep = _load_beep().get(target)
        if beep:
            variants = list(beep)
            for form in list(variants):
                extra = optional_final_stop(list(form))
                if extra:
                    variants.append(tuple(extra))
            return finish(variants, ReferenceSource.BEEP)

    if cmu and not real_entry:
        # g2p prediction: usable, but nothing stands behind it.
        return finish(cmu, ReferenceSource.G2P, needs_review=True)

    if cmu:
        variants = list(cmu)
        if accent == "en-GB":
            for form in list(cmu):
                variants.extend(british_variants(form))
            for form in list(variants):
                extra = optional_final_stop(list(form))
                if extra:
                    variants.append(tuple(extra))
            source = (ReferenceSource.CMU_ADAPTED
                      if len(variants) > len(cmu) else ReferenceSource.CMU)
        else:
            source = ReferenceSource.CMU
        return finish(variants, source)

    # Nothing in either dictionary: g2p already ran inside pronunciations()
    # and returned nothing, so there is no reference to be had.
    return None
