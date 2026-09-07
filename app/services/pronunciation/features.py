"""Articulatory feature representation of the ARPAbet phone inventory.

Substitution cost between two phones is derived from articulatory distance
rather than symbol identity, so that /f/ -> /v/ (voicing only) is scored as a
near miss while /f/ -> /k/ is scored as a gross error. This is what lets the
aligner in ``align.py`` prefer linguistically plausible alignments, and what
lets feedback name the single feature that went wrong.

The feature set is a reduced place/manner/voicing description for consonants
and a height/backness/rounding/tenseness description for vowels. It is
deliberately self-contained (no PanPhon dependency) so that the exact values
behind any published number are versioned in this file; ``FEATURE_SET_VERSION``
is folded into the pipeline config hash.
"""

from __future__ import annotations

from functools import lru_cache

FEATURE_SET_VERSION = "arpabet-af-1.0"

# --- consonants -------------------------------------------------------------
# Place is ordered front (0) -> back (7) so that numeric distance on this axis
# is meaningful.
_PLACE = {
    "bilabial": 0, "labiodental": 1, "dental": 2, "alveolar": 3,
    "postalveolar": 4, "palatal": 5, "velar": 6, "glottal": 7,
}
_PLACE_MAX = 7.0

# Manner distances are categorical, not ordinal: an affricate is close to both
# a stop and a fricative, but a stop is not close to a nasal in the same way.
_MANNER_DIST = {
    frozenset({"stop", "affricate"}): 0.45,
    frozenset({"affricate", "fricative"}): 0.40,
    frozenset({"stop", "fricative"}): 0.70,
    frozenset({"stop", "nasal"}): 0.55,
    frozenset({"nasal", "lateral"}): 0.60,
    frozenset({"lateral", "rhotic"}): 0.40,
    frozenset({"lateral", "glide"}): 0.50,
    frozenset({"rhotic", "glide"}): 0.40,
    frozenset({"fricative", "glide"}): 0.75,
}

# phone -> (place, manner, voiced)
CONSONANTS: dict[str, tuple[str, str, bool]] = {
    "P":  ("bilabial",     "stop",       False),
    "B":  ("bilabial",     "stop",       True),
    "T":  ("alveolar",     "stop",       False),
    "D":  ("alveolar",     "stop",       True),
    "K":  ("velar",        "stop",       False),
    "G":  ("velar",        "stop",       True),
    "CH": ("postalveolar", "affricate",  False),
    "JH": ("postalveolar", "affricate",  True),
    "F":  ("labiodental",  "fricative",  False),
    "V":  ("labiodental",  "fricative",  True),
    "TH": ("dental",       "fricative",  False),
    "DH": ("dental",       "fricative",  True),
    "S":  ("alveolar",     "fricative",  False),
    "Z":  ("alveolar",     "fricative",  True),
    "SH": ("postalveolar", "fricative",  False),
    "ZH": ("postalveolar", "fricative",  True),
    "HH": ("glottal",      "fricative",  False),
    "M":  ("bilabial",     "nasal",      True),
    "N":  ("alveolar",     "nasal",      True),
    "NG": ("velar",        "nasal",      True),
    "L":  ("alveolar",     "lateral",    True),
    "R":  ("postalveolar", "rhotic",     True),
    "W":  ("velar",        "glide",      True),   # labiovelar; see _DUAL_PLACE
    "Y":  ("palatal",      "glide",      True),
}

# /w/ is doubly articulated: treat its place as whichever of bilabial/velar is
# closer to the phone it is compared against, so /w/~/v/ and /w/~/g/ are both
# recognised as near misses.
_DUAL_PLACE = {"W": ("bilabial", "velar")}

