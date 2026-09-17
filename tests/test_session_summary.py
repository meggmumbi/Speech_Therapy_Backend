"""Phase 4: what the screen after a session is allowed to say.

The old overview scored every session, including assessments, and wrote
encouragement whatever had happened. That is feedback, on the screen the
participant is looking at, straight after a test whose whole purpose is to tell
them nothing. Phase 2 closed that path inside the session; this closes it on
the way out.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import study_summary  # noqa: E402


# --- fakes ------------------------------------------------------------------
#
# Plain objects rather than a database. These tests are about the rules the
# summary applies, and a fixture that needs Postgres running would make them
# the first thing skipped.

class _Item:
    def __init__(self, name, feature=None):
        self.id = uuid.uuid4()
        self.name = name
        self.target_feature = feature


class _Activity:
    def __init__(self, item, correct=True, attempt=1, gated=False, skipped=False,
                 exercise_type="repeat_word", quality="ok", response_time=1.5,
                 replays=0, created_at=None):
        self.id = uuid.uuid4()
        self.item = item
        self.item_id = item.id
        self.is_correct = correct
        self.attempt_number = attempt
        self.gated = gated
        self.skipped = skipped
        self.skip_reason = "cant_say" if skipped else None
        self.exercise_type = exercise_type
        self.audio_quality = quality
        self.response_time_seconds = response_time
        self.prompt_replays = replays
        self.slow_replay_used = False
        self.verdict = "correct" if correct else "incorrect"
        self.verdict_score = 0.8 if correct else 0.3
        self.feedback = None
        self.selected_answer = None
        self.created_at = created_at or datetime(2026, 9, 17, 10, 0, 0)


class _Session:
    def __init__(self, session_type, activities, end_time=None, condition=None):
        self.id = uuid.uuid4()
        self.session_type = session_type
        self.condition = condition
        self.block_index = 1 if session_type == "training" else None
        self.start_time = datetime(2026, 9, 17, 10, 0, 0)
        self.end_time = end_time
        self.is_completed = True
        self.ended_early = False
        self.activities = activities
        self.category_id = uuid.uuid4()
        self.child = type("C", (), {"label": "P21"})()
        self.category = type("Cat", (), {"name": "Study List A"})()


class _Query:
    def __init__(self, result):
        self._result = result

    def options(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._result

    def count(self):
        return 21


class _Db:
    def __init__(self, session):
        self._session = session
        self._calls = 0

    def query(self, model):
        # First query is the session; anything after is the item count.
        self._calls += 1
        return _Query(self._session if self._calls == 1 else None)


def _build(session):
    return study_summary.build(_Db(session), session.id)


# --- assessments say nothing ------------------------------------------------

@pytest.mark.parametrize("phase", ["pretest", "posttest", "delayed"])
def test_an_assessment_summary_carries_no_score(phase):
    item = _Item("ship", "kit_fleece")
    body = _build(_Session(phase, [_Activity(item, correct=False)]))

    assert body["scored"] is False
    assert body["accuracy_percentage"] is None
    assert body["correct_answers"] is None
    assert body["recommendations"] == []
    assert body["strengths"] == []
    assert body["areas_for_improvement"] == []


def test_an_assessment_activity_row_hides_the_verdict():
    """The per-item list is on the same screen. Marking each row right or wrong
    would tell the participant everything the percentage would have."""
    item = _Item("ship", "kit_fleece")
    body = _build(_Session("pretest", [_Activity(item, correct=False)]))
    row = body["activities"][0]

    for leak in ("is_correct", "verdict", "score", "feedback"):
        assert leak not in row, f"assessment summary leaked {leak}"
    assert row["item_name"] == "ship"


def test_a_training_summary_does_score():
    item = _Item("ship", "kit_fleece")
    body = _build(_Session("training", [_Activity(item, correct=True)],
                           condition="K"))
    assert body["scored"] is True
    assert body["accuracy_percentage"] == 100.0
    assert body["activities"][0]["is_correct"] is True


# --- what counts --------------------------------------------------------------

def test_gated_and_skipped_attempts_stay_out_of_the_denominator():
    """Neither is evidence that the word was produced wrongly. Counting either
    as an error is the false rejection this system exists to avoid."""
    good, gated, skipped = _Item("ship"), _Item("bit"), _Item("pull")
    body = _build(_Session("training", [
        _Activity(good, correct=True),
        _Activity(gated, correct=False, gated=True),
        _Activity(skipped, correct=None, skipped=True),
    ]))
    assert body["accuracy_percentage"] == 100.0
    assert body["excluded_from_accuracy"] == 2
    assert body["skipped"] == 1


def test_only_the_last_attempt_at_an_item_counts():
    """Retries only happen after an error, so averaging every attempt is biased
    downwards by exactly the items the participant went on to get right."""
    item = _Item("ship")
    body = _build(_Session("training", [
        _Activity(item, correct=False, attempt=1),
        _Activity(item, correct=True, attempt=2),
    ]))
    assert body["accuracy_percentage"] == 100.0
    assert body["correct_answers"] == 1
    # Every attempt is still listed; only the scoring is deduplicated.
    assert len(body["activities"]) == 2


def test_a_skipped_item_does_not_enter_the_response_time_mean():
    item, skipped = _Item("ship"), _Item("bit")
    body = _build(_Session("training", [
        _Activity(item, response_time=2.0),
        _Activity(skipped, skipped=True, response_time=99.0),
    ]))
    assert body["average_response_time"] == 2.0


# --- duration ---------------------------------------------------------------

def test_duration_falls_back_to_the_attempts_when_end_time_is_missing():
    """Every study session before the complete endpoint has end_time NULL, and
    the old overview reported all of them as zero minutes."""
    item = _Item("ship")
    start = datetime(2026, 9, 17, 10, 0, 0)
    body = _build(_Session("training", [
        _Activity(item, created_at=start),
        _Activity(_Item("bit"), created_at=start + timedelta(minutes=6)),
    ]))
    assert body["duration_minutes"] == 6.0


def test_duration_is_null_not_zero_when_it_cannot_be_known():
    """0.0 would be averaged into a mean as though it had been observed."""
    body = _build(_Session("training", [_Activity(_Item("ship"))]))
    assert body["duration_minutes"] is None


def test_a_recorded_end_time_wins():
    start = datetime(2026, 9, 17, 10, 0, 0)
    body = _build(_Session("training", [_Activity(_Item("ship"))],
                           end_time=start + timedelta(minutes=12)))
    assert body["duration_minutes"] == 12.0


# --- breakdowns -------------------------------------------------------------

def test_production_and_perception_are_reported_separately():
    """One accuracy figure over both would average two different constructs."""
    body = _build(_Session("training", [
        _Activity(_Item("ship", "kit_fleece"), correct=True),
        _Activity(_Item("bit", "kit_fleece"), correct=False,
                  exercise_type="minimal_pair_id"),
    ]))
    keys = {row["key"]: row for row in body["by_exercise"]}
    assert keys["repeat_word"]["accuracy_percentage"] == 100.0
    assert keys["minimal_pair_id"]["accuracy_percentage"] == 0.0


def test_results_are_grouped_by_target_feature():
    """The reason Phase 3 put a feature on every item: one aggregate number
    cannot say which contrast improved."""
    body = _build(_Session("training", [
        _Activity(_Item("ship", "kit_fleece"), correct=True),
        _Activity(_Item("bit", "kit_fleece"), correct=False),
        _Activity(_Item("think", "dental_fricative"), correct=True),
    ]))
    features = {row["key"]: row for row in body["by_feature"]}
    assert features["kit_fleece"]["accuracy_percentage"] == 50.0
    assert features["dental_fricative"]["accuracy_percentage"] == 100.0
    assert features["kit_fleece"]["label"] == "KIT / FLEECE"


def test_recording_quality_is_surfaced_not_buried():
    """A session whose recordings were mostly unusable is one to re-run, and
    that decision has to be made while the participant is still there."""
    body = _build(_Session("training", [
        _Activity(_Item("ship"), quality="ok"),
        _Activity(_Item("bit"), quality="quiet"),
        _Activity(_Item("pull"), quality="quiet"),
    ]))
    assert body["recording_quality"] == {"ok": 1, "quiet": 2}


# --- advice -----------------------------------------------------------------

def test_a_short_session_gets_no_advice():
    """The old version always said something, including "Excellent progress!"
    after four attempts. Advice with no evidence behind it is noise the
    researcher learns to skip, and then they miss the line that mattered."""
    body = _build(_Session("training", [_Activity(_Item("ship"))]))
    assert body["recommendations"] == []


def test_a_weak_feature_is_named():
    activities = [_Activity(_Item(f"w{i}", "kit_fleece"), correct=False)
                  for i in range(4)]
    activities += [_Activity(_Item(f"g{i}", "foot_goose"), correct=True)
                   for i in range(4)]
    body = _build(_Session("training", activities))
    assert any("KIT / FLEECE" in line for line in body["recommendations"])
    assert not any("FOOT / GOOSE" in line for line in body["recommendations"])


def test_bad_recordings_are_called_out():
    activities = [_Activity(_Item(f"w{i}"), quality="quiet") for i in range(6)]
    body = _build(_Session("training", activities))
    assert any("microphone" in line for line in body["recommendations"])
