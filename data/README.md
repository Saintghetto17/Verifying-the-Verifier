# Data

The benchmark lives on Hugging Face:
**[Saintghetto17/verifying-the-verifier](https://huggingface.co/datasets/Saintghetto17/verifying-the-verifier)**.

```bash
python -m vtv download      # metadata, splits and images into data/
python -m vtv validate
```

After download:

```text
data/
  pairs/<subset>/<local_id>/orig.png   reference figure V+
  pairs/<subset>/<local_id>/fail.png   counterfactual twin V-
  metadata/pairs.jsonl                 one record per pair (488)
  metadata/ml_candidates.jsonl         ML candidates and their filter outcome
  metadata/summary.json
  splits/*.txt                         versioned in git as well
```

| Split | Pairs | Use |
|---|---:|---|
| `ml` | 201 | ML paired run |
| `bt` / `bt_run` | 212 / 208 | all BT pairs / BT paired run (4 out-of-region pairs held out) |
| `b75` / `b75_images` | 75 / 15 | all B75 records / B75 pairs with released images |
| `balanced100` | 100 | operator-balanced ML sample for the ablation, Tables III, IV and VI |

Only 15 of the 75 B75 image pairs are released so far; the remaining 60 will
be uploaded soon. `summary.json` here is a copy of the release summary.
See [`../docs/DATASET.md`](../docs/DATASET.md) for construction details.