# --- vowels -----------------------------------------------------------------
# height 0=high .. 4=low ; backness 0=front, 1=central, 2=back
# phone -> (height, backness, rounded, tense, diphthong, rhotic)
VOWELS: dict[str, tuple[int, int, bool, bool, bool, bool]] = {
    "IY": (0, 0, False, True,  False, False),
    "IH": (1, 0, False, False, False, False),
    "EY": (1, 0, False, True,  True,  False),
    "EH": (2, 0, False, False, False, False),
    "AE": (4, 0, False, False, False, False),
    "AA": (4, 2, False, True,  False, False),
    "AO": (3, 2, True,  True,  False, False),
    "OW": (2, 2, True,  True,  True,  False),
    "UH": (1, 2, True,  False, False, False),
    "UW": (0, 2, True,  True,  False, False),
    "AH": (2, 1, False, False, False, False),  # STRUT and schwa collapse in CMUdict
    "ER": (2, 1, False, False, False, True),
    "AY": (4, 1, False, True,  True,  False),
    "AW": (4, 1, True,  True,  True,  False),
    "OY": (3, 2, True,  True,  True,  False),
}

_HEIGHT_MAX, _BACK_MAX = 4.0, 2.0

# Relative importance of each dimension. Manner outweighs place because a
# manner error (stop for fricative) is perceptually larger than a place error
# at the same manner, and both outweigh voicing.
_W_CONS = {"place": 0.35, "manner": 0.45, "voice": 0.20}
_W_VOWEL = {"height": 0.35, "back": 0.30, "round": 0.15,
            "tense": 0.10, "diph": 0.10}


def strip_stress(phone: str) -> str:
    """``AH0`` -> ``AH``. CMUdict marks lexical stress with a trailing digit."""
    return phone.rstrip("012").upper()


def stress_of(phone: str) -> int | None:
    """Return 0/1/2 for a stress-marked vowel, else ``None``."""
    p = phone.upper()
    return int(p[-1]) if p and p[-1] in "012" else None


def is_vowel(phone: str) -> bool:
    return strip_stress(phone) in VOWELS


def _manner_distance(m1: str, m2: str) -> float:
    if m1 == m2:
        return 0.0
    return _MANNER_DIST.get(frozenset({m1, m2}), 1.0)


def _place_distance(p1: str, p2: str, ph1: str, ph2: str) -> float:
    def candidates(phone: str, place: str) -> tuple[str, ...]:
        return _DUAL_PLACE.get(phone, (place,))

    best = min(
        abs(_PLACE[a] - _PLACE[b])
        for a in candidates(ph1, p1)
        for b in candidates(ph2, p2)
    )
    return best / _PLACE_MAX


@lru_cache(maxsize=4096)
def phone_distance(a: str, b: str) -> float:
    """Articulatory distance in ``[0.0, 1.0]``; 0.0 is identity.

    Stress is ignored here. A stress error is a different pedagogical event
    from a segmental one and is scored separately, so ``AH0`` and ``AH1`` are
    distance 0.0 to this function.
    """
    a, b = strip_stress(a), strip_stress(b)
    if a == b:
        return 0.0

    a_v, b_v = a in VOWELS, b in VOWELS
    # A vowel and a consonant are maximally distant: no shared feature space.
    if a_v != b_v:
        return 1.0

    if a_v:
        h1, k1, r1, t1, d1, rh1 = VOWELS[a]
        h2, k2, r2, t2, d2, rh2 = VOWELS[b]
        d = (
            _W_VOWEL["height"] * abs(h1 - h2) / _HEIGHT_MAX
            + _W_VOWEL["back"] * abs(k1 - k2) / _BACK_MAX
            + _W_VOWEL["round"] * (r1 != r2)
            + _W_VOWEL["tense"] * (t1 != t2)
            + _W_VOWEL["diph"] * (d1 != d2)
        )
        # Rhoticity is a large perceptual cue in English; surcharge it.
        if rh1 != rh2:
            d = min(1.0, d + 0.20)
        return round(d, 6)

    if a not in CONSONANTS or b not in CONSONANTS:
        return 1.0
    p1, m1, v1 = CONSONANTS[a]
    p2, m2, v2 = CONSONANTS[b]
    d = (
        _W_CONS["place"] * _place_distance(p1, p2, a, b)
        + _W_CONS["manner"] * _manner_distance(m1, m2)
        + _W_CONS["voice"] * (v1 != v2)
    )
    return round(d, 6)


