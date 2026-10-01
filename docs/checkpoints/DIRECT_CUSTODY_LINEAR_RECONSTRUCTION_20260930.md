# Direct-source linear reconstruction and niche-genre guardrail

The new local reconstruction candidate improves held-out source-genre recovery
while preserving the exact portable source cohort: **387,435 artist–genre pairs,
198,409 artist MBIDs, and 697 seed IDs**. No names, release credits, tags,
historical memberships, coordinates, or historical neighbor judgments enter
training, selection, or evaluation.

The selected model retrieves **33,489 of 77,206 test positives at rank 10**,
compared with **32,999** for the previous specificity-transfer model on the same
new split. Micro Recall@10 improves **42.7415% → 43.3762%**; macro seed recall
improves **32.3457% → 36.7873%**. These are descriptive reconstruction results,
not independent source gold, musical relevance judgments, or a parity score.

The improvement has a tradeoff: Recall@1 falls **14.3033% → 14.0209%** and
MRR@10 falls **22.8147% → 22.6612%**. The candidate improves discovery at ten
results and small-genre coverage; it does not improve every ranking metric.

## Construction and selection

[`direct_custody_reconstruction.py`](../../src/opennoise/ml/direct_custody_reconstruction.py)
verifies the compressed direct custody with the existing portable receipt reader.
It uses the same bounded sparse observation index as the earlier neighborhood
experiment. At most 1,000 genres, 1,000,000 artists, degree 256, and 5,000,000
pair visits are permitted. Dense work is restricted to the genre-square matrix;
artist evaluation runs in blocks of 512. No artist-square similarity matrix is
constructed.

For observed binary artist-by-genre matrix `X`, the linear reconstruction fit is:

```
P = inverse(X.T @ X + lambda * I)
B[i,j] = -P[i,j] / P[j,j]
B[j,j] = 0
```

This is the closed-form zero-diagonal constrained ridge reconstruction solution.
The selected arm uses `lambda=100` and divides each target column by the square
root of that target's training artist count. Negative coefficients remain in
scoring and may cancel redundant positive evidence. Absolute coefficients below
`1e-12` are zeroed to suppress numerical residue. Only positive total scores are
ranked; directly observed training genres are excluded. Equal scores resolve by
canonical seed ID. Unobserved source entries participate in a binary matrix
reconstruction surrogate; they are **not verified negative membership labels**.

The fixed thirteen-arm comparison includes the earlier specificity-transfer
baseline, conditional-probability transfer with shrinkage 5 or 50, unscaled ridge
with regularization 1, 10, 100, or 1,000, and ridge 10/100 with target-frequency
exponents 0.1, 0.25, or 0.5. All counts, norms, coefficients, and weighting use only
the current training partition.

The per-seed deterministic split sorts by SHA256 of revision, partition name,
seed ID, and artist MBID separated by NUL; it withholds the lowest fifth while
retaining four training observations. Inner and outer splits have distinct
partition salts. The resulting partitions contain 248,460 inner-training,
61,769 validation, 310,229 outer-training, and 77,206 test observations.

Selection first requires validation macro seed Recall@10 at least as high as
the prior baseline, then maximizes validation micro Recall@10, MRR@10, and finally
declared arm order. The chosen arm is frozen before the test is scored. Only the
chosen arm and the prior baseline are evaluated on that test.

| Arm | Validation micro Recall@10 | Validation macro Recall@10 |
| --- | ---: | ---: |
| Specificity transfer | 37.88% | 28.08% |
| Conditional, shrinkage 5 | 41.51% | 17.43% |
| Conditional, shrinkage 50 | 40.94% | 16.29% |
| Ridge 1 | 42.25% | 22.36% |
| Ridge 10 | 42.31% | 22.29% |
| Ridge 100 | 42.32% | 21.22% |
| Ridge 1,000 | 41.58% | 18.23% |
| Ridge 10, frequency exponent 0.1 | 42.29% | 24.52% |
| Ridge 10, frequency exponent 0.25 | 41.57% | 27.13% |
| Ridge 10, frequency exponent 0.5 | 37.62% | 31.27% |
| Ridge 100, frequency exponent 0.1 | 42.35% | 23.41% |
| Ridge 100, frequency exponent 0.25 | 41.79% | 26.63% |
| **Ridge 100, frequency exponent 0.5; selected** | **38.05%** | **31.36%** |

