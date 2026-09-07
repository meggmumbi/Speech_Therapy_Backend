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
import uuid
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

Condition = Literal["K", "D"]
ListLabel = Literal["A", "B"]


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


def category_id_for_list(label: ListLabel) -> uuid.UUID:
    """Resolve a word-list label to its activity category.

    The two lists are ordinary activity categories; which ones they are is
    deployment configuration, set once before the study from the pilot's
    difficulty matching. Kept out of the database schema so that re-matching
    the lists after the pilot does not need a migration.
    """
    env = f"STUDY_LIST_{label}_CATEGORY_ID"
    raw = os.getenv(env)
    if not raw:
        raise ListsNotConfigured(
            f"{env} is not set. Bind word lists {' and '.join(('A', 'B'))} to "
            "their activity categories before starting study sessions."
        )
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ListsNotConfigured(f"{env} is not a valid UUID: {raw!r}") from exc


def configured_lists() -> dict[str, str | None]:
    """What the lists are currently bound to, for the health/balance report."""
    out: dict[str, str | None] = {}
    for label in ("A", "B"):
        try:
            out[label] = str(category_id_for_list(label))  # type: ignore[arg-type]
        except ListsNotConfigured:
            out[label] = None
    return out


def validate_lists() -> list[str]:
    """Problems with the current list configuration, empty if it is sound."""
    problems: list[str] = []
    resolved: dict[str, str] = {}
    for label in ("A", "B"):
        try:
            resolved[label] = str(category_id_for_list(label))  # type: ignore[arg-type]
        except ListsNotConfigured as exc:
            problems.append(str(exc))
    if len(resolved) == 2 and resolved["A"] == resolved["B"]:
        problems.append(
            "lists A and B are bound to the same category; the counterbalance "
            "requires two distinct, difficulty-matched lists"
        )
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
