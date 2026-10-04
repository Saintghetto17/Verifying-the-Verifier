import json

import pytest

from conftest import FakeClient
from vtv import analysis as A
from vtv.artifacts import RunStore
from vtv.config import RunConfig
from vtv.data import DatasetError, load_pairs, select
from vtv.prompts import load_prompt
from vtv.report import Report
from vtv.runner import Runner


def run(data_root, tmp_path, prompt, client, name, **select_kwargs):
    pairs = select(load_pairs(data_root), data_root=data_root, **select_kwargs)
    config = RunConfig(workers=4)
    store = RunStore.create(pairs, load_prompt(prompt), config, runs_root=tmp_path / "runs", name=name)
    Runner(config, load_prompt(prompt), client).run(store, pairs, progress=False)
    return store


def test_selection_rejects_unreleased_images(data_root):
    pairs = load_pairs(data_root)
    with pytest.raises(DatasetError):
        select(pairs, data_root=data_root, ids=["b75/paper_9_figure_1"])
    assert len(select(pairs, data_root=data_root, subsets=["ml"])) == 6


def test_paired_run_and_resume(data_root, tmp_path):
    store = run(data_root, tmp_path, "tg", FakeClient(), "tg", subsets=["ml"])
    summary = store.read_run()["summary"]
    assert summary["complete"] == 6 and summary["calls"] == 12
    record = store.index_records()[0]
    assert record["orig"]["scores"]["faithfulness"] == 5 and record["fail"]["scores"]["faithfulness"] == 3
    request = json.loads((store.side_dir(record["pair_id"], "fail") / "request.json").read_text())
    assert "defect" not in json.dumps(request["messages"])
    client = FakeClient()
    Runner(RunConfig(), load_prompt("tg"), client).run(store, select(load_pairs(data_root), data_root=data_root, subsets=["ml"]), progress=False)
    assert client.calls == 0  # successful sides are reused


def test_invalid_json_is_retried(data_root, tmp_path):
    client = FakeClient(invalid_first=True)
    store = run(data_root, tmp_path, "tg", client, "retry", ids=["ml/doc_0__figure_1"])
    sides = [store.read_result("ml/doc_0__figure_1", s) for s in ("orig", "fail")]
    assert all(s["status"] == "success" for s in sides)
    assert sum(len(s["validation_errors"]) for s in sides) == 1


def test_ensemble_and_report(data_root, tmp_path):
    tg = run(data_root, tmp_path, "tg", FakeClient(fail_unsupported=0), "tg", subsets=["ml", "bt"])
    hd = run(data_root, tmp_path, "hd", FakeClient(hypotheses=8, fail_unsupported=1), "hd", subsets=["ml", "bt"])
    t, h = A.load_run(tg.run_dir), A.load_run(hd.run_dir)
    assert A.decomposition(t).psr == 0.0 and A.decomposition(t).ties == 10
    ens = A.ensemble(t, h)
    assert A.decomposition(ens).psr == 1.0
    assert A.gain_loss(t, ens) == {"n": 10, "gained": 10, "lost": 0, "p_mcnemar": pytest.approx(2 * 0.5 ** 10)}
    assert A.refs_at_max(h) == 1.0
    # Table VI: removing the U penalty erases HD's only signal on this fake data.
    assert A.decomposition(A.load_run(hd.run_dir, variant="no_u")).psr == 0.0

    spec = {"data_root": str(data_root), "main": {"tg": [str(tg.run_dir)], "hd": [str(hd.run_dir)]},
            "ablation": {"v03": [str(tg.run_dir)], "v13": [str(hd.run_dir)]},
            "third": {"split": "balanced100", "candidates": {"v11": [str(hd.run_dir)]}},
            "halo": {"split": "balanced100", "config": "hd"},
            "thresholds": {"split": "balanced100", "config": "hd"}}
    text = Report(spec, tmp_path).build()
    for title in ("Table I", "Table II", "Table III", "Table IV", "Table V", "Table VI"):
        assert title in text
    assert "| All | 10 | 0.0 | 100.0 |" in text
