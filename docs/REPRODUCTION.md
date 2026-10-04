# Reproduction

All commands run from the repository root. Live runs need `OPENROUTER_API_KEY`
in `.env`. In the paper's setting one configuration costs about $0.011 per
pair, and the full set of measurements costs about $10.

## 1. Data

```bash
python -m vtv download
python -m vtv validate
```

## 2. Main runs (Table II, Sections VII-A to VII-D)

```bash
for subset in ml bt b75; do
  python -m vtv run --prompt tg --subset $subset --name tg_$subset
  python -m vtv run --prompt hd --subset $subset --name hd_$subset
done
python -m vtv report --tg runs/*__tg_* --hd runs/*__hd_*
```

`report` prints Table II, the gains and losses of the ensemble against each
configuration with exact McNemar p-values, the Jaccard overlap of detections,
the either-rule rate, tie-adjusted rates, binomial and sign tests, the share of
references at `F = 5`, the references at the floor under both configurations,
the agreement of the unsupported counter, and the per-operator, per-topic and
per-figure-type breakdowns.

## 3. Prompt ablation (Table V) and third configurations (Table IV)

```bash
for v in v01 v02 v04 v05 v07 v08 v10 v12; do
  python -m vtv run --prompt $v --split balanced100 --name $v
done
for v in v06 v09 v11; do
  python -m vtv run --prompt $v --split balanced100 --name $v
done
```

In the paper the ablation versions were measured on samples of different
sizes (11 to 198 pairs); `--limit` reproduces a smaller sample. Versions whose
PSR falls within about ±10 points of each other on 100 pairs cannot be
distinguished statistically.

## 4. Tables

```bash
cp experiments/paper.example.json experiments/paper.json   # fill in run directories
python -m vtv tables --experiments experiments/paper.json --out reports
```

| Table | Source |
|---|---|
| I corpus | `data/metadata/pairs.jsonl` + pairs completed by both configurations |
| II separation by subset | `main` TG and HD runs |
| III separation by axis per operator | `halo.config` run restricted to `halo.split` |
| IV third configurations | `third.candidates` against `main` on `third.split` |
| V prompt ablation | `ablation` runs |
| VI U-penalty sensitivity | `thresholds.config` ledgers rescored offline |

## 5. Inspecting runs

```bash
python -m vtv viewer
```

The viewer shows both images, the caption and source text, each side's ledger
and computed counts, and the injected defect, which the verifier never saw.

## What is in a run directory

`run.json` holds the full configuration, the prompt version and its SHA-256,
the selected pair ids and a running summary of cost and status. Each side of
each pair stores the request without base64 image data, every raw response
attempt, and the validated result. A run is therefore auditable, and it can be
re-scored without new calls.

## Known differences from the paper's runs

- The ML subset is a deterministic reconstruction of the paper's 201 pairs
  ([DATASET.md](DATASET.md)), so ML numbers will not match the paper exactly.
- Only 15 of the 75 B75 image pairs are released so far; the rest will be
  uploaded soon.
- Hosted models change over time. `run.json` records the model id that was
  requested, and each result records the model id the provider returned.
