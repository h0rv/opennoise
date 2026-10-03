# Comparable acoustic metadata distances

`opennoise.analysis.acoustic_support` adds explicit evidence and numeric range
gates around the existing standardized RMS distance. It consumes numeric
`ArtistDescriptors` and observed recording counts. It does not read names,
historical genres, cultural memberships or source-specific tag packs.

The existing baseline ranks an arbitrarily extreme finite query if it shares
three descriptors with a candidate. It also permits candidates with different
shared descriptor sets to compete. That produces a nearest result without
establishing comparable evidence or support in the fitted population.

The new frame fits descriptor centers and scales only on the supplied training
artists. Default rules require two recording observations per feature, three
training artists per feature and at least three varying features. Constant and
undersupported features are omitted. Every accepted query and candidate must
have the entire fixed feature frame. Values more than six training standard
deviations from their descriptor centers cause explicit abstention. The rules
are declared configuration, not thresholds selected using held-out labels.

Use `fit_acoustic_support(training, features)` followed by
`supported_sonic_neighbors(query, candidates, frame)`. The result retains the
query and recording count, the exact feature dimensions, accepted neighbors and
candidate abstention reasons. Sparse queries, missing dimensions, unsupported
training populations and extreme values do not receive invented neighbors.
Accepted distances reuse `acoustic_representation.sonic_neighbors`; this does
not introduce a second distance implementation or change existing products.

`AcousticSupportPolicy` exposes the recording/population/feature budgets and
range rule. Six standard deviations is a conservative numerical rule. It is not
a calibrated probability of population novelty or musical relevance, especially
for the small, selected example population. Equal descriptor weighting retains
the baseline's correlated-feature and duration-dependent descriptor limitations.
Two recordings are still inadequate to summarize a diverse artist's catalog.

## Portable held-out replay

The existing `data/examples/acoustic-descriptors` pack is a receipt-bound numeric
artist projection. The replay checks its hash and declared source/license
bindings; it does not contain native AcousticBrainz recording bytes. A source
receipt hash alone cannot prove native feature custody or exact recording
credits. That native-custody gap remains open.

Run a fresh offline evaluation:

```sh
.venv/bin/python scripts/evaluate_acoustic_support.py \
  --output .cache/acoustic-support-new-report.json
```

The evaluator holds each query artist out of all fitting, keeps all ten queries
in denominators and checks deterministic support rankings when input order is
reversed. It verifies that every accepted comparison uses the same complete
feature set within its query. Reordering the baseline's feature declaration may
change the order of its explanatory fields; the new support frame uses canonical
feature order. No independent musical relevance judgments are available.

The committed report is
[`acoustic_support_projection_20261002.json`](../reports/acoustic_support_projection_20261002.json).
The baseline ranks ten queries and 90 pairs. The support frame ranks six queries
and 30 pairs; four artists with one recording explicitly abstain. All accepted
comparisons use fourteen dimensions. This improves missingness and support
behavior; it does not demonstrate better recommendation quality. Report SHA-256:
`fc2c1d77b605a3ff10f1e6748bb6624c2041a2eca3aaa518a823d8659ca72809`.

Validation includes an extreme held-out fixture that the baseline ranks and the
new frame abstains on, a partial-dimension candidate excluded from the comparison,
unit-change and ordering invariance, constant/sparse feature handling, corrupt
count/nonfinite/duplicate rejection, and actual portable projection replay with
matching-hash supplementary-field rejection. Nine new tests and four existing
representation tests pass; Ruff and ty pass. Exact report replay uses 199,922
output bytes, approximately 18 MB peak RSS and 0.006 seconds in this environment.

No audio, network acquisition, native-source replay, genre membership inference,
Every Noise acoustic-axis equivalence, new product promotion or deployment is
claimed.
