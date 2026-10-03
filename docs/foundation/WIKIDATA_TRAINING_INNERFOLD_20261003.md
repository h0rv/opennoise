# Wikidata training-only innerfold diagnostic — 2026-10-03

The selected conditional source rule recovered **73.15%** of masked observed
labels at rank 10, compared with **60.92%** for the unconditional training prior.
These are unweighted means across five innerfolds of the **original training
artists**. The increase is 12.23 percentage points on this training-only selection
task. It does not establish musical membership, calibrated confidence, or new
confirmation performance.

This diagnostic was designed after the earlier source-completion and prior
results had been inspected. It used a new innerfold seed and a newly frozen
parameter grid. It did not decode calibration or confirmation labels, evaluate
those outer folds, refit the selected rule on all training data, or promote a
model. The original source packs, algorithms, and observations remain preserved.

## Inputs and method

The input was the sealed source pack
`/dev/shm/opennoise-wikidata-artist-completion-v2`, specifically
`artist-fold-targets.jsonl.zst`. Its closed inventory was verified against an
explicit caller-supplied receipt hash. The implementation, policy, and pinned
input hashes were saved before any training label parsing or fit.

The compressed reader necessarily held each line's bytes. It decoded only the
top-level canonical artist UUID and split first, independently replayed the
original UUID-based outer assignment, and discarded non-training lines before
decoding label fields. Route counts were 5,976 training, 2,025 calibration, and
1,991 confirmation rows; the last two counts are routing metadata only.

[Implementation](../../src/opennoise/ml/wikidata_training_experiment.py) and
[CLI](../../scripts/experiment_wikidata_training_memberships.py) define the
experiment. Five innerfolds use
`SHA256(opennoise-training-only-innerfold-20261003-v1:artist UUID) modulo 5`.
Each held-out training artist keeps its original deterministic masked target.
Only the other four folds determine artist support, co-observation counts, and
the candidate vocabulary, which requires five inner-training artists per label.
Observed seed labels are excluded from candidates.

The conditional score is
`(pair_count + alpha * innertrain_prior) / (seed_support + alpha)`.
The grid includes alpha 1, 10, and 100; maximum or mean aggregation over supported
seeds; and conditional blend weights 0, 0.25, 0.5, 0.75, and 1, alongside the
unconditional prior: 31 arms in total, including duplicate zero-weight controls.
Empty or entirely unsupported seeds use the same unconditional prior. Selection
uses the highest unweighted mean fold R@10, with the frozen arm order breaking
ties and the prior first. Candidate ties use exact QID lexical order.

## Actual results

The selected arm was `conditional_a1_mean_w1`: alpha 1, mean seed aggregation,
and no prior blend beyond the conditional smoothing term.

| Innerfold | Held-out rows | Fit artists | Vocabulary | Prior R@10 | Selected R@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0 | 1,217 | 4,759 | 206 | 58.09% | 71.49% |
| 1 | 1,178 | 4,798 | 204 | 61.54% | 72.67% |
| 2 | 1,165 | 4,811 | 204 | 59.23% | 72.36% |
| 3 | 1,208 | 4,768 | 207 | 63.08% | 73.76% |
| 4 | 1,208 | 4,768 | 210 | 62.67% | 75.50% |
| Unweighted mean | 5,976 total | — | — | **60.92%** | **73.15%** |

Pooling all training queries gives prior/selected R@1 of 16.43%/24.90%, R@5 of
51.99%/64.54%, and R@10 of 60.93%/73.16%. These pooled values differ slightly
from the unweighted fold means used for selection.

The following strata use pooled query denominators. Strata overlap.

| Source stratum | Queries | Prior R@10 | Selected R@10 |
| --- | ---: | ---: | ---: |
| Supported observed seed | 2,095 | 31.12% | 66.01% |
| No observed seed; one observed positive | 3,785 | 77.75% | 77.75% |
| Observed seeds, none supported | 96 | 47.92% | 47.92% |
| Rare target: 1–10 inner-training artists | 458 | 0.00% | 16.81% |
| Common target: over 10 inner-training artists | 5,419 | 67.19% | 79.26% |
| Target outside inner-training vocabulary | 303 | 0.00% | 0.00% |
| Target unseen in inner-training artists | 99 | 0.00% | 0.00% |

