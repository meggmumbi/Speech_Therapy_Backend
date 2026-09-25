"""Inter-rater agreement is computed, so the arithmetic is pinned.

Worked examples with known answers, so a reviewer who recomputes a kappa
from the exported ratings gets the number the console showed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import agreement  # noqa: E402


def test_percent_agreement_ignores_missing():
    assert agreement.percent_agreement([1, 0, 1, None], [1, 1, 1, 0]) == pytest.approx(66.7)
    assert agreement.percent_agreement([], []) is None


def test_cohen_kappa_textbook_example():
    """20 subjects, raters agree on 14: kappa well below the 70% agreement."""
    a = [1] * 10 + [0] * 10
    b = [1] * 7 + [0] * 3 + [0] * 7 + [1] * 3
    assert agreement.percent_agreement(a, b) == 70.0
    assert agreement.cohen_kappa(a, b) == pytest.approx(0.4, abs=0.001)


def test_cohen_kappa_is_zero_at_chance_and_one_at_perfect():
    assert agreement.cohen_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    assert agreement.cohen_kappa([1, 1, 0, 0], [1, 0, 1, 0]) == pytest.approx(0.0)


def test_fleiss_kappa_matches_the_two_rater_case():
    a = [1] * 10 + [0] * 10
    b = [1] * 7 + [0] * 3 + [0] * 7 + [1] * 3
    assert agreement.fleiss_kappa(list(zip(a, b))) == pytest.approx(agreement.cohen_kappa(a, b), abs=0.01)


def test_fleiss_kappa_drops_subjects_with_uneven_raters():
    """A clip two raters saw and one three raters saw are not the same
    observation; the statistic assumes equal n per subject."""
    table = [(1, 1, 1), (0, 0, 0), (1, 0), (1, 1, 0), (0, 0, 1)]
    assert agreement.fleiss_kappa(table) == agreement.fleiss_kappa([r for r in table if len(r) == 3])


def test_fleiss_kappa_needs_two_raters_and_two_subjects():
    assert agreement.fleiss_kappa([(1,), (0,)]) is None
    assert agreement.fleiss_kappa([(1, 0)]) is None


def test_bands_use_the_same_word_every_time():
    assert agreement.describe_kappa(0.85) == "almost perfect"
    assert agreement.describe_kappa(0.5) == "moderate"
    assert agreement.describe_kappa(-0.1) == "poor"
    assert agreement.describe_kappa(None) == "not computable"


def test_mean_absolute_difference():
    assert agreement.mean_absolute_difference([5, 3, None], [4, 3, 1]) == 0.5
