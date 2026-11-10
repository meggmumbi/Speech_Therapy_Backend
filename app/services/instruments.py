"""The questionnaires, as data.

Phase 5 replaces a Google Form that could not be joined to the data it was
about. It asked participants to type a code like "P2" while the database keys
everything by UUID, so no rating could be attributed to a condition with
certainty -- which makes every subjective measure in the pilot unusable for the
K-versus-D comparison, however good the items were.

Two of its items were also broken on the page: "The tutor caught my" and "The
tutor was likable attention" are one line split in the wrong place, and
"likable" appears twice. Those two columns cannot be scored at all.

The bigger problem was ceiling. Pleasant, kind, friendly and likable all sat at
strongly-agree, and enjoyment was 14 of 20 at the top. A measure that everyone
maxes out cannot show a difference between conditions, so it cannot support or
refute anything. The scales here are chosen to have room to move: semantic
differentials with two named poles rather than agree/disagree with a virtuous
end, and a trust scale that can be related to the false-correction rate the
system actually produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ScaleKind = Literal["likert7", "differential", "single_choice"]


@dataclass(frozen=True)
class Item:
    key: str
    text: str
    #: Named ends. A differential shows both; a Likert shows them as anchors.
    low_label: str
    high_label: str
    kind: ScaleKind = "likert7"
    #: Scored in reverse, so a high raw answer means a low construct score.
    #: Present so that straight-lining is detectable at all: a respondent who
    #: taps 7 down the page produces an inconsistent total rather than a
    #: perfect one.
    reverse: bool = False


@dataclass(frozen=True)
class Scale:
    key: str
    title: str
    #: What this measures, in one sentence, for the paper's methods section.
    construct: str
    source: str
    items: tuple[Item, ...] = field(default_factory=tuple)


# --- perceptions of the robot ------------------------------------------------
#
# Godspeed, trimmed. The full instrument is 24 items and most of its animacy
# subscale is about whether a robot seems alive, which is not what varies
# between K and D. These are the subscales that could plausibly move when the
# only thing that changed is how a correction was worded.

GODSPEED = Scale(
    key="godspeed",
    title="How did the tutor seem?",
    construct="Perceived likeability and competence of the robot tutor.",
    source="Bartneck et al. (2009), Godspeed series III and IV, abbreviated.",
    items=(
        Item("dislike_like", "Overall", "Dislike", "Like", "differential"),
        Item("unfriendly_friendly", "Manner", "Unfriendly", "Friendly", "differential"),
        Item("unkind_kind", "Tone", "Unkind", "Kind", "differential"),
        Item("incompetent_competent", "At teaching pronunciation",
             "Incompetent", "Competent", "differential"),
        Item("ignorant_knowledgeable", "About English sounds",
             "Ignorant", "Knowledgeable", "differential"),
        Item("irresponsible_responsible", "In what it asked of me",
             "Irresponsible", "Responsible", "differential"),
    ),
)


# --- motivation --------------------------------------------------------------
#
# The Intrinsic Motivation Inventory's interest/enjoyment and perceived
# competence subscales, plus pressure/tension. Enjoyment on its own ceilings;
# perceived competence is what a tutoring manipulation should move, and
# pressure is the cost side that an enjoyment-only measure hides.

MOTIVATION = Scale(
    key="motivation",
    title="How was it for you?",
    construct="Intrinsic motivation: interest, perceived competence, and tension.",
    source="Ryan (1982), Intrinsic Motivation Inventory, abbreviated subscales.",
    items=(
        Item("enjoyed", "I enjoyed this session", "Not at all true", "Very true"),
        Item("attention_held", "My attention stayed on the task",
             "Not at all true", "Very true"),
        Item("competent", "I think I am good at saying these words",
             "Not at all true", "Very true"),
        Item("improved", "I got better during the session",
             "Not at all true", "Very true"),
        Item("tense", "I felt tense while doing this",
             "Not at all true", "Very true", reverse=True),
        Item("pressured", "I felt pressured to get things right",
             "Not at all true", "Very true", reverse=True),
        Item("would_continue", "I would come back and do this again",
             "Not at all true", "Very true"),
    ),
)


# --- trust in the feedback ---------------------------------------------------
#
# The item that makes the study's own error rate interpretable. A participant
# who was falsely corrected three times should report lower trust, and if they
# do not, the false-correction rate is not doing what the analysis assumes it
# does. This is the scale to relate to the measured false-correction rate.

FEEDBACK_TRUST = Scale(
    key="feedback_trust",
    title="What did you make of the corrections?",
    construct="Trust in, and perceived usefulness of, the tutor's feedback.",
    source="Adapted from Jian et al. (2000) trust-in-automation, for CAPT.",
    items=(
        Item("accurate", "When it said I was wrong, it was right to",
             "Never", "Always"),
        Item("missed", "It let mistakes go that I know I made",
             "Never", "Always", reverse=True),
        Item("specific", "The corrections told me what to change",
             "Not at all true", "Very true"),
        Item("actionable", "I knew what to do differently on the next try",
             "Not at all true", "Very true"),
        Item("would_rely", "I would rely on this tutor to correct me",
             "Not at all true", "Very true"),
    ),
)


# --- one free-text question --------------------------------------------------

OPEN = Scale(
    key="open",
    title="Anything else?",
    construct="Unprompted comments. Coded qualitatively.",
    source="Open response.",
    items=(
        Item("comment", "Is there anything you would change about the tutor?",
             "", "", "single_choice"),
    ),
)


ALL_SCALES: tuple[Scale, ...] = (GODSPEED, MOTIVATION, FEEDBACK_TRUST, OPEN)
SCALES_BY_KEY: dict[str, Scale] = {s.key: s for s in ALL_SCALES}


def for_session(session_type: str | None, condition: str | None) -> list[Scale]:
    """Which scales to ask after this session.

    Assessments get nothing. There is no tutor behaviour in a pre-test to form
    an impression of -- the robot says only "thank you, here is the next one" --
    so asking would collect ratings of something that did not happen, and
    asking at all would frame the test as a performance worth reflecting on.

    Training blocks get all of it. The feedback-trust scale is the reason the
    questionnaire exists: it is the one measure that can be related to the
    false-correction rate the system actually produced for that participant.
    """
    from . import study_design
    if session_type is None or study_design.is_assessment(session_type):
        return []
    return list(ALL_SCALES)


def score(scale: Scale, answers: dict[str, int]) -> dict:
    """Mean of the answered items, with reversals applied.

    Returns the item count alongside, because a mean over two of seven items is
    not the same number as a mean over seven and nothing downstream should have
    to guess which it got.
    """
    values: list[float] = []
    for item in scale.items:
        if item.kind == "single_choice":
            continue
        raw = answers.get(item.key)
        if raw is None:
            continue
        values.append(SCALE_MAX + 1 - raw if item.reverse else raw)
    if not values:
        return {"scale": scale.key, "mean": None, "answered": 0,
                "items": len([i for i in scale.items if i.kind != "single_choice"])}
    return {
        "scale": scale.key,
        "mean": round(sum(values) / len(values), 2),
        "answered": len(values),
        "items": len([i for i in scale.items if i.kind != "single_choice"]),
    }


#: Seven points, not five. A five-point scale with a virtuous end is what
#: produced the pilot's ceiling; seven leaves room above "good" for "very good"
#: without forcing a choice between them.
SCALE_MIN = 1
SCALE_MAX = 7


def serialise(scale: Scale) -> dict:
    return {
        "key": scale.key,
        "title": scale.title,
        "construct": scale.construct,
        "source": scale.source,
        "min": SCALE_MIN,
        "max": SCALE_MAX,
        "items": [
            {
                "key": item.key,
                "text": item.text,
                "low_label": item.low_label,
                "high_label": item.high_label,
                "kind": item.kind,
                # Not sent: whether an item is reverse-scored. A respondent who
                # knows which items are flipped can keep their answers
                # consistent on purpose, which is exactly what reversals exist
                # to detect.
            }
            for item in scale.items
        ],
    }
