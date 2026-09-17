"""Exercise types, and the one decision that forks the whole session.

An item is either *spoken* -- it goes through the acoustic pipeline and is
scored on how it was pronounced -- or it is *tapped*, and is right or wrong by
exact comparison with a designed answer key.

That fork is the reason this module exists as a single source rather than a
condition scattered through the endpoints. A tap-answer item must never reach
the recogniser, and not merely because it would be pointless: six of twenty
pilot participants complained unprompted that the robot could not hear Kenyan
English. For the perception half of a session, an exercise that cannot invoke
the recogniser cannot false-reject anyone, and that is a design guarantee worth
being able to point at in one place.

See docs/PHASE3_ITEM_MODEL.md for why items are typed at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# --- exercise types ---------------------------------------------------------

REPEAT_WORD = "repeat_word"
READ_SENTENCE = "read_sentence"
PICTURE_DESCRIBE = "picture_describe"
MINIMAL_PAIR_ID = "minimal_pair_id"
ODD_ONE_OUT = "odd_one_out"
SAME_SOUND_MATCH = "same_sound_match"
SYLLABLE_COUNT = "syllable_count"
SCHWA_SPOT = "schwa_spot"
STRESS_PLACE = "stress_place"


@dataclass(frozen=True)
class ExerciseType:
    key: str
    label: str
    #: Does the participant's answer arrive as audio?
    spoken: bool
    #: Does the answer go through the pronunciation pipeline and get a verdict?
    #: picture_describe is spoken but not scored: it is recorded for human
    #: rating, because there is no reference transcript to align against.
    scored_by_pipeline: bool
    #: What the item contributes to. Used to group results in the analysis, and
    #: to build a session that mixes the two rather than running twelve of one.
    construct: Literal["production", "perception", "prosody"]
    description: str


TYPES: tuple[ExerciseType, ...] = (
    ExerciseType(
        REPEAT_WORD, "Repeat the word", True, True, "production",
        "Pepper says a word; the participant repeats it.",
    ),
    ExerciseType(
        READ_SENTENCE, "Read the sentence", True, True, "production",
        "The target word inside a carrier sentence, so the feature is produced "
        "in connected speech rather than in citation form.",
    ),
    ExerciseType(
        PICTURE_DESCRIBE, "Describe the picture", True, False, "production",
        "Timed spontaneous description. Recorded for human rating; there is no "
        "reference transcript to align against, so the pipeline cannot score it.",
    ),
    ExerciseType(
        MINIMAL_PAIR_ID, "Tap what you hear", False, False, "perception",
        "Two words differing in one contrast. Identification.",
    ),
    ExerciseType(
        ODD_ONE_OUT, "Odd one out", False, False, "perception",
        "Which word has a different vowel from the others. Categorisation.",
    ),
    ExerciseType(
        SAME_SOUND_MATCH, "Same sound", False, False, "perception",
        "Pair a cue word with the option sharing its vowel.",
    ),
    ExerciseType(
        SYLLABLE_COUNT, "Odd syllable count", False, False, "prosody",
        "Which word has a different number of syllables.",
    ),
    ExerciseType(
        SCHWA_SPOT, "Find the weak syllable", False, False, "prosody",
        "Which syllables of the word are reduced. Reduction awareness.",
    ),
    ExerciseType(
        STRESS_PLACE, "Where is the stress", False, False, "prosody",
        "Which syllable carries primary stress.",
    ),
)

BY_KEY: dict[str, ExerciseType] = {t.key: t for t in TYPES}
EXERCISE_TYPES: tuple[str, ...] = tuple(t.key for t in TYPES)


def resolve(exercise_type: str | None) -> ExerciseType:
    """The type of an item, defaulting to the behaviour that predates typing.

    Every item stored before Phase 3 has no exercise_type and was a
    repeat-the-word item. Defaulting keeps those items and every attempt
    recorded against them meaning exactly what they meant.
    """
    if not exercise_type:
        return BY_KEY[REPEAT_WORD]
    try:
        return BY_KEY[exercise_type]
    except KeyError as exc:
        raise UnknownExerciseType(
            f"{exercise_type!r} is not an exercise type. Known types: "
            f"{', '.join(EXERCISE_TYPES)}"
        ) from exc


class UnknownExerciseType(ValueError):
    """An item's type is not one this build knows how to run."""


