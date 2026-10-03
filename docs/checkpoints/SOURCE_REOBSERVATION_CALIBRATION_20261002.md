# Source reobservation calibration, 2026-10-02

The frozen overlap scorer now exposes source detection rates and a bounded
abstention layer. On a deterministic 25,000-artist research cohort, held-source
Brier loss improves from **0.0275435 to 0.0248312**, a 9.85% relative reduction
against a constant calibration-capture baseline. This calibrates the event
“a nominated value is observed in the held source component.” It is not a
probability of musical genre membership, independent musical relevance, or
Every Noise semantic parity.

The fixed detection-rate threshold of 0.1 removes most suggestions and loses
source recall. It remains an optional research tool; there is no default-model,
UI, public export, or deployment promotion. No independent contextual evidence
was added, and true cold-artist recovery remains unresolved.

## Source permission and scope

The exact input is the preserved
`/workspace/opennoise/.cache/microgenre-features-primary-v4/artist-features.jsonl`,
SHA-256 `2b6179b4c969588f1268c9837b410c9da7b16d54c094850eb13ba00514b6f252`.
Its adjacent feature-projection receipt has SHA-256
`281a0cdcf87498bad50f6e2fe9b145cf0e010c1ed7c3b48a832ae0b8a094f6d7` and explicitly
sets `research_model_input_authorized=true`,
`research_model_scope=local_noncommercial_research`, and
`public_export_authorized=false`. It requires MusicBrainz contributor
attribution, noncommercial research, share alike, and no public export.

The evaluator requires that exact projection authorization and feature hash
before creating output. A license string alone is insufficient. A same-input
`training_authorized=false` flag rejects fitting. Its declaration records the
permission receipt path/hash, scope, obligations, and authorization basis.
The original direct-claim custody receipt and upstream artifacts are unchanged;
this does not grant them training, serving, publication, or membership authority.
The referenced bulk-v2 projection receipt
`079a6217b32fd651d465fe9234cb523d950e558c2f3137a66d0a05ea4fd39c5e` also explicitly
authorizes local noncommercial research inputs. Core identity CC0 licensing does
not cover this optional CC-BY-NC-SA-3.0 tag/genre pack or its derived artifacts.

## Frozen construction

Artist identities are selected by the 25,000 smallest SHA-256 cohort keys before
musical evidence is examined. The new cohort salt is
`bounded-source-reobservation-cohort-fixed-20261002-v1`. This budgeted cohort has
less training support than the earlier full-source experiment; their recall
percentages are not directly comparable.

Canonical artist/value facets and globally shared release-group evidence form
whole connected components. The salt
`source-reobservation-components-fixed-20261002-v1` assigns hashed components
60% to training, 20% to calibration and 20% to test. Component sizes can change
observed proportions. Both calibration and test values are removed from every
facet before vocabulary, support and association fitting. Their target sets have
zero overlap, and release components cannot cross roles. Calibration labels
never enter the base scorer. Test labels never enter either fit.

The base scorer remains rarity power 0.35, smoothing four, binary joint support
two and 128 outgoing neighbors. Its present-artist top-ten ordering is unchanged.
`score_batch` exposes raw association scores and explicitly abstains for missing
queries as well as primary-cold queries. No popularity guesses fill empty rows.

Score-bin lower edges are fixed at
`0, 0.125, 0.25, 0.5, 1, 2, 4, 8, 16`. Each bin stores the number of nominated
candidates and calibration-source detections. Rates shrink toward the overall
calibration-source detection rate with 32 prior nominations; bins with fewer
than 32 nominations abstain. The proposal threshold of 0.1 was fixed before the
first run and was not tuned on test outcomes. Non-detection is a missing
held-source observation, never a negative musical label.

## Results

There are 13,821 calibration positives and 13,847 test positives. All cold and
unseen positives remain in recall denominators.

| Measure | Frozen overlap | Fixed calibrated abstention |
| --- | ---: | ---: |
| Test positive hits | 5,028 / 13,847 | 1,243 / 13,847 |
| Recall@10 | 36.311% | 8.977% |
| Nominated suggestions | 177,373 | 3,937 |
| Held-source detections / suggestions | 2.835% | 31.572% |
| Artists with suggestions | 18,840 | 1,585 |
| Coverage of all 25,000 artists | 75.360% | 6.340% |
| Coverage of 19,658 primary-evidence-eligible artists | 95.839% | 8.063% |
| Primary-cold positive hits | 0 / 3,437 | 0 / 3,437 |
| Training-unseen value hits | 0 / 1,030 | 0 / 1,030 |