All 5,976 input training rows had at least one observed source label. Actual
missing-target queries were therefore zero. The implementation retains such
queries and treats absent source targets as unknown, rather than fabricating
negative labels. The 3,785 one-positive rows dominate the no-seed prior results;
the conditional improvement occurs among artists with supported observed seeds.
Unseen and excluded targets remain in the positive denominators and cannot be
recovered from the fitted vocabulary.

## Interpretation and replay

This is a bounded, source-selected Wikidata/MusicBrainz roster, not a
representative sample of artists or genres. Exact identity resolves which artist
a statement belongs to; it does not validate the statement musically. Source
label omissions, uneven label frequency, artist coverage, and the one-target
masking protocol limit interpretation. Choosing among 31 arms on these same
innerfolds makes the selected result a training model-selection diagnostic.
Independent source recovery or listener assessment would answer different
questions; neither was supplied by this experiment.

The one authorized run completed from 05:34:44 to 05:35:00 UTC with return code
zero. Its Linux `VmHWM` peak was 28,168,192 bytes (26.86 MiB), below the 35 MiB
bound. The complete sealed output was 1,859,872 bytes, below the 5 MB bound.
It preserves all 5,976 rows and all 185,256 rankings across the 31 arms, together
with every fold and stratum metric. Source and output inventories verified after
the run.

A separate root review agent replayed all 185,256 rankings, fold assignments,
and stratum metrics and reported exact agreement, with peak RSS 25,194,496 bytes.
That replay checks reproducibility of the training experiment; it adds no outer
confirmation or musical-validity evidence.

## Public evidence and immutable bindings

[Public report](evidence/wikidata-training-innerfold-20261003-report.json) contains
every actual sealed-report value in a lossless shared-metric encoding. In
`report.arms` and each `report.folds[*].arms`, replace each stratum's integer with
`metric_records[index]` to reconstruct the original report JSON. Reconstruction
was checked equal to the sealed original. The original 695,001-byte report
remains untouched. The public report is 194,903 bytes; the
[execution proof](evidence/wikidata-training-innerfold-20261003-run.json) is an
862-byte verbatim copy, preserving exact argv, times, return code, and resource
proof. Neither public file contains artist names, query rankings, private model
keys, or human assignments.

The complete local output is
`/dev/shm/opennoise-wikidata-training-experiment-20261003-v1`; its sibling
`-run.json` holds the execution proof. SHA256 bindings are:

| Artifact | SHA256 |
| --- | --- |
| Expected original source receipt | `5571f22953cfdc0c4003d855139bb4bbf1aadd97cbf2d3428495062eacaa0b6a` |
| Input `artist-fold-targets.jsonl.zst` | `5f1754dd1717b886c06360946745a00e385f8aa19673ca13ff171cb0d133befd` |
| Sealed output receipt | `399812f1e129272472d65312c873a150249fd5da99d606d903ef4d65a094c273` |
| Frozen policy | `1cd6f50ba438a379b735601b3a66176d1dc875fca1e50d7baff907b7d9874c63` |
| Frozen implementation | `d1653f75eb1ca055b589da467cd440b427487811cdf75bb4a010abac95e3d830` |
| Sealed full report | `fdd1032190b85ae80955e933ff195c68571bcf775b45cbf3a6f8e72c3831089b` |
| Sealed all-query rankings | `68a520d47fbf2419fc82703e8a3183072f422d69573729124715cc42c0de5178` |
| Original and public execution proof | `abb6350cbd6cead811e8f3d16865e2c4b882366d7c39df2729bf88755c271ec5` |
| Public lossless report | `2f3f0aa56a71910b6eb8ac5f54e857bb5ebe1ecf43630bb0b564e08635185e16` |
| Independent replay JSON | `1c88be2f12e154f543f246e59b74c46da6f9d73021dcaf513428b36e463ff602` |

The independent replay artifact is
`/dev/shm/opennoise-wikidata-training-innerfold-independent-audit-20261003-v1.json`.
These are CC0 source-observation metrics and reproducibility evidence, without a
model promotion or acceptance-dossier gate claim.