def needs_asr(exercise_type: str | None) -> bool:
    """Does answering this require the microphone?

    The fork. Everything downstream -- whether audio is uploaded, whether the
    acoustic model is touched, whether a verdict can be 'gated' -- follows from
    this one answer.
    """
    return resolve(exercise_type).spoken


def is_scored_by_pipeline(exercise_type: str | None) -> bool:
    return resolve(exercise_type).scored_by_pipeline


def construct_of(exercise_type: str | None) -> str:
    return resolve(exercise_type).construct


# --- target features --------------------------------------------------------
#
# What an item is actually testing. Without this the analysis has one aggregate
# number and no way to say which contrast improved, and no way to check that
# lists A and B cover the same ground.
#
# These are the transfer features documented for Kenyan English, chosen because
# they are teachable inside a session. "Hardest English words" -- epitome,
# hyperbole -- were dropped deliberately: those test whether someone has seen
# the word written, which is lexical knowledge and not what this tutor teaches.

@dataclass(frozen=True)
class TargetFeature:
    key: str
    label: str
    contrast: str
    example: str


FEATURES: tuple[TargetFeature, ...] = (
    TargetFeature("trap_palm_strut", "TRAP / PALM / STRUT",
                  "/ae/ vs /aa/ vs /ah/, commonly merged", "cat / cart / cut"),
    TargetFeature("kit_fleece", "KIT / FLEECE",
                  "/ih/ vs /iy/, length and quality", "ship / sheep"),
    TargetFeature("foot_goose", "FOOT / GOOSE",
                  "/uh/ vs /uw/", "pull / pool"),
    TargetFeature("schwa_reduction", "Schwa and reduction",
                  "unstressed vowels produced in full", "banana, about"),
    TargetFeature("dental_fricative", "Dental fricatives",
                  "/th/ and /dh/ realised as /t/ and /d/", "think / tink"),
    TargetFeature("polysyllabic_stress", "Polysyllabic stress",
                  "primary stress placement", "photograph / photography"),
    TargetFeature("rhotic_lateral", "Tapped /r/",
                  "tapped /r/ perceived as /l/", "rot / lot"),
)

FEATURES_BY_KEY: dict[str, TargetFeature] = {f.key: f for f in FEATURES}
TARGET_FEATURES: tuple[str, ...] = tuple(f.key for f in FEATURES)


#: Which letters of a word carry the feature being taught, so the tablet can
#: tint them. Ordered: the first spelling found in the word wins.
#:
#: Rough by design. English spelling does not map onto sounds cleanly and this
#: is not a grapheme-to-phoneme model; it is a visual cue pointing at roughly
#: the right part of the word. Where it would be wrong more often than right --
#: schwa, which can be almost any vowel letter, and stress, which is a property
#: of a syllable rather than a letter -- there is no entry and nothing is
#: tinted.
HIGHLIGHT_GRAPHEMES: dict[str, tuple[str, ...]] = {
    "kit_fleece": ("ee", "ea", "i"),
    "foot_goose": ("oo", "ou", "u"),
    "trap_palm_strut": ("ar", "a", "u"),
    "dental_fricative": ("th",),
    "rhotic_lateral": ("r", "l"),
}


def highlight_span(word: str, feature: str | None) -> tuple[int, int] | None:
    """Where in [word] to draw attention, as (start, end), or None.

    Only ever a teaching aid, so it is offered in training blocks and withheld
    from assessments: pointing at the vowel that matters is instruction, and an
    assessment is supposed to measure what the participant brings to it rather
    than what the screen just told them.
    """
    if not feature or not word:
        return None
    lowered = word.lower()
    for grapheme in HIGHLIGHT_GRAPHEMES.get(feature, ()):
        index = lowered.find(grapheme)
        if index != -1:
            return index, index + len(grapheme)
    return None


# --- study roles for a category ---------------------------------------------
#
# Which category is training list A, which is list B, and which holds the
# assessment items. This used to live in three environment variables on the
# server; see docs/PHASE3_ITEM_MODEL.md for why that was the wrong home.

LIST_A = "list_a"
LIST_B = "list_b"
TEST_SET = "test"
STUDY_ROLES: tuple[str, ...] = (LIST_A, LIST_B, TEST_SET)

#: The label the design uses ("A") to the role stored on the category.
ROLE_FOR_LIST: dict[str, str] = {"A": LIST_A, "B": LIST_B}
