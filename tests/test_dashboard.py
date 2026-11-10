"""The dashboard's definitions must match the analysis's.

Accuracy over final attempts, gated and skipped excluded, training only;
the funnel in protocol order; quality folded onto four meanings a reader can
act on. These pin the helpers those rest on.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import dashboard  # noqa: E402


class _S:
    def __init__(self, session_type, block_index=None):
        self.session_type = session_type
        self.block_index = block_index


class _A:
    def __init__(self, session_id, item_id, attempt_number):
        self.session_id = session_id
        self.item_id = item_id
        self.attempt_number = attempt_number


def test_the_funnel_is_in_protocol_order():
    assert [k for k, _ in dashboard.STEPS] == ["pretest", "block1", "block2", "posttest", "delayed"]


def test_a_training_session_maps_to_its_block():
    assert dashboard._step_of(_S("training", 1)) == "block1"
    assert dashboard._step_of(_S("training", 2)) == "block2"
    assert dashboard._step_of(_S("pretest")) == "pretest"


def test_an_unstamped_or_malformed_session_is_not_a_step():
    """An ad-hoc session is not part of the protocol, and a training session
    with no block index cannot be placed in the funnel."""
    assert dashboard._step_of(_S(None)) is None
    assert dashboard._step_of(_S("training", None)) is None


def test_only_the_last_attempt_at_an_item_counts():
    s, i = uuid.uuid4(), uuid.uuid4()
    finals = dashboard._final_attempts([_A(s, i, 1), _A(s, i, 2), _A(s, uuid.uuid4(), 1)])
    assert len(finals) == 2
    assert max(a.attempt_number for a in finals if a.item_id == i) == 2


def test_quality_folds_onto_four_actionable_meanings():
    """Six verdicts is more classes than a reader can hold; what they need to
    know is clean, move the mic closer, move it back, or lost."""
    assert set(dashboard.QUALITY_FOLD.values()) == {"clean", "quiet", "clipped", "lost"}
    assert dashboard.QUALITY_FOLD["ok"] == "clean"
    for lost in ("short", "long", "silent"):
        assert dashboard.QUALITY_FOLD[lost] == "lost"


def test_a_rate_over_nothing_is_null_not_zero():
    """0% with no attempts would be averaged into a mean as though observed."""
    assert dashboard._rate(0, 0) is None
    assert dashboard._rate(3, 4) == 75.0