def differing_feature(expected: str, actual: str) -> str | None:
    """Name the single feature separating two phones, if exactly one does.

    Lets feedback say *why* an attempt was wrong ("that sound needs voicing")
    rather than only *that* it was wrong. Returns ``None`` when the phones
    differ on several features at once, in which case the caller should fall
    back to a whole-phone contrast cue.
    """
    e, a = strip_stress(expected), strip_stress(actual)
    if e == a:
        return None
    if e in CONSONANTS and a in CONSONANTS:
        p1, m1, v1 = CONSONANTS[e]
        p2, m2, v2 = CONSONANTS[a]
        diffs = [name for name, same in
                 (("voicing", v1 == v2), ("place", p1 == p2), ("manner", m1 == m2))
                 if not same]
        return diffs[0] if len(diffs) == 1 else None
    if e in VOWELS and a in VOWELS:
        h1, k1, r1, t1, d1, rh1 = VOWELS[e]
        h2, k2, r2, t2, d2, rh2 = VOWELS[a]
        diffs = [name for name, same in
                 (("height", h1 == h2), ("backness", k1 == k2),
                  ("rounding", r1 == r2), ("tenseness", t1 == t2),
                  ("diphthong", d1 == d2), ("rhoticity", rh1 == rh2))
                 if not same]
        # Tense/lax pairs (IY~IH, UW~UH) differ on height *and* tenseness,
        # because the slight lowering of the lax vowel is how laxness is
        # realised in English rather than an independent contrast. Name the
        # tenseness, which is the cue a learner can act on ("hold it longer,
        # tighter"); "raise your tongue one step" is not usable instruction.
        if set(diffs) == {"height", "tenseness"} and abs(h1 - h2) == 1:
            return "tenseness"
        return diffs[0] if len(diffs) == 1 else None
    return None


ARPABET_PHONES: tuple[str, ...] = tuple(CONSONANTS) + tuple(VOWELS)

# Acoustic models trained on reduced phone sets do not distinguish every
# CMUdict phone. The folds below are the standard reductions used when
# evaluating on TIMIT's 39-phone set, applied only when the model genuinely
# lacks the finer phone -- never to make scoring easier.
#
# AO -> AA is the cot-caught merger, absent from TIMIT-39 and from most
# North American English. ZH -> SH and AH -> ER cover models that fold rarer
# contrasts. A fold makes a contrast unscoreable, so each one must be declared
# in the paper's limitations: a learner who says "cot" for "caught" cannot be
# marked wrong by a model that does not represent the difference.
PHONE_FOLDS: dict[str, tuple[str, ...]] = {
    "AO": ("AA",),
    "ZH": ("SH",),
    "ER": ("AH",),
    "AH": ("ER",),
    "UH": ("UW",),
}


def resolve_to_inventory(
    phones: list[str] | tuple[str, ...],
    inventory: frozenset[str] | set[str] | dict[str, int],
) -> tuple[list[str], list[tuple[str, str]]] | None:
    """Rewrite a phone sequence into a model's label inventory.

    Returns ``(resolved_phones, applied_folds)``, or ``None`` when some phone
    has no representation at all -- in which case the caller must decline to
    score rather than silently substitute something plausible.
    """
    resolved: list[str] = []
    applied: list[tuple[str, str]] = []
    for phone in phones:
        bare = strip_stress(phone)
        if bare in inventory:
            resolved.append(bare)
            continue
        substitute = next(
            (f for f in PHONE_FOLDS.get(bare, ()) if f in inventory), None
        )
        if substitute is None:
            return None
        resolved.append(substitute)
        applied.append((bare, substitute))
    return resolved, applied
