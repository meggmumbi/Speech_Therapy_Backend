"""The counterbalanced study design, in one place.

Sheet 3 specifies a within-subject design with two conditions crossed with two
difficulty-matched word lists, in a 2x2 counterbalance:

    group 0:  K-A  ->  D-B
    group 1:  K-B  ->  D-A
    group 2:  D-A  ->  K-B
    group 3:  D-B  ->  K-A

Every participant sees each condition once and each list once. Across groups,
condition-in-block-1 is balanced (K, K, D, D), list-in-block-1 is balanced
(A, B, A, B), and all four condition-by-list pairings occur. That is what stops
list difficulty or order/fatigue from masquerading as a condition effect.

Assignment is **not random**. With N around 40 and four cells, random
assignment routinely lands 14/8/12/10, and the counterbalance stops doing its
job. Participants are assigned to the least-filled group, with ties broken
deterministically from the participant's own id -- so the design stays balanced,
the same participant always resolves to the same group however often the
endpoint is called, and the sequence is not the trivially guessable
0,1,2,3,0,1,2,3 rotation.
"""

from __future__ import annotations

import hashlib
import os
import random
import uuid
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

Condition = Literal["K", "D"]
ListLabel = Literal["A", "B"]


# --- session types ----------------------------------------------------------
#
# A session is either a training block, where the robot gives feedback under
# one of the two conditions, or an assessment, where it gives none.
#
# The distinction has to live in the data, not in how the experimenter ran the
# app that day. Everything the study claims about learning comes from comparing
# assessments; everything it claims about feedback comes from training blocks.
# A session that cannot be told apart afterwards is unusable for either.

TRAINING = "training"
PRETEST = "pretest"
POSTTEST = "posttest"
DELAYED = "delayed"

#: Assessments, in the order they are run. Production is rated by humans from
#: these recordings; the robot says nothing that could teach or correct.
ASSESSMENT_PHASES: tuple[str, ...] = (PRETEST, POSTTEST, DELAYED)
SESSION_TYPES: tuple[str, ...] = (TRAINING,) + ASSESSMENT_PHASES


def is_assessment(session_type: str | None) -> bool:
    """Must this session withhold all feedback?

    Defaults to False for an unknown or missing type, because a session that
    was never stamped is an ad-hoc therapy session rather than a silent test,
    and silently muting the robot would be the more confusing failure.
    """
    return session_type in ASSESSMENT_PHASES


@dataclass(frozen=True)
class Block:
    """One block of a session: which condition, which word list."""

    index: int              # 1 or 2
    condition: Condition
    word_list: ListLabel


# group index -> the two blocks, in order
GROUPS: tuple[tuple[Block, Block], ...] = (
    (Block(1, "K", "A"), Block(2, "D", "B")),
    (Block(1, "K", "B"), Block(2, "D", "A")),
    (Block(1, "D", "A"), Block(2, "K", "B")),
    (Block(1, "D", "B"), Block(2, "K", "A")),
)

N_GROUPS = len(GROUPS)


def blocks_for(group_index: int) -> tuple[Block, Block]:
    if not 0 <= group_index < N_GROUPS:
        raise ValueError(f"group_index must be 0..{N_GROUPS - 1}, got {group_index}")
    return GROUPS[group_index]


def block_for(group_index: int, block_index: int) -> Block:
    blocks = blocks_for(group_index)
    if block_index not in (1, 2):
        raise ValueError(f"block_index must be 1 or 2, got {block_index}")
    return blocks[block_index - 1]


def describe_group(group_index: int) -> str:
    first, second = blocks_for(group_index)
    return (f"{first.condition}-{first.word_list} -> "
            f"{second.condition}-{second.word_list}")


def choose_group(counts: Mapping[int, int], participant_id: uuid.UUID | str) -> int:
    """Pick the least-filled group, breaking ties from the participant id.

    ``counts`` maps group index to the number of *active* (non-excluded)
    participants already assigned. Excluded participants free their slot, so a
    withdrawal does not permanently unbalance the design.
    """
    filled = {g: int(counts.get(g, 0)) for g in range(N_GROUPS)}
    fewest = min(filled.values())
    candidates = sorted(g for g, n in filled.items() if n == fewest)

    # Deterministic tie-break: the same participant always resolves to the
    # same group, so calling the assignment endpoint twice cannot reassign
    # them mid-study.
    digest = hashlib.sha256(str(participant_id).encode("utf-8")).digest()
    return candidates[digest[0] % len(candidates)]


