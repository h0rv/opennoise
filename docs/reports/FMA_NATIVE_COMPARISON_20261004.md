# Fresh native FMA replay and fixed cosine comparison

The approved source host now works in the fresh environment. Ten serial requests
captured 304,921,396 bytes of official metadata and numeric features, with no
audio, EchoNest or pickle. Native CRC, observed SHA256, member/range checks and
independent full source replay passed. The full archive checksum is unverified.
The [fresh capture evidence](../foundation/evidence/fma-native-recapture-20261004.json)
is distinct from the historical saved-rank replay. It reproduces the fixed
Gaussian result using newly captured native inputs; it is not a new unseen test.

The new, separately [frozen cosine arm](../checkpoints/FMA_COSINE_COMPARISON_DECLARATION_20261004.json)
compares directional positive-class means with the Gaussian's variance and
prevalence scoring. It does **not** replace the Gaussian baseline: overall
validation recall and first-hit rank are worse. No tuning, model selection,
new source download, or split change occurred. Both earlier validation and test
results were available before this experiment; test comparisons are diagnostics.

| Fold / arm | Micro R@10 | Macro R@10 | First-positive MRR | Rare R@10 |
| --- | ---: | ---: | ---: | ---: |
| Validation / cosine | 23.60% | 24.20% | 0.18144 | 14.75% |
| Validation / Gaussian | 37.05% | 25.33% | 0.30261 | 4.64% |
| Validation / popularity | 36.33% | 7.19% | 0.32789 | 0.00% |
| Test diagnostic / cosine | 24.47% | 25.02% | 0.17251 | 16.73% |
| Test diagnostic / Gaussian | 39.59% | 27.40% | 0.31296 | 4.94% |
| Test diagnostic / popularity | 36.63% | 7.35% | 0.31911 | 0.00% |

Cosine improves rare-label recovery but loses substantially overall. Rare means
at most 100 source-positive training tracks; the test rare denominator is only
263 positives. No significance or musical-quality claim follows from this table.
The [machine-readable comparison](../foundation/evidence/fma-native-cosine-comparison-20261004.json)
retains all arms, Recall@5, support, abstentions, component sizes and bindings.

## Fit, coverage and leakage boundaries

Cosine uses the same 44 training-standardized mean descriptors and 92,270 finite
training rows as Gaussian. Positive class means are recovered from the verified
Gaussian sufficient statistics (`linear / (-2 * quadratic)`) and normalized to
unit vectors. Query direction is scored against these vectors without variance
or prevalence terms. The independent audit recomputes class means directly from
the native training projection rather than using that recovery formula.

At least five finite-feature positive training rows are required. Norms at or
below `1e-12` are unsupported. There are 158 active prototypes and zero
support-qualified zero-norm prototypes. Source-positive support and finite-feature
support remain separate in the full evaluation. No query-range filter is applied
to training. Missing/nonfinite descriptors, absolute standardized values above
12, and zero query norms abstain; ties use ascending native label ID.

The fixed v2 split groups native artist/known-album components and exact complete
native-feature duplicate groups. All 109,727 saved fold rows are compared with
fresh native components before scoring. The whole-track audit now includes the
retained duplicate custody, closing the earlier ledger-only evidence gap. This
still cannot resolve unknown recording or performer aliases.

The 7,410 components include one of 39,750 tracks. Realized known-artist folds are
94,953 training, 7,332 validation and 6,468 test; nominal 80/10/10 hashing does not
produce balanced folds. There are 974 unresolved-artist tracks excluded from
fit/evaluation. The raw corpus has 3,153 missing-feature tracks and 2,609 missing
target rows; the complete 164-label vocabulary is retained, with 162 observed.

Validation retains 7,332 queries, 7,253 labeled queries and 16,668 positives; test
retains 6,468 queries, 6,369 labeled queries and 14,402 positives. Both acoustic
arms abstain on 170 missing-feature and three range failures in validation, and
182 missing-feature and one range failure in test. Every target stays in the
recall denominator. MRR averages over labeled queries; macro recall averages over
labels with held-out positives. Missing annotations are unknown, not negatives.
Popularity ranks all training-observed labels by source-positive training count;
constant ranks the same supported vocabulary by native ID. Neither comparator
requires query features. Source recovery does not measure precision, calibrated
musical membership, sonic relevance, or factual artist genres.

## Reproduction and review

The retained native-input Library bundle is `libfile_c567548f92ec8191864e35995e2ea5d7`,
332,185,600 bytes, SHA256
`1daeb6dd035b15a78e8359728aa3cef207c2434dea157acb678ae66b84facc30`.
The separate comparison Library bundle is `libfile_70d07179f91c81919be9a54809bf3255`,
5,985,190 bytes, SHA256
`3cb4ac5c5c1d0da2ac6553d613283e46c806da019dbf7fdb40f4c41d3ed8c4b8`.
It preserves both runs, independent audit scripts/results, review, model/rank
artifacts and full check logs. `model-final` is the reviewed final run.
Use that capture's `metadata`, `feature-source/projection`, `declaration.json`
and `model` directories after extraction. Run from the repository's Python 3.13
environment after `poe sync`, with a fresh output path:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src:. timeout 120s \
  .venv/bin/python scripts/compare_fma_cosine_baseline.py \
  --metadata "$FMA_ROOT/metadata" \
  --features "$FMA_ROOT/feature-source/projection" \
  --native-declaration "$FMA_ROOT/declaration.json" \
  --baseline "$FMA_ROOT/model" \
  --declaration docs/checkpoints/FMA_COSINE_COMPARISON_DECLARATION_20261004.json \
  --output "$NEW_OUTPUT"
```

The runner verifies native hashes, baseline artifacts, exact query identities,
folds and metric denominators; it saves a reusable numeric model, full rankings,
code snapshots and hashes. Process guards remain 1 GB address space, 120 seconds
CPU and 100 MB complete outputs; the invocation adds a 120-second wall limit.
Final execution used 121,831,424 bytes peak RSS and 2.434 seconds. The first run
and audit remain preserved; review corrected a report-byte budget omission,
then a fresh final run retained the same protocol and results.

The [independent engineering review](../foundation/evidence/fma-cosine-independent-review-20261004.json)
and [direct-native formula replay](../foundation/evidence/fma-cosine-independent-replay-20261004.json)
bind this final output; the reviewer is a separate AI engineering agent, not a
human musical reviewer. Seven focused tests cover held-out perturbations, numerical
abstention, inactive/zero prototypes, deterministic ties, overflow rejection and
saved-model roundtrip. Full source checks passed locally (1,829 Python tests,
36 skips; 43 Node passes, nine skips); skipped optional browser/artifact tests do
not certify a public export. No website or deployment changes are included.

This advances licensed ingestion, reusable representations and leak-safe
source-recovery evaluation in `reproducible-data-and-model-research-v1`.
Calibration of musical confidence, independent listener judgments, alias-complete
identity coverage and broader cultural relevance remain unmet. Additional test-
driven tuning cannot close them. No historical acceptance gate is promoted.
