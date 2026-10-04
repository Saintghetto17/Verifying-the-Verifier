"""Check the statistics against values reported in the paper."""

import pytest

from vtv.metrics import binomial_test, decompose, jaccard, mcnemar_exact, sign_test, wilson


def test_wilson_matches_paper():
    lo, hi = wilson(309, 477)
    assert (round(100 * lo, 1), round(100 * hi, 1)) == (60.4, 68.9)
    lo, hi = wilson(121, 198)          # ML ensemble 61.1%
    assert (round(100 * lo, 1), round(100 * hi, 1)) == (54.2, 67.6)


def test_binomial_against_coin():
    assert binomial_test(239, 477) == pytest.approx(1.0)                 # TG 50.1%
    assert binomial_test(281, 477) == pytest.approx(1.2e-4, rel=0.1)     # HD 58.9%
    assert binomial_test(309, 477) == pytest.approx(1.1e-10, rel=0.1)    # ensemble 64.8%
    assert sign_test(309, 14) < 1e-70


def test_mcnemar_exact():
    assert mcnemar_exact(70, 0) == pytest.approx(1.7e-21, rel=0.05)
    assert mcnemar_exact(15, 0) == pytest.approx(6.1e-5, rel=0.05)
    assert mcnemar_exact(1, 1) == pytest.approx(1.0)


def test_decomposition():
    d = decompose({"a": (5, 3), "b": (3, 3), "c": (1, 3), "d": (5, 1)})
    assert (d.wins, d.ties, d.inversions) == (2, 1, 1)
    assert d.psr == 0.5 and d.inversion_rate == 0.25 and d.tie_adjusted == 0.625


def test_jaccard():
    assert jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)
