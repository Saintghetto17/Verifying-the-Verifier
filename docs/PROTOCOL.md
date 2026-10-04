# Verification protocol

This page specifies what a run does, so that any verifier can be evaluated
under the same conditions as in the paper.

## Task

Each instance is a triplet `(T, C, V)`: the source-text block `T`, the caption
`C` and one image `V`. For a faithful reference `V+` the counterfactual is
`V- = P_k(V+)`, where `P_k` is one defect operator with a recorded label.

- The verifier receives `(T, C, V)` and returns a structured evidence ledger.
- It never receives the paired image, the defect record, or any indication of
  whether `V` is `V+` or `V-`.
- The two sides of a pair are two independent HTTP requests with separate
  sessions and no shared context ([`vtv/runner.py`](../vtv/runner.py)).

## Evidence ledger

All prompt versions return the same JSON format; they differ only in how they
search for evidence. The ledger is validated in [`vtv/ledger.py`](../vtv/ledger.py).

| Field | Content | Counted as |
|---|---|---|
| `requirements[]` | what the text requires, with a verbatim quote; status `confirmed` or `missing` | `P`, `M` |
| `unsupported[]` | visual elements that contradict the text, or extend a structure the text describes completely | `U` |
| `relations[]` | relations the text states; status `correct`, `missing` or `wrong_direction` | `R_bad` = non-`correct` |
| `label_bindings[]` | labels the text binds to entities; status `match` or `mismatch` | `L_bad` = `mismatch` |
| `hypotheses[]` | HD only: verdicts on H1 to H8 (`trace_found`, `no_trace`, `not_testable`) | not counted directly |
| `axes` | Clarity, Compactness, Style in {1, 3, 5} | descriptive |
| `audit` | short justification per axis | descriptive |

A ledger with fewer than three requirements, an unknown status, an axis value
outside {1, 3, 5}, or missing fields is invalid. An invalid ledger is retried
with a fresh request, up to two times. Any Faithfulness value the model reports
is ignored.

## Scoring

`D = U + R_bad + L_bad`, `c = P / (P + M)`, `tau_min = 0.60`, `tau_max = 0.80`:

| Condition | F |
|---|---:|
| `D = 0` and `c >= tau_max` | 5 |
| `D = 0` and `tau_min <= c < tau_max` | 3 |
| `D = 1` and `M = 0` | 3 |
| otherwise | 1 |

`Overall = 0.45 F + 0.25 Cl + 0.15 Co + 0.15 S` is descriptive. Separation and
every benchmark result use `F` alone ([`vtv/scoring.py`](../vtv/scoring.py)).

The U-penalty variants of Table VI are applied offline to stored counts:

| Variant | Effective `U` |
|---|---|
| `current` | `U` |
| `shift_one` | `max(U - 1, 0)` (U >= 3 -> 1, U = 2 -> 1 or 3) |
| `single_free` | `0` if `U = 1`, else `U` |
| `no_u` | `0` |

## Configurations

| Alias | Version | Search direction |
|---|---|---|
| `tg` | v03 | text to figure: typed requirements (entity, label, order, relation, value); presence alone does not satisfy; record every discrepancy; no inference beyond the text; omission is not contradiction |
| `hd` | v13 | the TG core plus eight corruption hypotheses: label/text edit, deletion, permutation, edge rewiring, content replacement, geometric distortion, addition/duplication, value fabrication |

The HD hypothesis set overlaps the corpus taxonomy. Its scores are therefore
an upper bound for a deployment in which the defect distribution is unknown.

## Ensemble

`F_ens = (F_TG + F_HD) / 2`, computed per figure from completed runs. A pair
is separated when `F_ens(V+) > F_ens(V-)`. Only pairs completed by both
configurations enter the paired analysis. The asymmetric "either configuration
separates" rule is reported for comparison.

## Metrics

| Metric | Definition |
|---|---|
| PSR | `wins / N`, with `wins` the pairs where `F(V+) > F(V-)` |
| Inversion rate | `inversions / N` |
| Tie-adjusted rate | `(wins + ties / 2) / N`, the rank statistic of a paired comparison |
| Interval | 95% Wilson score interval |
| Configuration comparison | exact McNemar test on discordant pairs (gains vs losses) |
| Against chance | exact two-sided binomial test of PSR against the no-tie 50% null |
| Direction | sign test of wins against inversions among resolved pairs |
| Complementarity | Jaccard overlap of the sets of pairs each configuration separates |
| Accusation agreement | Jaccard overlap of figures with `U >= 1` under each configuration, on references and on corrupted figures separately |
| Specificity | share of references scored at `F = 5`; for the ensemble this changes meaning, because averaging changes the score's support |

Reference points: a no-tie coin flip separates 50%; an always-accept verifier
ties every pair and separates 0%. A candidate model whose references fall
below roughly 70% at `F = 5` on a small screen should be rejected
(`python -m vtv screen`).

## Decoding and retries

`temperature = 0`, `top_p = 1`, `seed = 42`, `max_tokens = 16384`, reasoning
effort `medium`, `response_format = json_object`. Each request gets three
network attempts with back-off. Ten pairs are processed in parallel. All
parameters are stored in every run's `run.json`.