The detection fraction is precision for the declared source observation event,
not semantic precision. Unobserved suggestions may be musically appropriate,
and captured source tags can be poor musical descriptions. The threshold trades
substantial recall and artist coverage for more frequent source reobservation;
that tradeoff does not support default promotion.

| Raw score bin | Calibration nominations | Calibration detections | Test detections |
| --- | ---: | ---: | ---: |
| [0, 0.125) | 32,166 | 142 | 143 |
| [0.125, 0.25) | 55,144 | 519 | 508 |
| [0.25, 0.5) | 49,822 | 972 | 982 |
| [0.5, 1) | 26,414 | 1,239 | 1,230 |
| [1, 2) | 9,890 | 888 | 922 |
| [2, 4) | 2,265 | 476 | 464 |
| [4, 8) | 1,397 | 612 | 653 |
| [8, 16) | 275 | 145 | 126 |
| [16, infinity) | 0 | 0 | 0 |

Brier loss includes all 177,373 scored nominees; there are no thin-bin nominees
in this cohort. The constant comparison uses the calibration rate 0.0281497,
not a rate fitted to the test. Rates depend on this source capture, cohort and
withholding mechanism. They are not certified for a full-source refit, a new
source, or new artist populations. Bins share artists and source components;
these descriptive results carry no independent-bin significance claim.

## Artifacts and verification

The final local artifact is
`.cache/source-reobservation-bounded-20261002-v8/`, report SHA-256
`7328f99a424d36c7fb3e0d063452d51fb0df3d94aa8848f078008b112dce08cf`.
It contains frozen code, sparse associations, canonical vocabulary, calibration
counts with an explicit event/role contract, positive ranks, and scored nominees
with prediction rates, support, test detection and retained decisions. The
report binds fourteen files. `load_source_reobservation` requires an expected
file hash and exact source/scorer identities; a full-source refit cannot silently
inherit these rates. Proposals expose `native_fact=false`,
`genre_identity_validated=false`, and `semantic_membership_probability=null`.

A fresh refit/reranking reproduced the associations, vocabulary, calibration,
compressed ranks and compressed nominations byte for byte. The final run adds
source-permission binding and code-format fixes without changing those five
artifacts or any metric. Earlier immutable runs remain visible; none tuned the
method after observing test results.

Independent streaming arithmetic, without importing model scoring, verified all
fourteen file hashes, eight positive-rank metric cells, every recorded bin/rate
and retention decision, both Brier losses, detection fractions and artist
coverage. Audit: `.cache/source-reobservation-bounded-20261002-v8-audit.json`.
This arithmetic replay is not independent musical validation. Twelve targeted
tests cover score/rank consistency, missing/cold abstention, bin shrinkage,
thin-bin abstention, semantic-role rejection, exact file/source/scorer binding,
source permission rejection, and globally coupled three-role source isolation.
Targeted Ruff formatting/lint and type checks pass.

Profiled runs use at most 169 MiB resident memory and approximately eleven
seconds. Each final artifact is 3.9 MiB. All new runs combined remain below
30 MiB; no preserved source cache or recovery artifact was mutated or deleted.

Replay from this checkout, with the authorized optional local inputs available:

```sh
PYTHONPATH=src /workspace/opennoise/.venv/bin/python \
  -m scripts.evaluate_source_reobservation \
  --features /workspace/opennoise/.cache/microgenre-features-primary-v4/artist-features.jsonl \
  --source-receipt /workspace/opennoise/.cache/microgenre-features-primary-v4/receipt.json \
  --output .cache/source-reobservation-new-replay
```

The output must be fresh; existing outputs are never replaced. Missing source
files or authorization receipts block this full-corpus research replay. The
checked-in code and small fixtures require no optional tag pack. The prior rare
lens's full-corpus Recall@10 gain of 23.737% to 25.911% remains a separate source
recovery result, with unchanged cold/unseen and semantic relevance limitations.
