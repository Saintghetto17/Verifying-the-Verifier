<p align="center">
  <h1 align="center">Verifying the Verifier</h1>
  <p align="center">
    <b>A Controlled-Counterfactual Benchmark for Scientific Figure Evaluators</b>
  </p>
  <p align="center">
    <a href="https://huggingface.co/datasets/Saintghetto17/verifying-the-verifier"><img alt="Hugging Face Dataset" src="https://img.shields.io/badge/Hugging%20Face-Dataset-FFD21E?style=for-the-badge&logo=huggingface&logoColor=black"></a>
    <a href="#citation"><img alt="ICDM 2026 Workshop" src="https://img.shields.io/badge/ICDM%202026-AI4S--Bench-3b82f6?style=for-the-badge"></a>
    <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/License-Apache%202.0-green?style=for-the-badge"></a>
  </p>
  <p align="center">
    Official implementation of our paper accepted at the<br/>
    <b>ICDM 2026 Workshop AI4S-Bench 2026</b>
  </p>
  <p align="center">
    <a href="https://huggingface.co/datasets/Saintghetto17/verifying-the-verifier"><b>🤗 Dataset</b></a>
    ·
    <a href="#quickstart"><b>🚀 Quickstart</b></a>
    ·
    <a href="#protocol"><b>🧠 Protocol</b></a>
    ·
    <a href="#reproducing-the-paper"><b>📊 Reproduce</b></a>
    ·
    <a href="#citation"><b>📚 Citation</b></a>
  </p>
</p>

---

## Overview

Autonomous pipelines that generate scientific figures rely on an automated
verifier to accept or regenerate each candidate. Published figures are faithful
by construction, so testing a verifier on them alone cannot show whether it
detects anything: a verifier that scores everything highly looks reliable.

This benchmark pairs every **reference figure** `V+` with a hand-authored
**counterfactual twin** `V- = P_k(V+)` that carries exactly one injected
semantic defect of a recorded type. The correct preference order is therefore
known before any model is called. The verifier scores each image **on its own**
from the caption `C`, the source-text block `T` and one image. It never sees
both images together and is never told which one it is looking at, as in a
generation pipeline.

| Question | How the benchmark answers it |
|---|---|
| Does the verifier rank the faithful figure above its corrupted twin? | Perturbation separation rate (PSR) on matched pairs |
| When it fails, is it wrong or undecided? | Full win / tie / inversion decomposition |
| Which defects does it miss? | Per-operator, per-topic and per-figure-type breakdowns |
| Is a second prompt worth paying for? | Ensemble gain, McNemar tests and Jaccard overlap of detections |

---

## Paper