## Test coverage and limits

| Outer-training support | Seeds | Test positives | Prior hits@10 | Selected hits@10 |
| --- | ---: | ---: | ---: | ---: |
| 4–20 observations | 123 | 323 | 63 | 93 |
| 21–100 observations | 245 | 3,033 | 900 | 1,071 |
| Over 100 observations | 319 | 73,850 | 32,036 | 32,325 |

All **26,469 positives on artists without remaining training observations** stay
in the denominator and abstain. The source-only model cannot infer a profile for
these cold artists. Positive-score target coverage rises from 44,329 to 49,034.
Ten source seeds lack enough observations for a test split, leaving 687 evaluated
seeds. The smallest stratum has only 323 positives; its improvement does not
establish reliable niche quality across a wider catalog.

An exploratory v1 run selected unscaled ridge 100 using micro recall alone. Its
separately salted test improved micro Recall@10 42.5653% → 47.4678%, but reduced
macro recall 32.6797% → 24.6981% and small-support hits 66 → 34. That popularity
tradeoff motivated the v2 macro guardrail and calibration arms. The v1 artifacts
remain under `.cache/direct-custody-reconstruction/run-20260930-v1/`; they are not
the selected candidate. The v2 arms and guardrail were fixed before v2 test
scoring, but both experiments reuse the same source corpus. Changing the split
salt does not create an independent external confirmation.

This work cannot claim full Every Noise parity. The portable custody supplies
697 observed seeds; there is no evidence here that the remaining historical
name universe has source memberships. The retained portable credit catalog is
metadata-only (87 projections), and the native genre dictionary supplies labels,
not artist memberships. Neither can supply missing training labels. Wider
source-grounded coverage requires additional real artist observations with
retained provenance. Artist-to-artist relevance, genre-to-artist candidate ranking,
and map geometry remain unevaluated by this artist-to-genre recall experiment.

## Local artifacts and queries

The completed reproducible fit is
`.cache/direct-custody-reconstruction/run-20260930-final2/`:

- `observations.npz` and `identities.json`: full direct source matrix and exact IDs.
- `transfer.npy`: full signed genre coefficient matrix, including 271,182 negative
  coefficients; its bytes are bound by the report.
- `model.json`: 697 source genres, 683 peer-supported genres, 14 peer abstentions,
  10,517 bounded display edges, and 13,900 explicitly inferred artist proposals.
- `report.json`: all validation arms, selected/baseline test metrics, source and
  implementation hashes, split policy, and all four output byte bindings.

The model byte SHA-256 is
`79b8563fb5c5201a5e443e4944c25367d451e0bacafb35244792cc4e45c8ef6c`.
The report logical SHA-256 is
`b01857358199c405ed7aefda8b5012ea38dac681791c37aaecccf55ca3661e84`.
A final replay reproduced every v2 validation and test metric; its recorded
implementation hash matches the current source file.

Display peers retain at least two shared direct artists and at most twenty peers
per target. They are a bounded explanation view, **not** the full scoring matrix.
Artist proposals include every direct positive contribution in `via_seed_ids`
and every negative contribution in `opposing_seed_ids`. Neither list is restricted
to the displayed twenty peers. `verify_artist_proposal` replays both lists and
the signed score against the full matrix, rejecting altered explanations and
proposals that duplicate an existing direct observation. All 13,900 real-corpus
proposals replayed successfully through this verifier in 0.69 seconds; identity
lookup uses binary search over the canonical sorted ID tuples.

After the existing `poe sync` setup:

```sh
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/build_direct_custody_reconstruction.py \
  --output .cache/direct-custody-reconstruction/replay
```

Destinations must be new and inside the checkout's `.cache`. Inputs are local;
no network acquisition is required. `load_reconstruction(directory)` verifies
all artifact hashes and returns the observation index and signed matrix.
`predict_artist_genres(index, transfer, artist_mbid)` returns up to ten inferred
genres with signed per-seed weights. Unknown artists abstain. These outputs have
no public export, serving, or membership-promotion authorization.

Eleven focused tests cover split isolation, constrained optimization, full cold
positive accounting, leakage rejection, validation-only selection, the macro
eligibility guardrail, signed explanation verification, disconnected-source
abstentions, deterministic ties, coefficient tampering, orchestration refits,
and forbidden public destinations. Focused tests, Ruff, and type checks pass.
