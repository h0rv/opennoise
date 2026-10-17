# Training-only calibration of the human-vote metadata model

This local noncommercial experiment adds a probability-calibration stage to the
retained Jamendo genre/instrument classifier. It does not acquire recordings,
change FMA retrieval, or add a serving model. The existing outer folds have been
inspected: new outcomes are diagnostic, not independent confirmation.

The fixed protocol is `protocol.json`, SHA-256
`a4dfc1148e339cfb8980f50cddccb6b2e020645694bde42ec174af65e724f0d4`.
It retains all 11,565 nominated identities, their native artist/album components,
and the existing five outer folds. Exactly three recognized human votes define
eligibility; disagreements remain fractional targets and other rows remain in
the missingness ledger.

For each outer fold, a fixed hash partitions its training components into inner
fit and calibration roles. Only inner-fit labels determine the NB vocabulary,
likelihoods and prior. A two-parameter nondecreasing logistic calibration map
learns from the separate calibration components, with fixed regularization toward
the identity map. It never sees outer-query labels. The NB is not refitted after
calibration. Reusing old OOF predictions from other folds would leak current
outer-query labels through their training models; this workflow does not do so.

The matched controls are the **same inner-fit NB** without calibration and its
training human prior. The previous NB trained on all four outer training folds
is not a matched comparator. No privileged uploader mood tags enter any arm.

The primary score is component-equal individual-vote Brier, calibrated minus
uncalibrated: negative is better. Fractional log loss, track weighting, and
mean-target squared error are secondary. Calibration optimizes regularized log
loss and need not improve Brier. The irreducible empirical vote-disagreement
term `y*(1-y)` is reported separately, not called calibration error. Fixed
probability bins report descriptive reliability; weights sum to the number of
scored components, with each component having unit mass. Empty bins have null
means. These bins do not select thresholds or calibration parameters.

Identity fallback preserves original NB probabilities when calibration has too
few components or only one target class. An optimizer failure stops the stage;
it does not trigger another method. Eligible queries lacking an inner-fit model
remain unpredicted, with explicit counts; scores then describe the covered
subset rather than a silently complete cohort. All methods share availability.
No statistical-significance or population-confidence claim is made.

## Local reproduction

Use the retained original prepared identity seal and source files. This is a
new research stage; existing source, protocol, cohort and implementation guards
are reused unchanged. Absolute paths in a new seal are local execution inputs.

```sh
PYTHONPATH=src .venv/bin/python scripts/run_jamendo_calibration.py freeze \
  --prepared /workspace/opennoise-fresh-signal-20261017/prepared \
  --protocol data/recipes/jamendo-calibration-20261017/protocol.json \
  --output /tmp/jamendo-calibration-sealed
```

Independently review the new `seal.json`, including its source hashes, before
running the remaining stages. Supply its exact SHA-256 as `REVIEWED_SEAL_SHA`:

```sh
PYTHONPATH=src .venv/bin/python scripts/run_jamendo_calibration.py evaluate \
  --sealed /tmp/jamendo-calibration-sealed --seal-sha256 "$REVIEWED_SEAL_SHA" \
  --output /tmp/jamendo-calibration-results
PYTHONPATH=src .venv/bin/python scripts/run_jamendo_calibration.py replay \
  --sealed /tmp/jamendo-calibration-sealed --seal-sha256 "$REVIEWED_SEAL_SHA" \
  --output /tmp/jamendo-calibration-results
```

Each stage is limited to 120 CPU/wall seconds, 1,000,000,000 address-space bytes,
one BLAS thread, and 20,000,000 output bytes. The result includes complete local
predictions, five model/calibration records, descriptive evaluation, and a
closed hash inventory. Deterministic producer replay is separate from independent
numerical verification.

## Rights and interpretation

The retained MTG-Jamendo metadata and human annotations remain CC BY-NC-SA 4.0
and upstream noncommercial-research-only. Cite Bogdanov, Won, Tovstogan, Porter
and Serra (2019), *The MTG-Jamendo Dataset for Automatic Music Tagging*, and the
Music Classification Annotations documentation. Source attribution and acquisition
pins remain in the original `jamendo-human-mood-20261017` recipe.

Raw sources, per-track predictions and fitted research artifacts remain local;
they are not MIT product assets. Only code, protocol and restrained aggregate
research results belong in this recipe. No deployment is authorized. A
probability improvement for human happiness votes would not establish acoustic
similarity, artist style, recommendation usefulness, or EveryNoise parity.
