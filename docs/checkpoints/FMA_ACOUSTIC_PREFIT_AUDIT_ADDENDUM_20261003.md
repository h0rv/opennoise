# FMA pre-fit audit addendum

The original declaration remains unchanged (SHA256
`af972502f0f231dc1b0615a291f868d83c575c379195a687b82c52494f173fdc`).
Before fitting or inspecting metrics, the independent reviewer verified native
grouping, unresolved-artist graph bridges, training-only normalization and
source-positive Gaussian fitting, and retention of raw missing-feature queries.

The reviewer requested both comparators restrict rankings to labels observed in
source training metadata (`support > 0`). This resolves the ambiguity between a
training-only baseline and an external taxonomy prior; it changes neither model
parameters nor component assignments. Training-unseen positives are now also
reported separately from seen labels below the five-positive model threshold.
The source vocabulary still retains every native taxonomy ID, and every held-out
observed positive remains in recall denominators.

The run preserves compressed full acoustic genre rank lists and query abstention
reasons, raw native fold assignments, implementation source snapshots and hashes,
and the original declaration. Scores are uncalibrated native track source-label
recovery, with no artist-fact or public product promotion authorization. Nine
focused tests, Ruff and ty passed before the first fit, including a zero-training
low-ID comparator regression and unseen-positive denominator checks.