def balance_report(counts: Mapping[int, int]) -> dict:
    """Per-group and per-cell counts, for checking the design before analysis."""
    filled = {g: int(counts.get(g, 0)) for g in range(N_GROUPS)}
    total = sum(filled.values())

    first_condition: dict[str, int] = {"K": 0, "D": 0}
    first_list: dict[str, int] = {"A": 0, "B": 0}
    for group, n in filled.items():
        first, _ = blocks_for(group)
        first_condition[first.condition] += n
        first_list[first.word_list] += n

    return {
        "total_assigned": total,
        "per_group": {describe_group(g): n for g, n in filled.items()},
        "condition_in_block_1": first_condition,
        "list_in_block_1": first_list,
        "balanced": len(set(filled.values())) <= 1,
        "max_cell_difference": max(filled.values()) - min(filled.values()) if filled else 0,
    }


class ListsNotConfigured(RuntimeError):
    """The A/B word lists have not been bound to activity categories."""


def _role_from_db(db, role: str) -> uuid.UUID | None:
    """The category claiming this study role, if the database says so.

    Phase 3 moved list binding out of environment variables and into
    `activity_categories.study_role`. The variables remain as a fallback so a
    deployment mid-study does not change under anyone, but the database is
    preferred: a fact about the experiment does not belong in a file that is
    not in version control, and the unset variables are what blocked the first
    study run.
    """
    if db is None:
        return None
    from .. import models  # local: models import the database, which imports config
    row = (
        db.query(models.ActivityCategory.id)
        .filter(models.ActivityCategory.study_role == role)
        .first()
    )
    return row[0] if row else None


def category_id_for_list(label: ListLabel, db=None) -> uuid.UUID:
    """Resolve a word-list label to its activity category.

    The two lists are ordinary activity categories marked with a `study_role`.
    Pass a session to use that; without one this falls back to the environment
    variable, which is how the pure design tests exercise it.
    """
    from .exercises import ROLE_FOR_LIST
    found = _role_from_db(db, ROLE_FOR_LIST[label])
    if found is not None:
        return found

    env = f"STUDY_LIST_{label}_CATEGORY_ID"
    raw = os.getenv(env)
    if not raw:
        raise ListsNotConfigured(
            f"No category is marked as study list {label}. Set its study_role "
            f"to {ROLE_FOR_LIST[label]!r}, or set {env}."
        )
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ListsNotConfigured(f"{env} is not a valid UUID: {raw!r}") from exc


def test_category_id(db=None) -> uuid.UUID:
    """The category holding the assessment items.

    Separate from lists A and B on purpose. The test set has to contain items
    from both training lists *and* untrained items sharing the same target
    features, because generalisation to untrained words is the measure that
    distinguishes learning from having memorised twelve words. A test set drawn
    from one training list could not show it.
    """
    from .exercises import TEST_SET
    found = _role_from_db(db, TEST_SET)
    if found is not None:
        return found

    raw = os.getenv("STUDY_TEST_CATEGORY_ID")
    if not raw:
        raise ListsNotConfigured(
            "No category is marked as the assessment set. Set its study_role "
            "to 'test', or set STUDY_TEST_CATEGORY_ID."
        )
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ListsNotConfigured(
            f"STUDY_TEST_CATEGORY_ID is not a valid UUID: {raw!r}") from exc


def configured_lists(db=None) -> dict[str, str | None]:
    """What the lists are currently bound to, for the health/balance report."""
    out: dict[str, str | None] = {}
    for label in ("A", "B"):
        try:
            out[label] = str(category_id_for_list(label, db))  # type: ignore[arg-type]
        except ListsNotConfigured:
            out[label] = None
    try:
        out["test"] = str(test_category_id(db))
    except ListsNotConfigured:
        out["test"] = None
    return out


