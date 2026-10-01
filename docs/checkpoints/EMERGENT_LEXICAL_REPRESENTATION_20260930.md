# Native tag text representation experiment

This isolated experiment asks whether lexical relationships among native musical
tag values produce more coherent parent communities than artist cooccurrence
alone. It uses no artist names, historical taxonomy labels or memberships,
audio, external pretrained model, or added dependency. The method cannot infer
semantic synonyms that lack textual similarity; lexical similarity can also be
musically misleading. Inferred community descriptors remain unvalidated.

## Prespecified representation

Before any predictive evaluation, version 1 fixes the following construction:

- Canonical musical values and IDF use the training artist-feature corpus only.
  Duplicate artist/release genre/tag facets collapse to the same musical value.
- Native value text uses Unicode word unigrams and word-boundary character
  3–5-grams. Each channel has sublinear term frequency, smoothed document IDF,
  and L2 normalization. Text affinity is 50% word cosine plus 50% character
  cosine. Without a shared word, character cosine must reach 0.6.
- Each value retains its top 20 positive lexical neighbors; the undirected
  union forms the text graph. This is a lexical representation, not a claim
  that a shared token establishes a musical relationship.
- The separate source cooccurrence graph retains its frozen degree correction,
  minimum two shared artists, cosine normalization, and mutual top-20 rule.
- Row-stochastic transitions combine 65% source cooccurrence and 35% lexical
  edges. Dangling graph rows retain their own value. Each musical profile keeps
  50% observed residual and adds 50% one-step diffusion, then normalizes.
- Structured area and time are excluded from the fitting representation. Exact
  canonical musical-profile groups remain indivisible. Source support and the
  frozen spherical model's fine-membership, differentiating-value, and ancestor
  closure gates remain in force. Lexical diffusion does not create additional
  observed musical values or let singleton profiles qualify for fine membership.

The representation is fitted through the unchanged v4 spherical hierarchy.
After fitting, labels and all published prediction/display centroids are
recomputed from the original observed source features of each core group.
Membership scores describe the lexical/source representation, while reported
`core_mean_cosine` measures original source profiles; the representation cosine
is retained separately. A lexical neighbor absent from a community's source
observations cannot become a published source centroid feature.

## Provenance and comparison

`src/opennoise/ml/emergent_lexical_topics.py` supplies
`fit_lexical_topics(data, settings, include_centroids=True)` with the evaluator's
existing model/membership contract. `scripts/build_emergent_lexical_topics.py`
writes complete assignment artifacts, sparse observed-source centroids, core
profile groups, and a byte-bound report. The report binds this module and both
frozen source-topic and feature-graph dependencies. It records learned lexical
vocabulary hashes and dimensions, exact mixture weights, graph edges, source
hash, and the explicit absence of external pretrained weights.

The first construction comparison uses pinned rich-v2, the same corpus as the
previous v4 and graph experiments. A richer primary-only v5 corpus comparison
is separate: changing the available source vocabulary is not an untouched test
of the earlier model. Any reuse of the fixed artist/value feature holdout is a
diagnostic, not a new independent test. Hyperparameters are not reselected from
its results. Existing failed models and reports remain immutable.

## First construction result on pinned rich-v2

The immutable `.cache/emergent-topics/lexical-v2-source-20260930-v1` has output
identity `45e26691d42759c10b8cb5af2b1d0fc90e64adcaf5d9e292f46550325966f15f`.
Its implementation SHA-256 is
`d2ef87a5ef76ea96850b5dd69583afa0c1482d36f61e2699af97ee96e03c7dc6`.
The text vocabulary contains 2,480 words and 19,690 character grams for 3,730
canonical source musical values. It contributes 24,921 undirected lexical
edges, alongside 8,821 source cooccurrence edges.

It produces 16 broad / 253 sub / 987 micro candidates. Artist coverage is
198,409 / 86,917 / 81,448. Original-source weighted core cosine is
0.463 / 0.788 / 0.880, versus spherical v4's 0.452 / 0.774 / 0.869. These are
training diagnostics on different partitions, not independent quality gains.
Some broad labels are more internally consistent, but a drum and bass /
country / regional mexicano group remains. The fixed broad budget and limited
representation therefore still fail to supply uniformly coherent parents.

Four Tet receives a folktronica / indie folk / indietronica fine candidate;
Aphex Twin receives an acid techno / techno / electro fine candidate. These
source-derived descriptors and uncalibrated representation affinities do not
establish listening relevance. No parameter changes follow from these artist
examples or later predictive outcomes.

The fixed reused-fold evaluation completes at
`.cache/emergent-evaluation/feature-holdout-lexical-20260930-v1/report.json`.
Recall@10 is **35.33%**, versus frozen v4's 29.06% and the conditioned baseline's
57.01%. On tag-only positives it reaches **16.56%**, compared with 14.20% for v4
and 15.65% for the conditioned baseline. The latter gain is only 72 of 7,868
positives, and is on a reused diagnostic fold. It supports a limited improvement
in source-tag reconstruction, not overall predictive superiority or validated
musical hierarchy. Tag-only MRR is 0.0925 versus the conditioned baseline's 0.0715.

A separate fit on `.cache/microgenre-features-primary-v1/artist-features.jsonl`
produces 16 broad / 255 sub / 925 micro candidates, with artist coverage
198,409 / 89,754 / 83,230. Its fitted source vocabulary has 6,348 facets and
39,089 distinct musical profiles, including 107,188 singleton-profile artists.
Those corpus changes prevent interpreting the changed candidate counts as a
controlled representation-only comparison. Artifacts are retained in
`.cache/emergent-topics/lexical-primary-source-20260930-v1`.
