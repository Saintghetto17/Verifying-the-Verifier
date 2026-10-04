# Dataset construction

The release is assembled by [`scripts/build_dataset.py`](../scripts/build_dataset.py)
from three source corpora:

```bash
python scripts/build_dataset.py \
    --vba-root  <verification-before-assembly dataset clone> \
    --bt-source <bench_l2_folders.zip or directory> \
    --b75-root  <bench_final directory> \
    --out data --clean
```

## ML subset (201 pairs)

Source: the ML split of
[Verification Before Assembly](https://huggingface.co/datasets/Saintghetto17/verification-before-assembly)
(`figures/ml_l2_fail`, `figures/ml_orig` and their `golden/` counterparts). Each
corrupted figure is paired with the original that has the same
`document_N/figure_M` id.

| Step | Pairs |
|---|---:|
| Marked-corrupted candidates with both images | 245 |
| − marked but byte-identical to the reference | 5 |
| − source text under 40 words | 4 |
| − caption under 5 words | 1 |
| Automatic filters passed | 235 |
| Deterministic stand-in for the manual review | 201 |

The paper starts from the full 1645-entry manifest (1645 − 1402 unmarked − 15
identical − 4 short text − 1 short caption = 223) and then removes 22 pairs by
manual inspection. The released dump contains only the marked candidates, and
the list of 22 manual exclusions was not preserved. The build script therefore
selects 201 pairs deterministically. It keeps the paper's text-source strata
exactly (134 `mentions`, 32 `mentions+same_page_context`, 35
`same_page_context`) and, within each stratum, the pairs with the longest
source-text block. Every record carries
`flags.selection = "approximate_paper_201"`, and
`metadata/ml_candidates.jsonl` lists every candidate with the step that removed
it.

**Operator tags.** The ML descriptions are free-form Russian text
(`defect.description_ru`). [`vtv/taxonomy.py`](../vtv/taxonomy.py) maps them to
ten normalized operators. Each comma-separated clause gets one tag by priority,
and a clause without a verb inherits the tag of the clause before it. Tags are
mentions, not a partition: one injection may carry several tags. Affected-object
tags (blocks, labels, images, plots, arrows, axes) are derived the same way.
The rules are a reconstruction, so the counts are close to, but not identical
with, the counts printed in the paper (see `metadata/summary.json`).

## BT subset (212 pairs)

Source: `bench_l2_folders` (212 folders). Each folder holds the original and
the corrupted page crop of the same rectangle, the caption, the passage that
discusses the figure, the extracted entities (at least three), the annotator's
description, and normalized English labels. Topics come from `topic_primary`
(16 topics).

Four pairs have `visual_diff_verified = false`: the declared corruption is
absent from the figure region. They are released with
`flags.out_of_region = true` and excluded from `splits/bt_run.txt` (208 pairs):

- `bt/paper_65_figure_7`: the corrupted page renders identically
- `bt/paper_24_figure_6c`, `bt/paper_46_figure_6`, `bt/paper_157_figure_2`:
  the pixel differences are in body text only

## B75 subset (75 records, 15 with images so far)

Source: `bench_final/dataset.jsonl`. It holds 64 hand-made corruptions on
conference-topic papers and 11 drug-discovery pairs from the biotechnology
corpus (ids prefixed `bt_`; their images are taken from the matching BT
folder). Records keep topic, figure type, panel count, entities and the
annotator's free-form labels.

At release time, images are available for 15 pairs: the 11 `bt_` pairs and
4 Earth-system-science pairs. **The remaining 60 image pairs will be uploaded
soon.** Their records are already in `metadata/pairs.jsonl` with
`images_available = false`. Selecting them for a run raises an error instead
of running on missing inputs.

## Operator-balanced sample (100 pairs)

`splits/balanced100.txt` is drawn from the ML subset by round-robin over the
ten operators. Each pair is assigned to its first operator tag, each operator's
pool is shuffled with seed 42, and exhausted operators are skipped. The paper
uses a 100-pair balanced sample for the prompt ablation and for Tables III, IV
and VI.
