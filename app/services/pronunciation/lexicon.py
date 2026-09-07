"""Target-side phonology: text normalisation and expected phone sequences.

Differences from the original ``pronunciation_pipeline.get_phonemes``:

* **All dictionary variants are returned**, not ``cmu_dict[word][0]``. CMUdict
  lists several valid pronunciations for many words (``either``, ``route``,
  ``mischievous``); scoring against only the first marks a correct alternate
  pronunciation as an error. Callers score against every variant and keep the
  best-matching one.
* **Nothing is downloaded at import time.** The original module called
  ``nltk.download`` on import, so every server start touched the network and a
  failure there took down the whole app. Resources load lazily on first use and
  are expected to be installed by ``scripts/setup_resources.py``.
* **g2p is only a fallback**, loaded lazily, because constructing ``G2p()``
  costs seconds and pulls in a neural model that most requests never need.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterator

from num2words import num2words

from .features import is_vowel, strip_stress

_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_DIGITS = re.compile(r"^\d+$")

_cmudict: dict[str, list[list[str]]] | None = None
_g2p = None


class ResourceUnavailable(RuntimeError):
    """A required linguistic resource is not installed on this machine."""


def _load_cmudict() -> dict[str, list[list[str]]]:
    global _cmudict
    if _cmudict is None:
        try:
            from nltk.corpus import cmudict
            _cmudict = cmudict.dict()
        except LookupError as exc:  # corpus not downloaded
            raise ResourceUnavailable(
                "CMUdict is not installed. Run scripts/setup_resources.py once "
                "on this machine; the pipeline never downloads at request time."
            ) from exc
    return _cmudict


def _load_g2p():
    global _g2p
    if _g2p is None:
        from g2p_en import G2p
        _g2p = G2p()
    return _g2p


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, spell out integers.

    ``"3"`` -> ``"three"``. Unlike the original, a ``num2words`` failure is
    caught by type rather than by a bare ``except``, so genuine bugs surface
    instead of being silently swallowed as "keep the digits".
    """
    text = _PUNCT.sub("", text.lower())
    out: list[str] = []
    for word in text.split():
        if _DIGITS.match(word):
            try:
                out.append(num2words(int(word)))
            except (ValueError, OverflowError, NotImplementedError):
                out.append(word)
        else:
            out.append(word)
    return " ".join(out).strip()


@lru_cache(maxsize=8192)
def pronunciations(word: str) -> tuple[tuple[str, ...], ...]:
    """Every accepted phone sequence for ``word``, stress marks retained.

    Falls back to grapheme-to-phoneme prediction for out-of-vocabulary words,
    which returns a single variant. The result is cached because study items
    repeat across every participant and every attempt.
    """
    key = word.lower().strip()
    if not key:
        return ()
    variants = _load_cmudict().get(key)
    if variants:
        return tuple(tuple(p.upper() for p in v) for v in variants)
    predicted = [p for p in _load_g2p()(key) if p.strip()]
    return (tuple(p.upper() for p in predicted),) if predicted else ()


def canonical_pronunciation(word: str) -> tuple[str, ...]:
    """The first dictionary variant, for display and for stress reference."""
    variants = pronunciations(word)
    if not variants:
        raise ResourceUnavailable(f"no pronunciation available for {word!r}")
    return variants[0]


def segmental(phones: tuple[str, ...]) -> tuple[str, ...]:
    """Drop stress digits, leaving the segmental sequence only."""
    return tuple(strip_stress(p) for p in phones)


def stress_pattern(phones: tuple[str, ...]) -> tuple[int, ...]:
    """Lexical stress digit of each vowel, in order (``0``/``1``/``2``)."""
    return tuple(
        int(p[-1]) for p in phones if is_vowel(p) and p[-1] in "012"
    )


def syllabify(phones: tuple[str, ...]) -> list[list[str]]:
    """Split a phone sequence into syllables by maximal onset.

    Approximate, and only ever used to render spoken stress feedback
    ("stress the second syllable: hy-PER-bo-le"), never to score. An
    approximate syllabification that produces intelligible feedback is
    preferable to a full sonority-sequencing implementation the paper would
    then have to defend.
    """
    vowel_positions = [i for i, p in enumerate(phones) if is_vowel(p)]
    if not vowel_positions:
        return [list(phones)] if phones else []

    syllables: list[list[str]] = []
    start = 0
    for n, v in enumerate(vowel_positions):
        if n == len(vowel_positions) - 1:
            syllables.append(list(phones[start:]))
            break
        next_v = vowel_positions[n + 1]
        # Consonants between this vowel and the next: give all but the first
        # to the following onset, which approximates maximal onset.
        cluster = next_v - v - 1
        split = v + 1 + (1 if cluster > 1 else 0)
        syllables.append(list(phones[start:split]))
        start = split
    return syllables


def iter_words(text: str) -> Iterator[str]:
    yield from normalize_text(text).split()
