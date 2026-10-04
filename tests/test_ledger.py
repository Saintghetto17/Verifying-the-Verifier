import json

import pytest

from conftest import ledger
from vtv.config import RunConfig
from vtv.ledger import LedgerError, parse_ledger

CFG = RunConfig()


def test_counts_and_score():
    out = parse_ledger(ledger(confirmed=4, missing=1, unsupported=1), CFG)
    c = out["computed"]["counts"]
    assert (c["P"], c["M"], c["U"], c["D"]) == (4, 1, 1, 1)
    assert out["computed"]["scores"]["faithfulness"] == 1


def test_relations_count_as_defects():
    out = parse_ledger(ledger(confirmed=5, bad_relations=1), CFG)
    assert out["computed"]["counts"]["R_bad"] == 1
    assert out["computed"]["scores"]["faithfulness"] == 3


def test_fenced_json_is_accepted():
    assert parse_ledger("```json\n" + ledger() + "\n```", CFG)["status"] == "success"


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(requirements=p["requirements"][:2]),
    lambda p: p["requirements"][0].update(status="present"),
    lambda p: p["axes"].update(clarity=4),
    lambda p: p.pop("unsupported"),
    lambda p: p["requirements"][0].update(text_evidence=""),
])
def test_invalid_ledgers(mutate):
    payload = json.loads(ledger())
    mutate(payload)
    with pytest.raises(LedgerError):
        parse_ledger(json.dumps(payload), CFG)


def test_hypotheses_required_for_hd():
    with pytest.raises(LedgerError):
        parse_ledger(ledger(), CFG, require_hypotheses=8)
    assert parse_ledger(ledger(hypotheses=8), CFG, require_hypotheses=8)["status"] == "success"
    with pytest.raises(LedgerError):
        parse_ledger(ledger(hypotheses=7), CFG, require_hypotheses=8)


def test_not_json():
    with pytest.raises(LedgerError):
        parse_ledger("The figure looks fine.", CFG)
