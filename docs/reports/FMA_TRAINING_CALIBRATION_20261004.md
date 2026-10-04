# FMA calibration within original training components

The stricter FMA training-only selection requirement is implementable with the
retained licensed native metadata and numeric features. The historical
validation-component protocol remains a valid, separately named protocol; it did
not satisfy that stricter requirement. Its outputs and the negative cosine result
are preserved. This change does not establish musical confidence or complete the
broader data/model milestone.

The [declaration](../../data/recipes/fma-training-memberships-v1/declaration.json)
was frozen before outcomes, SHA-256
`5697578e85b92f355020edb56b9351583c9e10208f8fe99ec3782d930801ef09`.
Original native artist/album/exact-full-feature-duplicate components and outer
folds remain unchanged. A fixed SHA-256 hash assigns original training components
to inner fit or calibration (modulo five; bucket zero calibrates). No labels,
scores, or component sizes enter assignment. No reshuffling or rebalancing occurs.

Only inner-fit queries determine Gaussian normalization, class moments,
prevalence and support. The fixed historical Gaussian hyperparameters are reused;
there is no refit after calibration. Thresholds use the worst positive rank per
inner-calibration component, the predeclared 80% order statistic, a minimum of 20
positive components, and abstention for unsupported positive tails. The output
cap remains 20 labels. Rank percentiles describe observed source positives, not
probabilities of musical membership. Neither an 80% target nor the bounded set
establishes a coverage guarantee under dataset shift or incomplete labels.

| Role | Queries | Components | Source positives | Missing features | Unlabelled |
| --- | ---: | ---: | ---: | ---: | ---: |
| Inner fit | 83,658 | 4,679 | 203,461 | 2,399 | 2,102 |
| Inner calibration | 11,295 | 1,204 | 23,980 | 284 | 174 |
| Previously inspected validation diagnostic | 7,332 | 753 | 16,668 | 170 | 79 |
| Previously inspected test diagnostic | 6,468 | 703 | 14,402 | 182 | 99 |

All 974 unresolved-artist queries (2,075 positives) remain recorded as excluded
from fitting/calibration/evaluation. The full 109,727-track ledger is retained.
The largest inner-fit component contains 39,312 known-artist queries; component
hashing does not yield an 80/20 split by track count. No imbalance correction was
chosen after observing this result.

The fitted model supports 158 labels. Only 32 of the 164 labels support calibrated
thresholds: 128 abstain for insufficient positive-component support and four for
an unsupported positive-rank tail. Validation/test bounded source-positive recall
is 9,400/16,668 (56.40%) and 8,089/14,402 (56.17%), with mean set sizes 19.51 and
19.42. All rare-label membership positives are unrecovered (0/472 validation;
0/289 test, plus 0/14 test positives below five fit observations). These are
previously inspected diagnostics, not fresh confirmation or optimization targets.
Inner-calibration metrics reuse the threshold-fitting labels and are labelled
accordingly. Missing-feature, out-of-support and unlabelled queries remain in the
reported denominators. Precision and musical calibration remain unavailable.

The new suggestion path conservatively checks bounded-set rank stability against
all excluded labels that could enter after a two-rank perturbation, including
labels currently outside their threshold. The old suggestion path is unchanged.
A conservative sufficient stability condition is not a musical confidence score.

Run the retained-input path with the existing 1 GB address-space cap, 120-second
CPU/wall cap, one BLAS thread, and 100 MB output cap:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src:. timeout 120s \
  .venv/bin/python scripts/calibrate_fma_training_memberships.py \
  --metadata /workspace/fma-fresh-20261004/metadata \
  --features /workspace/fma-fresh-20261004/feature-source/projection \
  --native-declaration /workspace/fma-fresh-20261004/declaration.json \
  --baseline /workspace/fma-fresh-20261004/model \
  --declaration data/recipes/fma-training-memberships-v1/declaration.json \
  --output /workspace/fma-training-memberships-replay
```

The final run used 8.00 seconds and 346,689,536 bytes peak RSS. A single exact
producer reproduction after a static-type annotation correction preserved every
model, threshold, rank, membership, ledger and seal byte; the first run is retained.
Final evaluation SHA-256:
`67228714920a686a2893e778c01406c8f5ee01344d389b1e4a00e414a32b8781`.
Model and threshold hashes were saved before outer scoring and rechecked after it.
Eight regression tests cover role assignment, forbidden calibration cohorts,
component support, missing-score abstention, non-fit feature/label perturbations,
outer-fold invariance, query denominators, potential-entrant stability, and the
runner's exact fit mask/single fit/pre-diagnostic seal. Existing membership replay
tests preserve the historical protocol.

Independent direct-native replay passed: all 109,727 role assignments, the 81,259
finite fit rows and Gaussian statistics, all 164 thresholds, and all 25,095 full
rank/membership rows and metrics (including bootstrap intervals) match. The audit
uses independent role, fitting, scoring, threshold and metric calculations rather
than importing producer implementations. It used 26.43 seconds and 462 MB peak RSS.
The saved seal is checked by hash; chronology is established by reviewed runner
control flow and the runner regression test, not by hashes alone.