# --- item order -------------------------------------------------------------

def new_order_seed() -> int:
    """A fresh seed for one session's item order.

    Bounded to 31 bits so it fits a plain integer column on any backend and
    can be quoted in a paper without qualification.
    """
    return random.randrange(1, 2 ** 31 - 1)


def order_items(item_ids: Sequence[str], seed: int | None) -> list[str]:
    """Shuffle the items for one session, reproducibly.

    Presentation order matters: without randomisation the last items always
    carry the most fatigue and the first always the most novelty, and with
    fixed lists that confound is identical for every participant, so it cannot
    average out. Randomising per session removes it.

    The seed is stored on the session rather than the order itself, so the
    exact sequence any participant saw can be regenerated later from two
    columns. ``seed = None`` returns the natural order unchanged, which is what
    an unstamped ad-hoc session should get.
    """
    ordered = list(item_ids)
    if seed is None:
        return ordered
    random.Random(seed).shuffle(ordered)
    return ordered


# --- the revisit round ---------------------------------------------------------

#: Said once, before the first revisited item. Server-authored so that K and
#: D hear the same bridge, and the round is announced as practice rather than
#: as a test: a participant told they are being tested on the words they got
#: wrong is in a different task from one asked to try them again.
REVISIT_INTRO = "Let's go back to a few words from earlier and try them once more."


def revisit_item_ids(attempts: Sequence, seed: int | None) -> list[str]:
    """Which items come back at the end of a training block, in what order.

    An item is revisited when the participant was *corrected* on it in the
    main round: at least one of its scored, non-gated attempts was not
    correct. Whether the second attempt then repaired it does not matter; the
    revisit is the measure of whether the correction held a few minutes later,
    and an item repaired on attempt two and one not repaired both carry that
    question. Items the participant skipped are not brought back: a skip is a
    refusal, not an error, and re-presenting it turns the refusal into one.

    Only spoken items qualify. A tapped item in D has had its answer revealed,
    so a revisit of it would measure recall of the key, not of the contrast.

    The order is the session's own seeded shuffle restricted to the revisited
    items, so that the sequence is reproducible from the session row exactly
    as the main round's is. Rows already stamped as revisits are ignored, which
    makes the function idempotent: the tablet can ask twice and get the same
    answer, and the second answer does not include the revisits themselves.
    """
    corrected: set[str] = set()
    skipped: set[str] = set()
    for a in attempts:
        if getattr(a, "revisit", None):
            continue
        item = str(a.item_id)
        if getattr(a, "skipped", False):
            skipped.add(item)
            continue
        if getattr(a, "gated", False):
            continue
        if getattr(a, "response_type", None) != "verbal":
            continue
        if a.is_correct is False:
            corrected.add(item)
    eligible = sorted(corrected - skipped)
    ordered = order_items(eligible, seed)
    return ordered


def validate_lists(db=None) -> list[str]:
    """Problems with the current list configuration, empty if it is sound."""
    problems: list[str] = []
    resolved: dict[str, str] = {}
    for label in ("A", "B"):
        try:
            resolved[label] = str(category_id_for_list(label, db))  # type: ignore[arg-type]
        except ListsNotConfigured as exc:
            problems.append(str(exc))
    if len(resolved) == 2 and resolved["A"] == resolved["B"]:
        problems.append(
            "lists A and B are bound to the same category; the counterbalance "
            "requires two distinct, difficulty-matched lists"
        )
    try:
        test = str(test_category_id(db))
        for label, category in resolved.items():
            if category == test:
                problems.append(
                    f"the assessment set is bound to the same category as list "
                    f"{label}; generalisation to untrained words is what "
                    f"separates learning from memorising the training list"
                )
    except ListsNotConfigured as exc:
        problems.append(str(exc))
    return problems


def session_plan(group_index: int) -> Sequence[dict]:
    """The full plan for a participant, for the experimenter's screen."""
    return [
        {
            "block": block.index,
            "condition": block.condition,
            "word_list": block.word_list,
            "description": describe_group(group_index),
        }
        for block in blocks_for(group_index)
    ]