| Field | Value |
|-------|-------|
| **Title** | Verifying the Verifier: A Controlled-Counterfactual Benchmark for Scientific Figure Evaluators |
| **Authors** | Egor Gromov, Ilia Novitskii, Boris Malashenko, Kirill Mironov, Nikolay Gavrishok, Evgenii Rutkovskii, Valeria Efimova (ITMO University) |
| **Venue** | ICDM 2026 Workshop AI4S-Bench 2026 |
| **Dataset** | [Saintghetto17/verifying-the-verifier](https://huggingface.co/datasets/Saintghetto17/verifying-the-verifier) |
| **Code** | this repository |

---

## Protocol

```text
 Reference V+        Corrupted V-
        \               /
         caption C + source text T + ONE image        (two independent requests per pair)
              |                      |
   TG: check every claim     HD: test eight corruption
       the text makes            hypotheses
              \                      /
        structured evidence ledger <P, U, M, R_bad, L_bad>   (per figure)
                          |
        deterministic rule (Eq. 1)  ->  F in {1, 3, 5}        (code, never the model)
                          |
        separated  iff  F_ens(V+) > F_ens(V-),   F_ens = (F_TG + F_HD) / 2
```

**Scoring rule (Eq. 1).** The model never reports a Faithfulness score. It
returns an evidence ledger, and code computes the score from it. With `P`
confirmed and `M` missing requirements, `U` unsupported elements, `R_bad`
missing or reversed relations, and `L_bad` mismatched label bindings,
`D = U + R_bad + L_bad` and `c = P / (P + M)`:

```text
F = 5   if D = 0 and c >= 0.80
    3   if D = 0 and 0.60 <= c < 0.80
    3   if D = 1 and M = 0
    1   otherwise
```

The thresholds were fixed before any run. The rule is monotone in `D` and `c`,
so relation and label checks can only lower a score. Clarity, Compactness and
Style are reported by the model for descriptive use only, combined as
`Overall = 0.45 F + 0.25 Cl + 0.15 Co + 0.15 S`. Separation depends on `F` alone.

**Configurations.** Both use `google/gemini-3.7-flash` (temperature 0, top-p 1,
seed 42, 16384 output tokens, medium reasoning) and differ only in how they
search for evidence:

| Configuration | Prompt | Direction of search |
|---|---|---|
| **TG**, text-grounded | [`prompts/v03_text_grounded.md`](prompts/v03_text_grounded.md) | from the text to the figure: every stated requirement must agree in object, label, order, direction and magnitude; every discrepancy is recorded; no inference beyond the text |
| **HD**, hypothesis-driven | [`prompts/v13_hypothesis_driven.md`](prompts/v13_hypothesis_driven.md) | from a taxonomy of eight corruption mechanisms to the figure; six of them can be tested from the image alone |

**Ensemble (Eq. 3).** The ensemble is the mean of the two completed runs'
scores. It makes no extra model call.

**Metrics.** For each pair the reference wins, ties or is inverted.
`PSR = wins / N`, the inversion rate is `inversions / N`, and the tie-adjusted
rate is `(wins + ties/2) / N`. The code also reports 95% Wilson intervals,
exact McNemar tests between configurations, exact binomial tests against the
no-tie 50% null, sign tests on resolved pairs, the Jaccard overlap of
detections, and the share of references scored at `F = 5` as a specificity
check.

See [`docs/PROTOCOL.md`](docs/PROTOCOL.md) for the full specification.

---

## Repository layout

```text
Verifying-the-Verifier/
├── vtv/                    # benchmark package (python -m vtv ...)
│   ├── data.py             # pairs, splits, selection (blind inputs only)
│   ├── prompts.py          # prompt registry and multimodal rendering
│   ├── ledger.py           # evidence-ledger validation
│   ├── scoring.py          # Eq. 1-2, U-penalty variants (Table VI)
│   ├── runner.py           # blind paired runner, 10 pairs in parallel
│   ├── openrouter.py       # OpenRouter client
│   ├── artifacts.py        # self-contained run directories
│   ├── analysis.py         # ensembles, gains/losses, overlaps, breakdowns
│   ├── metrics.py          # Wilson, exact binomial / McNemar / sign tests
│   ├── report.py           # recreates Tables I-VI from runs
│   ├── taxonomy.py         # ten normalized defect operators
│   └── viewer.py           # local read-only run viewer
├── prompts/                # the thirteen measured prompts + registry.json
├── scripts/build_dataset.py  # assembles the release from its source corpora
├── experiments/            # experiments-file template for `vtv tables`
├── data/                   # dataset (downloaded); split lists are versioned
├── viewer/                 # HTML/JS of the run viewer
├── docs/                   # protocol, dataset and reproduction notes
└── tests/                  # offline unit tests (no network, no cost)
```

---

## Quickstart

### 1. Environment

```bash
git clone https://github.com/Saintghetto17/Verifying-the-Verifier.git
cd Verifying-the-Verifier
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add OPENROUTER_API_KEY for live runs
```

### 2. Data

```bash
python -m vtv download        # Hugging Face -> data/
python -m vtv validate
```

### 3. Inspect without spending anything

```bash
python -m vtv prompts                                   # list v01..v13, TG and HD
python -m vtv render --subset ml --limit 1 --prompt hd  # exact text the verifier receives
python -m vtv run --subset ml --limit 2 --prompt tg --dry-run
python -m pytest -q                                     # offline tests
```

### 4. Live runs

```bash
python -m vtv run --prompt tg --subset ml --name tg_ml
python -m vtv run --prompt hd --subset ml --name hd_ml
python -m vtv report --tg runs/*__tg_ml --hd runs/*__hd_ml
python -m vtv viewer          # http://127.0.0.1:8080
```

Each pair issues two independent requests, one per figure. Ten pairs run in
parallel by default (`--workers`). An interrupted run continues with
`python -m vtv resume runs/<run>`, which keeps every successful call. Each
request allows three network attempts and two retries on an invalid ledger.
Use `--max-cost-usd` to cap spending.

**Screening a new verifier model.** A model that rejects genuine figures
separates nothing. A cheap check before a paired run:

```bash
python -m vtv screen --model x-ai/grok-4.3 --subset ml --limit 4
```

This scores references only and rejects the model when fewer than 70% of them
receive `F = 5`.

---

## Data

**[🤗 Saintghetto17/verifying-the-verifier](https://huggingface.co/datasets/Saintghetto17/verifying-the-verifier)**

| Subset | Domain | Pairs | Paired (paper) |
|---|---|---:|---:|
| ML | Machine learning | 201 | 198 |
| BT | Biotechnology, 16 topics | 212 | 204 |
| B75 | Climate modeling, materials discovery, drug discovery, protein structure prediction, Earth system science | 75 | 75 |
| **Total** | | **488** | **477** |

> **Release status.** All 488 records are published. Images are released for
> ML and BT in full and for 15 of the 75 B75 pairs. The remaining 60 B75 image
> pairs will be uploaded soon. Until then, `--subset b75` runs the 15 released
> pairs.

Four BT pairs whose stated corruption lies outside the figure region are
flagged (`flags.out_of_region`) and held out of the paired run
(`splits/bt_run.txt`). The ML subset is a deterministic reconstruction of the
paper's 201 pairs: the paper's manual exclusion list was not preserved (see
[`docs/DATASET.md`](docs/DATASET.md)). To rebuild the release from its source
corpora, run `scripts/build_dataset.py`.

---

## Reproducing the paper

1. Run TG and HD on each subset (six runs, ~$10 in total in the paper's setting).
2. Run the ablation versions and the third-configuration candidates on
   `--split balanced100`.
3. Copy [`experiments/paper.example.json`](experiments/paper.example.json) to
   `experiments/paper.json` and fill in the run directories.
4. Run `python -m vtv tables`, which writes `reports/tables.md` and
   `reports/results.json`.

Every table is recomputed from the stored ledgers. The U-penalty sweep
(Table VI) rescores existing ledgers offline, with no new calls. Details are in
[`docs/REPRODUCTION.md`](docs/REPRODUCTION.md).

### Prompt versions

| Version | Mechanism added | Role in the paper |
|---|---|---|
| v01 | entity presence only | Table V |
| v02 | presence does not satisfy | Table V |
| **v03** | scrutiny plus no inference | **TG configuration**, Table V |
| v04 | internal-consistency checks | Table V |
| v05 | two non-falsifiable checks | Table V |
| v06 | counting of quantified items | Table IV candidate |
| v07 | requirements before viewing | Table V |
| v08 | panel-grid checks | Table V |
| v09 | self-verification of accusations | Table IV candidate |
| v10 | one worked example | Table V |
| v11 | figure-type dependent checks | Table IV candidate |
| v12 | three-step reconstruction | Table V |
| **v13** | eight corruption hypotheses | **HD configuration**, Table V |

### Results reported in the paper

| Subset | N | TG (%) | HD (%) | Ensemble (%) | Ties | Inv. |
|---|---:|---:|---:|---:|---:|---:|
| ML | 198 | 44.4 | 54.5 | 61.1 [54.2–67.6] | 72 | 5 |
| BT | 204 | 51.0 | 56.9 | 64.2 [57.4–70.5] | 67 | 6 |
| B75 | 75 | 62.7 | 76.0 | 76.0 [65.2–84.2] | 15 | 3 |
| **All** | **477** | **50.1** | **58.9** | **64.8 [60.4–68.9]** | **154** | **14** |

The corrupted figure outranks the reference in only 14 of 477 pairs, so most
non-separations are ties, not errors. Averaging the two configurations
resolves 70 tied pairs and loses no pair that TG separates.

---

## Citation

```bibtex
@inproceedings{verifying_the_verifier_2026,
  title     = {Verifying the Verifier: A Controlled-Counterfactual Benchmark for Scientific Figure Evaluators},
  author    = {Gromov, Egor and Novitskii, Ilia and Malashenko, Boris and Mironov, Kirill and
               Gavrishok, Nikolay and Rutkovskii, Evgenii and Efimova, Valeria},
  booktitle = {ICDM 2026 Workshop AI4S-Bench 2026},
  year      = {2026}
}
```

## Acknowledgements

This work was carried out at ITMO University under project 666009, "A tool for
the automated presentation of scientific research results with verification of
the generated content authenticity".

## License

Code: Apache-2.0. Dataset metadata and annotations: CC BY 4.0. Figure images
remain subject to the licenses of their source publications.
