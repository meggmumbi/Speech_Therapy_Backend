"""The revisit round: corrected items come back once at the end of a block.

Why it exists: the assessments present only the test set, and every feature
is trained under both conditions in every participant, so a pre-to-post gain
cannot be attributed to K or D. One more attempt at each corrected item, a
few minutes later, under the same condition, is the only within-session
retention measure that carries a condition. These tests pin the selection
rule, the stamp on the row, and the two places the stamp must be respected.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: E402
from app.api import study  # noqa: E402
from app.database import get_db  # noqa: E402
from app.services import dashboard, study_design, study_summary  # noqa: E402


def _a(item, correct, *, gated=False, skipped=False, verbal=True, revisit=False, n=1):
    return SimpleNamespace(item_id=item, is_correct=correct, gated=gated, skipped=skipped,
                           response_type="verbal" if verbal else "select", revisit=revisit,
                           attempt_number=n, session_id="s")


# --- the rule ------------------------------------------------------------------

def test_a_corrected_item_comes_back_and_a_clean_one_does_not():
    wrong, right = uuid.uuid4(), uuid.uuid4()
    out = study_design.revisit_item_ids([_a(wrong, False), _a(wrong, True, n=2), _a(right, True)], seed=None)
    assert out == [str(wrong)]


def test_an_item_not_repaired_on_attempt_two_still_comes_back():
    """The revisit asks whether the correction held, and that question is
    just as real for an item the participant never got right."""
    item = uuid.uuid4()
    assert study_design.revisit_item_ids([_a(item, False), _a(item, False, n=2)], None) == [str(item)]


def test_a_skipped_item_is_not_brought_back():
    item = uuid.uuid4()
    assert study_design.revisit_item_ids([_a(item, False), _a(item, None, skipped=True, n=2)], None) == []


def test_a_gated_only_item_is_not_a_correction():
    item = uuid.uuid4()
    assert study_design.revisit_item_ids([_a(item, False, gated=True), _a(item, True, n=2)], None) == []


def test_tapped_items_are_not_revisited():
    """In D the key was revealed after the wrong tap; a revisit would measure
    recall of the key, not the contrast."""
    item = uuid.uuid4()
    assert study_design.revisit_item_ids([_a(item, False, verbal=False)], None) == []


def test_revisit_rows_do_not_feed_the_selection():
    """Asking twice returns the same list; the revisits themselves never
    qualify an item for another round."""
    item, other = uuid.uuid4(), uuid.uuid4()
    rows = [_a(item, False), _a(item, True, n=2), _a(other, True), _a(other, False, revisit=True, n=2)]
    assert study_design.revisit_item_ids(rows, None) == [str(item)]


def test_order_comes_from_the_session_seed():
    items = [uuid.uuid4() for _ in range(6)]
    rows = [_a(i, False) for i in items]
    first = study_design.revisit_item_ids(rows, seed=42)
    assert first == study_design.revisit_item_ids(rows, seed=42)
    assert sorted(first) == sorted(str(i) for i in items)
    assert first != study_design.revisit_item_ids(rows, seed=43) or len(items) < 2


def test_the_intro_is_the_same_words_for_both_conditions():
    assert "test" not in study_design.REVISIT_INTRO.lower()
    assert "wrong" not in study_design.REVISIT_INTRO.lower()


# --- the stamp is respected downstream ---------------------------------------------

def test_dashboard_final_attempt_ignores_the_revisit():
    s, i = uuid.uuid4(), uuid.uuid4()
    rows = [SimpleNamespace(session_id=s, item_id=i, attempt_number=n, revisit=r)
            for n, r in ((1, False), (2, False), (3, True))]
    finals = dashboard._final_attempts(rows)
    assert [a.attempt_number for a in finals] == [2]


def test_summary_final_attempt_ignores_the_revisit():
    i = uuid.uuid4()
    rows = [SimpleNamespace(item_id=i, attempt_number=n, revisit=r)
            for n, r in ((1, False), (2, True))]
    finals = study_summary._final_attempts(rows)
    assert [a.attempt_number for a in finals] == [1]


def test_rows_written_before_the_round_read_as_main_round():
    """Old rows have no revisit attribute at all; they must not disappear."""
    s, i = uuid.uuid4(), uuid.uuid4()
    rows = [SimpleNamespace(session_id=s, item_id=i, attempt_number=1)]
    assert len(dashboard._final_attempts(rows)) == 1


# --- the endpoint ------------------------------------------------------------------

class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class _Db:
    def __init__(self, session, attempts, items):
        self.tables = {models.TherapySession: [session], models.SessionActivity: attempts,
                       models.ActivityItem: items}

    def query(self, model):
        return _Query(self.tables.get(model, []))


def _client(session, attempts, items):
    app = FastAPI()
    app.include_router(study.router, prefix="/study")
    app.dependency_overrides[get_db] = lambda: _Db(session, attempts, items)
    return TestClient(app)


def _item(word):
    return SimpleNamespace(id=uuid.uuid4(), name=word, description=f"Say the word. {word}", image_url=None,
                           audio_url=None, difficulty_level="medium", exercise_type="repeat_word",
                           effective_type="repeat_word", spec={"word": word}, target_feature="rhotic_lateral")


def test_a_training_session_returns_its_corrected_items_as_revisits():
    rice, road = _item("rice"), _item("road")
    session = SimpleNamespace(id=uuid.uuid4(), session_type="training", condition="D", item_order_seed=7)
    attempts = [_a(rice.id, False), _a(rice.id, True, n=2), _a(road.id, True)]
    body = _client(session, attempts, [rice, road]).get(f"/study/sessions/{session.id}/revisits").json()
    assert [i["id"] for i in body["items"]] == [str(rice.id)]
    assert body["items"][0]["revisit"] is True
    assert body["items"][0]["target_feature"] == "rhotic_lateral"
    assert body["condition"] == "D"
    assert body["intro_speech"] == study_design.REVISIT_INTRO


def test_an_assessment_has_no_revisit_round():
    session = SimpleNamespace(id=uuid.uuid4(), session_type="pretest", condition=None, item_order_seed=7)
    body = _client(session, [_a(uuid.uuid4(), False)], []).get(f"/study/sessions/{session.id}/revisits").json()
    assert body["items"] == []
    assert body["intro_speech"] is None


def test_nothing_corrected_means_no_round_and_no_intro():
    rice = _item("rice")
    session = SimpleNamespace(id=uuid.uuid4(), session_type="training", condition="K", item_order_seed=1)
    body = _client(session, [_a(rice.id, True)], [rice]).get(f"/study/sessions/{session.id}/revisits").json()
    assert body["items"] == [] and body["intro_speech"] is None


# --- attention segments ----------------------------------------------------------------

class _WriteDb(_Db):
    def __init__(self, session):
        super().__init__(session, [], [])
        self.added = []
        self.committed = False

    def query(self, model):
        q = super().query(model)
        q.delete = lambda: 0
        return q

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.committed = True


def _attention_client(session, db):
    from app.utils.auth import get_current_user
    app = FastAPI()
    app.include_router(study.router, prefix="/study")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
    return TestClient(app)


def test_attention_segments_are_stored_as_derived_states_only():
    session = SimpleNamespace(id=uuid.uuid4(), session_type="training", condition="K", item_order_seed=1)
    db = _WriteDb(session)
    item = uuid.uuid4()
    r = _attention_client(session, db).post(f"/study/sessions/{session.id}/attention", json={"segments": [
        {"item_id": str(item), "phase": "prompt", "started_at_ms": 1000, "ended_at_ms": 4000,
         "samples": 6, "attending_samples": 5, "states": {"LOOKING_AT_ROBOT": 5, "LOOKING_DOWN": 1}},
        {"item_id": str(item), "phase": "response", "started_at_ms": 4000, "ended_at_ms": 6000,
         "samples": 0, "attending_samples": 0, "states": {}},
    ]})
    assert r.status_code == 200, r.text
    assert db.committed and len(db.added) == 2
    prompt, response = db.added
    assert prompt.attending_fraction == pytest.approx(5 / 6)
    assert response.attending_fraction is None      # nobody detected: unknown, not zero
    assert prompt.states == {"LOOKING_AT_ROBOT": 5, "LOOKING_DOWN": 1}
    assert not hasattr(prompt, "image") and not hasattr(prompt, "estimated_age")


@pytest.mark.parametrize("bad", [
    {"phase": "thinking", "started_at_ms": 1, "ended_at_ms": 2},
    {"phase": "prompt", "started_at_ms": 5, "ended_at_ms": 2},
    {"phase": "prompt", "started_at_ms": 1, "ended_at_ms": 2, "samples": 1, "attending_samples": 2},
])
def test_malformed_segments_are_refused_whole(bad):
    session = SimpleNamespace(id=uuid.uuid4(), session_type="training", condition="K", item_order_seed=1)
    db = _WriteDb(session)
    r = _attention_client(session, db).post(f"/study/sessions/{session.id}/attention", json={"segments": [bad]})
    assert r.status_code == 422
    assert not db.committed
