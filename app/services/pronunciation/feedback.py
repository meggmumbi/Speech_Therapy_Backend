"""Turning a scored attempt into something a robot can say out loud.

Three constraints shape this module, and the first two are measurements rather
than opinions.

**1. Name the sound, not the substitution.** On Speechocean762 (15,967 words,
2026-09-03) the pipeline picked a phone the raters had also flagged 68% of the
time, but identified the correct *substituted* phone only 19% of the time. So
feedback says "the th sound needs work" -- right about two thirds of the time
-- and never "you said t instead of th", which would be wrong four times in
five. The rejected paper's own script did the unreliable thing: *"you said
'drought', but the correct pronunciation is 'draught'"*.

The same measurement rules out contrast-derived articulatory cues. A cue
chosen from the expected/observed *pair* ("add your voice") inherits the 19%
reliability of the pair, so cues are keyed on the expected phone alone.
``contrast_cue`` implements the pair-derived version for the day diagnosis
accuracy justifies it, and is off by default.

**2. Never speak ARPAbet.** The original pipeline interpolated raw phone
symbols into feedback strings, so Pepper would say "it sounds like AH0". Every
phone reaching text goes through :data:`PHONE_EXEMPLARS`, and a test asserts no
ARPAbet token ever escapes.

**3. Conditions K and D must differ in exactly one thing.** Both re-model the
word, with the same warmth marker drawn in the same order from the same list,
and the same TTS rendering of the target. D adds the diagnosis and the cue.
Any K/D difference in the study should be attributable to that content and
nothing else, so the shared parts are built once, here, rather than written
twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from .features import CONSONANTS, VOWELS, differing_feature, strip_stress
from .scoring import AttemptScore, PhoneDiagnosis

Condition = Literal["K", "D"]

# phone -> (how to say the sound, primary exemplar, fallback exemplar)
# The exemplar is what makes a phone speakable: "the th sound, as in bath".
# Two exemplars because the primary one is sometimes the target word itself,
# and "the th sound, as in think... listen again: think" is circular.
PHONE_EXEMPLARS: dict[str, tuple[str, str, str]] = {
    "P": ("p", "pen", "stop"),        "B": ("b", "ball", "cab"),
    "T": ("t", "top", "cat"),         "D": ("d", "dog", "bed"),
    "K": ("k", "cat", "book"),        "G": ("g", "go", "bag"),
    "CH": ("ch", "chair", "teach"),   "JH": ("j", "jump", "bridge"),
    "F": ("f", "fish", "leaf"),       "V": ("v", "van", "love"),
    "TH": ("th", "think", "bath"),    "DH": ("th", "this", "mother"),
    "S": ("s", "sun", "bus"),         "Z": ("z", "zoo", "buzz"),
    "SH": ("sh", "shoe", "wash"),     "ZH": ("s", "measure", "vision"),
    "HH": ("h", "hat", "behind"),     "M": ("m", "moon", "drum"),
    "N": ("n", "nose", "rain"),       "NG": ("ng", "sing", "long"),
    "L": ("l", "leaf", "ball"),       "R": ("r", "red", "carry"),
    "W": ("w", "water", "wind"),      "Y": ("y", "yes", "yellow"),
    "IY": ("ee", "see", "tree"),      "IH": ("i", "sit", "big"),
    "EY": ("ay", "day", "rain"),      "EH": ("e", "bed", "red"),
    "AE": ("a", "cat", "hand"),       "AA": ("ah", "father", "car"),
    "AO": ("aw", "thought", "door"),  "OW": ("oh", "go", "boat"),
    "UH": ("u", "book", "foot"),      "UW": ("oo", "blue", "moon"),
    "AH": ("u", "cup", "bus"),        "ER": ("er", "bird", "word"),
    "AY": ("eye", "time", "five"),    "AW": ("ow", "now", "house"),
    "OY": ("oy", "boy", "coin"),
}

# One actionable articulatory instruction per phone, keyed on the *expected*
# phone only -- see constraint 1. Wording is aimed at an adult L2 learner
# hearing it once, spoken, with no visual aid.
#
# NOTE: this table has not been reviewed by a phonetician. That review is
# owed before the study runs; the wording is the part participants actually
# receive, and it is the basis of the feedback-quality ratings in H5.
ARTICULATORY_CUES: dict[str, str] = {
    "TH": "Put the tip of your tongue lightly between your teeth and blow.",
    "DH": "Tongue tip between your teeth, and let your voice buzz.",
    "F": "Rest your top teeth on your bottom lip and blow, with no voice.",
    "V": "Rest your top teeth on your bottom lip and let your voice buzz.",
    "S": "Tongue close behind your top teeth, and hiss like a snake.",
    "Z": "Same as an s, but switch your voice on so it buzzes.",
    "SH": "Pull your tongue back a little and round your lips.",
    "ZH": "Like sh, but with your voice on.",
    "R": "Curl your tongue back without letting it touch the roof of your mouth.",
    "L": "Touch the tip of your tongue to the ridge behind your top teeth.",
    "W": "Round your lips tightly, then open them.",
    "Y": "Raise the middle of your tongue towards the roof of your mouth.",
    "P": "Close your lips, build up the air, and release it sharply.",
    "B": "Like p, but with your voice on from the start.",
    "T": "Tongue tip on the ridge behind your top teeth, then release sharply.",
    "D": "Like t, but with your voice on from the start.",
    "K": "Back of your tongue against the roof of your mouth, then release.",
    "G": "Like k, but with your voice on from the start.",
    "CH": "Start with a t, then let it open into a sh.",
    "JH": "Start with a d, then let it open into a zh, with your voice on.",
    "M": "Close your lips and hum through your nose.",
    "N": "Tongue tip behind your top teeth and hum through your nose.",
    "NG": "Back of your tongue up, and hum through your nose.",
    "HH": "Just a soft breath out, no tongue or lips.",
    "IY": "Spread your lips wide, like a smile, and keep it long.",
    "IH": "Shorter and more relaxed than ee. Let your jaw drop slightly.",
    "EY": "Start with an e and glide up towards ee.",
    "EH": "Open your mouth a little more, and keep it short.",
    "AE": "Drop your jaw and spread your lips.",
    "AA": "Open your mouth wide and keep your tongue low and back.",
    "AO": "Round your lips a little and keep your tongue low and back.",
    "OW": "Start rounded and glide towards oo.",
    "UH": "Short and relaxed, with lips slightly rounded.",
    "UW": "Round your lips tightly and push the sound forward.",
    "AH": "Relax everything. It is a short, neutral sound.",
    "ER": "Curl your tongue back and hold the sound.",
    "AY": "Start with your mouth open and glide up towards ee.",
    "AW": "Start with your mouth open and glide towards oo.",
    "OY": "Start rounded and glide up towards ee.",
}

# Feature-level cues, used only by contrast_cue (disabled by default).
_FEATURE_CUES: dict[str, tuple[str, str]] = {
    # feature -> (cue when expected has the feature, cue when it lacks it)
    "voicing": ("Switch your voice on for that sound, so your throat buzzes.",
                "Take your voice off that sound. It is just breath."),
    "tenseness": ("Hold that vowel longer and tighter.",
                  "Keep that vowel short and relaxed."),
    "rounding": ("Round your lips for that vowel.",
                 "Keep your lips spread, not rounded."),
    "rhoticity": ("Curl your tongue back at the end of that vowel.",
                  "Do not curl your tongue on that vowel."),
}

# Warmth markers. Rotated by attempt index so K and D draw the SAME marker at
# the same point in a session -- otherwise a K/D difference could be a
# difference in how warm the robot sounded.
WARMTH_MARKERS: tuple[str, ...] = (
    "Not quite.", "Nice try.", "Close.", "Good effort.",
)

# Neutral extensions for Condition K, rotated by the same attempt index as the
# warmth markers.
#
# Without these, K runs 4-5 spoken words and D runs 20-25 -- a 5x gap. A D>K
# result would then be open to the reading that the robot simply spent five
# times longer engaging with the learner, which is exactly the "D was just
# longer/warmer" rebuttal the design is meant to pre-empt. These add task
# framing and time-on-task with NO diagnostic content: no phone is named, no
# articulatory instruction is given, nothing is said about what went wrong.
#
# Matching is approximate by construction -- D's length varies with the cue for
# the phone it names -- so the study should report the realised distribution of
# Feedback.word_count per condition rather than claim the two are equal.
K_FILLERS: tuple[str, ...] = (
    "Listen carefully to the whole word, then say it after me.",
    "Take your time with this one, and copy what you hear.",
    "Have another go when you are ready, following my voice.",
    "Let's do that one together. Listen right to the end.",
)

PRAISE: tuple[str, ...] = (
    "That's it.", "Well done.", "Exactly right.", "Perfect.",
)

# Said identically in both conditions when the recogniser is not confident
# enough to judge. Never a diagnosis, never a verdict.
GATED_PROMPT = "I didn't quite catch that. Could you say it once more?"

_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth")


@dataclass(frozen=True)
class Feedback:
    """What the robot says, plus what the study needs to log about it."""

    speech: str                  # spoken by Pepper's TTS
    display: str                 # shown on the tablet
    kind: Literal["praise", "correction", "stress", "repeat", "encourage"]
    condition: Condition
    named_phone: str | None      # expected phone named, if any (for logging)
    cue_used: str | None
    remodel: bool                # did this utterance re-model the target word

    @property
    def word_count(self) -> int:
        """Spoken length, so K/D utterance-length matching is auditable."""
        return len(self.speech.split())


def speakable_phone(phone: str, avoid: str | None = None) -> str:
    """``TH`` -> ``the th sound, as in bath``. Never returns ARPAbet.

    ``avoid`` is the target word: if it is the phone's primary exemplar the
    fallback is used instead, so the robot never explains a sound using the
    very word the learner is failing to say.
    """
    bare = strip_stress(phone)
    entry = PHONE_EXEMPLARS.get(bare)
    if entry is None:
        return "that sound"
    spoken, primary, fallback = entry
    exemplar = fallback if avoid and primary.lower() == avoid.lower() else primary
    return f"the {spoken} sound, as in {exemplar}"


def articulatory_cue(phone: str) -> str | None:
    """The cue for producing ``phone``, keyed on the expected phone alone."""
    return ARTICULATORY_CUES.get(strip_stress(phone))


def contrast_cue(expected: str, actual: str | None) -> str | None:
    """Cue derived from the expected/observed *pair*.

    Disabled by default: pair identification was only 19% accurate on
    Speechocean762, so a cue chosen this way is wrong four times in five.
    Kept because it is the right thing to say when diagnosis accuracy
    supports it, and because a future benchmark run should be able to switch
    it on by config rather than by rewriting this module.
    """
    if not actual:
        return None
    feature = differing_feature(expected, actual)
    if feature is None:
        return None
    cues = _FEATURE_CUES.get(feature)
    if cues is None:
        return None
    bare = strip_stress(expected)
    if feature == "voicing":
        has_it = CONSONANTS.get(bare, ("", "", False))[2]
    elif feature == "tenseness":
        has_it = VOWELS.get(bare, (0, 0, False, False, False, False))[3]
    elif feature == "rounding":
        has_it = VOWELS.get(bare, (0, 0, False, False, False, False))[2]
    else:  # rhoticity
        has_it = VOWELS.get(bare, (0, 0, False, False, False, False))[5]
    return cues[0] if has_it else cues[1]


def primary_diagnosis(result: AttemptScore) -> PhoneDiagnosis | None:
    """The one error worth mentioning: the worst-scoring nameable phone.

    One error per turn. Listing every flagged phone would be both longer than
    a learner can act on and more exposed to the precision limits -- naming
    three phones means three chances to be wrong.
    """
    nameable = [
        d for d in result.diagnoses
        if d.kind in ("substitution", "weak", "deletion")
        and strip_stress(d.expected) in PHONE_EXEMPLARS
    ]
    if not nameable:
        return None
    return min(nameable, key=lambda d: d.score)


def stress_sentence(result: AttemptScore) -> str | None:
    """"Put the stress on the second syllable." if stress was the error.

    Deliberately an ordinal rather than a hyphenated gloss ("hy-PER-bo-le"):
    going from phones back to orthographic syllables is unreliable, and a
    wrong gloss spoken aloud is worse than a correct ordinal.
    """
    stress = result.stress
    if stress is None or not stress.is_error or stress.expected_primary is None:
        return None
    index = stress.expected_primary
    if index >= len(_ORDINALS):
        return None
    return f"Put the stress on the {_ORDINALS[index]} syllable."


def _remodel(word: str) -> str:
    return f"Listen again: {word}."


def generate_feedback(
    result: AttemptScore,
    word: str,
    condition: Condition,
    attempt_index: int = 0,
    use_contrast_cue: bool = False,
    match_length: bool = True,
) -> Feedback:
    """Render one turn of robot speech for a scored attempt.

    ``attempt_index`` drives warmth-marker and filler rotation and must be the
    same counter in both conditions, so that K and D differ only in diagnostic
    content.

    ``match_length`` extends Condition K with a neutral filler so the two
    conditions are closer in spoken duration. Turning it off restores the
    unmatched script and reopens the length confound; it exists so the choice
    is explicit and logged rather than implicit in the code.
    """
    if result.verdict == "gated" or result.verdict == "unscorable":
        # Identical in both conditions: no verdict, no diagnosis, no re-model.
        return Feedback(GATED_PROMPT, GATED_PROMPT, "repeat", condition,
                        None, None, remodel=False)

    if result.is_correct:
        praise = PRAISE[attempt_index % len(PRAISE)]
        speech = f"{praise} That's {word}."
        return Feedback(speech, speech, "praise", condition, None, None,
                        remodel=False)

    marker = WARMTH_MARKERS[attempt_index % len(WARMTH_MARKERS)]
    remodel = _remodel(word)

    # Condition K: knowledge of correct response only. Re-model, plus neutral
    # filler if length matching is on -- never a diagnosis.
    if condition == "K":
        filler = K_FILLERS[attempt_index % len(K_FILLERS)] if match_length else None
        speech = " ".join(p for p in (marker, filler, remodel) if p)
        return Feedback(speech, speech, "correction", condition, None, None,
                        remodel=True)

    # Condition D: the same marker and the same re-model, plus the diagnosis.
    stress_line = stress_sentence(result)
    if stress_line:
        speech = f"{marker} {stress_line} {remodel}"
        return Feedback(speech, speech, "stress", condition, None, None,
                        remodel=True)

    diagnosis = primary_diagnosis(result)
    if diagnosis is None:
        # Scored wrong, but no phone is nameable with enough confidence. D
        # falls back to K's utterance rather than inventing a diagnosis --
        # including K's filler. Without the filler this fallback ran ~5 words
        # against K's ~16, inverting the very length imbalance the filler
        # exists to remove.
        filler = K_FILLERS[attempt_index % len(K_FILLERS)] if match_length else None
        speech = " ".join(p for p in (marker, filler, remodel) if p)
        return Feedback(speech, speech, "correction", condition, None, None,
                        remodel=True)

    cue = (contrast_cue(diagnosis.expected, diagnosis.observed)
           if use_contrast_cue else None) or articulatory_cue(diagnosis.expected)
    named = speakable_phone(diagnosis.expected, avoid=word)
    parts = [marker, f"Focus on {named}."]
    if cue:
        parts.append(cue)
    parts.append(remodel)
    speech = " ".join(parts)
    return Feedback(speech, speech, "correction", condition,
                    strip_stress(diagnosis.expected), cue, remodel=True)


def arpabet_tokens_in(text: str) -> list[str]:
    """Any ARPAbet symbol that leaked into user-facing text.

    Used by the guard test. Matches on upper-case tokens so that ordinary
    words ("this", "cat") are not flagged while "AH0" and "TH" are.
    """
    from .features import ARPABET_PHONES

    inventory = set(ARPABET_PHONES)
    found: list[str] = []
    for raw in text.replace(".", " ").replace(",", " ").split():
        token = raw.strip("'\"!?:;()")
        if not token or not token.isupper():
            continue
        if strip_stress(token) in inventory:
            found.append(token)
    return found


def all_feedback_strings() -> Sequence[str]:
    """Every static string this module can speak, for the guard test."""
    return (
        *(f"the {s} sound, as in {a}; as in {b}"
          for s, a, b in PHONE_EXEMPLARS.values()),
        *ARTICULATORY_CUES.values(),
        *(c for pair in _FEATURE_CUES.values() for c in pair),
        *WARMTH_MARKERS, *PRAISE, *K_FILLERS, GATED_PROMPT,
        *(f"Put the stress on the {o} syllable." for o in _ORDINALS),
    )
