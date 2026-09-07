"""Tests for the counterbalanced study design.

Pure functions only -- no database, no model. The properties checked here are
what make a K-vs-D comparison interpretable at all, so they are worth pinning
down independently of any storage layer.

Runs under pytest, or standalone via ``python tests/test_study_design.py``.
"""

from __future__ import annotations

import sys
import uuid
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import study_design as sd  # noqa: E402


# --- the design itself -------------------------------------------------------

def test_every_participant_sees_each_condition_and_each_list_once():
    for group in range(sd.N_GROUPS):
        first, second = sd.blocks_for(group)
        assert {first.condition, second.condition} == {"K", "D"}
        assert {first.word_list, second.word_list} == {"A", "B"}
        assert (first.index, second.index) == (1, 2)


def test_condition_and_list_are_balanced_in_the_first_block():
    """Otherwise order/fatigue or list difficulty is confounded with condition."""
    firsts = [sd.blocks_for(g)[0] for g in range(sd.N_GROUPS)]
    assert Counter(b.condition for b in firsts) == {"K": 2, "D": 2}
    assert Counter(b.word_list for b in firsts) == {"A": 2, "B": 2}


def test_all_four_condition_by_list_pairings_occur():
    pairings = {(b.condition, b.word_list)
                for g in range(sd.N_GROUPS) for b in sd.blocks_for(g)}
    assert pairings == {("K", "A"), ("K", "B"), ("D", "A"), ("D", "B")}


def test_group_index_is_validated():
    for bad in (-1, sd.N_GROUPS, 99):
        try:
            sd.blocks_for(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for group_index={bad}")


def test_block_index_is_validated():
    try:
        sd.block_for(0, 3)
    except ValueError:
        return
    raise AssertionError("expected ValueError for block_index=3")


# --- assignment --------------------------------------------------------------

def test_assignment_stays_balanced_across_a_full_cohort():
    """The reason assignment is not random: with N=44 and four cells, random
    assignment routinely lands cells 6 apart and the counterbalance stops
    doing its job."""
    counts: dict[int, int] = {}
    for _ in range(44):
        group = sd.choose_group(counts, uuid.uuid4())
        counts[group] = counts.get(group, 0) + 1

    assert sum(counts.values()) == 44
    assert max(counts.values()) - min(counts.values()) <= 1


def test_assignment_is_deterministic_for_the_same_participant():
    """Calling the assignment endpoint twice must not move someone between
    groups mid-study."""
    participant = uuid.uuid4()
    counts = {0: 3, 1: 3, 2: 3, 3: 3}
    first = sd.choose_group(counts, participant)
    for _ in range(20):
        assert sd.choose_group(counts, participant) == first


def test_assignment_fills_the_least_used_cell():
    counts = {0: 5, 1: 5, 2: 1, 3: 5}
    assert sd.choose_group(counts, uuid.uuid4()) == 2


def test_ties_are_not_a_fixed_rotation():
    """A pure 0,1,2,3 rotation is balanced but trivially predictable; the
    tie-break should spread across candidates."""
    counts = {0: 0, 1: 0, 2: 0, 3: 0}
    chosen = {sd.choose_group(counts, uuid.uuid4()) for _ in range(50)}
    assert len(chosen) > 1


def test_an_exclusion_frees_its_slot():
    """Balance counts only active participants, so a withdrawal does not leave
    the design permanently lopsided."""
    counts = {0: 3, 1: 3, 2: 3, 3: 3}
    after_exclusion = {**counts, 1: 2}
    assert sd.choose_group(after_exclusion, uuid.uuid4()) == 1


# --- balance reporting -------------------------------------------------------

def test_balance_report_flags_an_unbalanced_design():
    balanced = sd.balance_report({0: 10, 1: 10, 2: 10, 3: 10})
    assert balanced["balanced"] is True
    assert balanced["max_cell_difference"] == 0
    assert balanced["condition_in_block_1"] == {"K": 20, "D": 20}
    assert balanced["list_in_block_1"] == {"A": 20, "B": 20}

    skewed = sd.balance_report({0: 14, 1: 8, 2: 12, 3: 10})
    assert skewed["balanced"] is False
    assert skewed["max_cell_difference"] == 6
    # Block-1 condition is still even here, but the list is not -- which is
    # exactly the kind of partial imbalance a single summary number hides.
    assert skewed["condition_in_block_1"] == {"K": 22, "D": 22}
    assert skewed["list_in_block_1"] == {"A": 26, "B": 18}


def test_balance_report_handles_an_empty_study():
    report = sd.balance_report({})
    assert report["total_assigned"] == 0
    assert report["max_cell_difference"] == 0


# --- word list configuration -------------------------------------------------

def test_unconfigured_lists_are_reported_not_guessed(monkeypatch=None):
    import os
    saved = {k: os.environ.pop(k, None)
             for k in ("STUDY_LIST_A_CATEGORY_ID", "STUDY_LIST_B_CATEGORY_ID")}
    try:
        problems = sd.validate_lists()
        assert len(problems) == 2
        try:
            sd.category_id_for_list("A")
        except sd.ListsNotConfigured:
            pass
        else:
            raise AssertionError("expected ListsNotConfigured")
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_identical_lists_are_rejected():
    """Two lists bound to the same category is not a counterbalance."""
    import os
    same = str(uuid.uuid4())
    saved = {k: os.environ.get(k)
             for k in ("STUDY_LIST_A_CATEGORY_ID", "STUDY_LIST_B_CATEGORY_ID")}
    os.environ["STUDY_LIST_A_CATEGORY_ID"] = same
    os.environ["STUDY_LIST_B_CATEGORY_ID"] = same
    try:
        problems = sd.validate_lists()
        assert any("same category" in p for p in problems), problems
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_malformed_list_id_is_rejected():
    import os
    saved = os.environ.get("STUDY_LIST_A_CATEGORY_ID")
    os.environ["STUDY_LIST_A_CATEGORY_ID"] = "not-a-uuid"
    try:
        sd.category_id_for_list("A")
    except sd.ListsNotConfigured:
        pass
    else:
        raise AssertionError("expected ListsNotConfigured for a malformed UUID")
    finally:
        if saved is None:
            os.environ.pop("STUDY_LIST_A_CATEGORY_ID", None)
        else:
            os.environ["STUDY_LIST_A_CATEGORY_ID"] = saved


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            passed += 1
            print(f"  ok   {name}")
        except Exception as exc:  # noqa: BLE001 - test runner
            failed += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
