"""What each exercise type's `spec` must contain.

A discriminated union on `exercise_type`. The database column is plain JSON;
the shape is enforced here, at the authoring boundary, because that is the only
moment when a malformed item is cheap to discover. The alternative is finding
out that an odd-one-out item has no answer key while a participant is sitting
in front of the robot.

Every model below rejects an answer that is not among its own options. That
single rule catches the most likely authoring mistake by a wide margin: a
distractor edited later and the key left pointing at the old string.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

from ..services import exercises


def _clean(value: str) -> str:
    return " ".join(value.split())


class _Spec(BaseModel):
    """Common behaviour. Extra keys are refused, not ignored.

    A typo in a spec key would otherwise leave the field at its default and the
    item would run, quietly, as something other than what was authored.
    """

    model_config = {"extra": "forbid"}


# --- spoken -----------------------------------------------------------------

class RepeatWordSpec(_Spec):
    exercise_type: Literal["repeat_word"] = "repeat_word"
    word: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def _tidy(self):
        object.__setattr__(self, "word", _clean(self.word))
        return self


class ReadSentenceSpec(_Spec):
    exercise_type: Literal["read_sentence"] = "read_sentence"
    sentence: str = Field(min_length=1, max_length=300)
    #: The word carrying the target feature. Scoring still covers the whole
    #: sentence; this says which part the item exists to measure, so a
    #: feature-level result is not diluted by the carrier words around it.
    target_word: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def _target_is_in_the_sentence(self):
        sentence = _clean(self.sentence)
        target = _clean(self.target_word)
        words = {w.strip(".,!?;:'\"").lower() for w in sentence.split()}
        if target.lower() not in words:
            raise ValueError(
                f"target_word {target!r} does not appear in the sentence"
            )
        object.__setattr__(self, "sentence", sentence)
        object.__setattr__(self, "target_word", target)
        return self


class PictureDescribeSpec(_Spec):
    exercise_type: Literal["picture_describe"] = "picture_describe"
    prompt: str = Field(min_length=1, max_length=300)
    #: How long the participant is given. Bounded because the recorder's own
    #: hard cap is well under a minute and a spec asking for more would
    #: silently truncate.
    seconds: int = Field(default=30, ge=5, le=60)


# --- tapped -----------------------------------------------------------------

class _ChoiceSpec(_Spec):
    """Options plus a key that must be one of them."""

    options: list[str] = Field(min_length=2, max_length=6)
    answer: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def _answer_is_an_option(self):
        options = [_clean(o) for o in self.options]
        answer = _clean(self.answer)
        if len(set(options)) != len(options):
            raise ValueError("options contain a duplicate")
        if answer not in options:
            raise ValueError(
                f"answer {answer!r} is not one of the options {options}"
            )
        object.__setattr__(self, "options", options)
        object.__setattr__(self, "answer", answer)
        return self


class MinimalPairSpec(_ChoiceSpec):
    exercise_type: Literal["minimal_pair_id"] = "minimal_pair_id"
    options: list[str] = Field(min_length=2, max_length=2)
    #: Which of the two the participant actually hears. Stored on the item
    #: rather than synthesised per turn: a pilot participant reported the
    #: pronunciation changing between repeats, and a stimulus that varies is
    #: not a stimulus.
    stimulus_audio: str | None = Field(default=None, max_length=300)


class OddOneOutSpec(_ChoiceSpec):
    exercise_type: Literal["odd_one_out"] = "odd_one_out"
    options: list[str] = Field(min_length=3, max_length=5)


class SameSoundMatchSpec(_ChoiceSpec):
    exercise_type: Literal["same_sound_match"] = "same_sound_match"
    #: The word whose vowel the participant is matching against.
    cue: str = Field(min_length=1, max_length=80)
    options: list[str] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def _cue_is_not_an_option(self):
        if _clean(self.cue) in self.options:
            raise ValueError("cue must not also appear among the options")
        object.__setattr__(self, "cue", _clean(self.cue))
        return self


class SyllableCountSpec(_ChoiceSpec):
    exercise_type: Literal["syllable_count"] = "syllable_count"
    options: list[str] = Field(min_length=3, max_length=5)


class _SyllableSpec(_Spec):
    """A word broken into syllables, with an index-based answer.

    Indices rather than strings, because a word can repeat a syllable
    ("banana") and a string answer could not say which one was meant.
    """

    word: str = Field(min_length=1, max_length=80)
    syllables: list[str] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def _syllables_spell_the_word(self):
        joined = "".join(s.strip() for s in self.syllables).lower()
        if joined != _clean(self.word).replace(" ", "").lower():
            raise ValueError(
                f"syllables {self.syllables} do not spell {self.word!r}"
            )
        return self


class SchwaSpotSpec(_SyllableSpec):
    exercise_type: Literal["schwa_spot"] = "schwa_spot"
    #: Every reduced syllable, not just one: "banana" has two.
    answer_indices: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _indices_are_in_range(self):
        limit = len(self.syllables)
        if len(set(self.answer_indices)) != len(self.answer_indices):
            raise ValueError("answer_indices contains a duplicate")
        for index in self.answer_indices:
            if not 0 <= index < limit:
                raise ValueError(
                    f"answer index {index} is outside 0..{limit - 1}"
                )
        if len(self.answer_indices) == limit:
            raise ValueError(
                "every syllable cannot be reduced; the item would have no "
                "stressed syllable to contrast against"
            )
        return self


class StressPlaceSpec(_SyllableSpec):
    exercise_type: Literal["stress_place"] = "stress_place"
    answer_index: int = Field(ge=0)

    @model_validator(mode="after")
    def _index_is_in_range(self):
        if self.answer_index >= len(self.syllables):
            raise ValueError(
                f"answer_index {self.answer_index} is outside "
                f"0..{len(self.syllables) - 1}"
            )
        return self


ExerciseSpec = Annotated[
    Union[
        RepeatWordSpec,
        ReadSentenceSpec,
        PictureDescribeSpec,
        MinimalPairSpec,
        OddOneOutSpec,
        SameSoundMatchSpec,
        SyllableCountSpec,
        SchwaSpotSpec,
        StressPlaceSpec,
    ],
    Field(discriminator="exercise_type"),
]

SPEC_FOR_TYPE: dict[str, type[_Spec]] = {
    exercises.REPEAT_WORD: RepeatWordSpec,
    exercises.READ_SENTENCE: ReadSentenceSpec,
    exercises.PICTURE_DESCRIBE: PictureDescribeSpec,
    exercises.MINIMAL_PAIR_ID: MinimalPairSpec,
    exercises.ODD_ONE_OUT: OddOneOutSpec,
    exercises.SAME_SOUND_MATCH: SameSoundMatchSpec,
    exercises.SYLLABLE_COUNT: SyllableCountSpec,
    exercises.SCHWA_SPOT: SchwaSpotSpec,
    exercises.STRESS_PLACE: StressPlaceSpec,
}


def parse(exercise_type: str | None, spec: dict | None) -> _Spec:
    """Validate a stored or submitted spec against its type.

    An item with no spec is a pre-Phase-3 repeat-the-word item, and its word is
    the item's name; the caller supplies that.
    """
    resolved = exercises.resolve(exercise_type)
    model = SPEC_FOR_TYPE[resolved.key]
    return model(**{"exercise_type": resolved.key, **(spec or {})})


def display_name(parsed: _Spec) -> str:
    """The item's short label, derived from its own spec.

    Derived rather than stored alongside, because a `name` column and a spec
    that disagree is a silent authoring bug: the list would read correctly and
    run as something else.
    """
    if isinstance(parsed, RepeatWordSpec):
        return parsed.word
    if isinstance(parsed, ReadSentenceSpec):
        return parsed.target_word
    if isinstance(parsed, PictureDescribeSpec):
        return parsed.prompt[:80]
    if isinstance(parsed, SameSoundMatchSpec):
        return f"{parsed.cue} -> {parsed.answer}"
    if isinstance(parsed, _SyllableSpec):
        return parsed.word
    if isinstance(parsed, _ChoiceSpec):
        return parsed.answer
    return "item"


#: What Pepper says when the item appears, unless the author overrides it.
#: Kept identical across items of a type so the instruction is not itself a
#: source of difficulty variation between lists.
_PROMPTS: dict[str, str] = {
    exercises.REPEAT_WORD: "Say the word.",
    exercises.READ_SENTENCE: "Read the sentence out loud.",
    exercises.PICTURE_DESCRIBE: "Tell me what you can see.",
    exercises.MINIMAL_PAIR_ID: "Listen, then tap the word you heard.",
    exercises.ODD_ONE_OUT: "Tap the word with a different vowel sound.",
    exercises.SAME_SOUND_MATCH: "Tap the word with the same vowel sound.",
    exercises.SYLLABLE_COUNT: "Tap the word with a different number of beats.",
    exercises.SCHWA_SPOT: "Tap the weak syllables.",
    exercises.STRESS_PLACE: "Tap the strongest syllable.",
}


def default_prompt(parsed: _Spec) -> str:
    resolved = exercises.resolve(getattr(parsed, "exercise_type", None))
    if isinstance(parsed, ReadSentenceSpec):
        return f"Read this out loud. {parsed.sentence}"
    if isinstance(parsed, RepeatWordSpec):
        return f"Say the word. {parsed.word}"
    if isinstance(parsed, SameSoundMatchSpec):
        return f"Which word has the same vowel sound as {parsed.cue}?"
    return _PROMPTS[resolved.key]


def is_correct(exercise_type: str, spec: dict, answer) -> bool:
    """Grade a tapped answer against the key.

    Exact, after whitespace normalisation, and never fuzzy. These are
    tap-to-choose items: the participant selected one of the strings this item
    supplied, so anything other than an exact match means the client sent
    something the item did not offer.
    """
    parsed = parse(exercise_type, spec)
    if isinstance(parsed, SchwaSpotSpec):
        if not isinstance(answer, (list, tuple, set)):
            return False
        return set(answer) == set(parsed.answer_indices)
    if isinstance(parsed, StressPlaceSpec):
        return answer == parsed.answer_index
    if isinstance(parsed, _ChoiceSpec):
        return isinstance(answer, str) and _clean(answer) == parsed.answer
    raise ValueError(
        f"{exercise_type} is answered by speaking, not by tapping"
    )
