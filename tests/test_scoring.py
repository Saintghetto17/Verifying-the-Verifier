import pytest

from vtv.scoring import EvidenceCounts, faithfulness, outcome, overall


def F(P, M, U=0, R=0, L=0, variant="current"):
    return faithfulness(EvidenceCounts(P=P, M=M, U=U, R_bad=R, L_bad=L), 0.60, 0.80, variant)


def test_rule_cases():
    assert F(4, 1) == 5            # D=0, c=0.80 (boundary goes up)
    assert F(3, 1) == 3            # D=0, c=0.75
    assert F(3, 2) == 3            # D=0, c=0.60 (boundary goes up)
    assert F(1, 1) == 1            # D=0, c=0.50
    assert F(5, 0, U=1) == 3       # D=1, M=0
    assert F(5, 1, U=1) == 1       # D=1, M>0
    assert F(5, 0, U=2) == 1       # D=2
    assert F(5, 0, R=1) == 3 and F(5, 0, L=1) == 3
    assert F(5, 0, U=1, L=1) == 1


def test_monotone_in_defects_and_coverage():
    for P in range(1, 7):
        for M in range(0, 5):
            scores = [F(P, M, U=u) for u in range(4)]
            assert scores == sorted(scores, reverse=True)
    for d in range(3):
        scores = [F(P, 10 - P, U=d) for P in range(1, 11)]
        assert scores == sorted(scores)


def test_relation_and_label_checks_only_lower():
    for P, M in [(5, 0), (4, 1), (3, 2)]:
        assert F(P, M, R=1) <= F(P, M) and F(P, M, L=2) <= F(P, M)


def test_u_penalty_variants():
    assert F(5, 0, U=1, variant="shift_one") == 5
    assert F(5, 0, U=2, variant="shift_one") == 3
    assert F(5, 0, U=3, variant="shift_one") == 1
    assert F(5, 0, U=1, variant="single_free") == 5
    assert F(5, 0, U=2, variant="single_free") == 1
    assert F(5, 0, U=7, variant="no_u") == 5


def test_invalid_counts():
    with pytest.raises(ValueError):
        EvidenceCounts(P=0, M=0, U=0)
    with pytest.raises(ValueError):
        EvidenceCounts(P=-1, M=2, U=0)


def test_overall_and_outcome():
    assert overall(5, 5, 5, 5) == 5.0
    assert overall(1, 3, 5, 5) == pytest.approx(0.45 + 0.75 + 0.75 + 0.75)
    with pytest.raises(ValueError):
        overall(2, 3, 3, 3)
    assert outcome(5, 3) == "win" and outcome(3, 3) == "tie" and outcome(1, 3) == "inversion"
