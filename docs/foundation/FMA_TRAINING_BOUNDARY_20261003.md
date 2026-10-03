# FMA training boundary checks, 2026-10-03

The reusable FMA fitter now rejects non-boolean or misaligned training masks
before indexing observations. A numeric 0/1 mask previously survived bitwise
intersection with finite-feature flags and became NumPy integer row indices.
In a 14-row reproduction with nominally held-out row 0, changing that row from
zero to 10,000 moved both fitted centers from 0.7142857142857143 to
2857.8571428571427. The same change cannot affect a valid boolean-mask fit.
Tests cover signed/unsigned integer, floating and object masks, scalar and
two-dimensional masks, row-count mismatch and malformed feature dimensions.

The historical native component splitter also omitted tracks with no artist ID
from album and duplicate connectivity. A known artist's track on album 10,
a missing-artist track on album 10, and a different artist's track that is an
exact duplicate of the missing-artist track must form one component. The old
algorithm split artists 30 and 5 into training and validation respectively.

A separate whole-track connectivity audit now rejects such a v2 assignment
before fitting. It retains missing-artist vertices, all supplied album edges
and overlapping duplicate groups. It does not invent artist identities,
connect missing values as a shared sentinel, or silently remove difficult
tracks. Safe historical assignments retain their existing component IDs and
fold hash. The audit does not replace verification of the supplied identities.

This change supplies fail-closed engineering checks, not a new empirical model
result. Published v2 model artifacts and reported scores remain historical.
Whether the preserved full native corpus contains this bridge requires source
replay; this synthetic counterexample does not establish its prevalence there.
The hash-verified saved fold ledger contains 109,727 tracks and zero missing
artist IDs; its supplied artist/album edges pass the new audit. The retained
[ledger check](evidence/fma-boundary-ledger-audit-20261003.json) took 0.111 seconds
with process peak RSS of 156,200,960 bytes, including imports and ledger loading.
The saved pack lacks duplicate-group custody, so this is not full native replay
and does not certify duplicate isolation. No saved model scores were recomputed.
If the audit rejects the native corpus, a separately versioned split and model
run must be frozen and replayed before reporting replacement scores. No musical
membership probabilities or fresh confirmation are established here.
