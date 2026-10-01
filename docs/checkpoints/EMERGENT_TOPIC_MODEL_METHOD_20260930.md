# Source topic model method, 2026-09-30

These local experiments construct inferred music communities from open artist
features. They do not reproduce an established taxonomy, validate names by
listening, or establish 100% Every Noise parity. Historical artist memberships,
coordinates, and names are absent from fitting. Display names join afterward.
The 697 direct proper genres are inputs, not a ceiling on inferred community count.

## Pinned inputs and musical equivalence

The evaluated input is `.cache/microgenre-features-rich-v2/artist-features.jsonl`:
198,409 exact artist IDs, 558,467 source-faceted features. It combines direct
MusicBrainz proper genres with verified positive artist tags. Newer release-group
or geographic-cleanup caches remain separate experiments. Supplementary source
tags have noncommercial/share-alike licensing; all artifacts remain local research.

The loader normalizes Unicode and whitespace, rejects unsupported namespaces,
requires evidence references, and rejects nonpositive weights. Explicit technical,
place, nationality, and occupation tag values are filtered; native proper-genre
values bypass this tag filter. Compound musical terms remain available. The
fitted vocabulary retains source features supported by at least two artists.
Duplicated source facets share feature mass. Generic broad music terms have 0.35
weight; structured area and decade context have 0.15 weight. IDF and L2
normalization follow. Votes never create additional artist identities.

All artists with the same set of canonical musical values collapse into one
profile group before fitting. Differences in source facet, vote, area, and time
cannot split such artists into claimed microgenres. Rich-v2 retains 36,085 distinct
musical profiles and 109,546 artists with only one musical value. Sparse evidence
therefore imposes a substantial limit on justified fine assignments.

## Spherical hierarchy and the optimizer correction

`opennoise.ml.emergent_topics` builds a weighted spherical hierarchy. The source
artist count weights each collapsed profile. Best-first weighted dispersion
refinement has frontier budgets 16, 256, and 4,096, with depth capped at 32.
Every child needs at least 20 artists and both full-feature and musical-only
cosine gain at least 0.002. Budgets do not force unsupported communities.
A terminal node is emitted once, rather than repeated under finer level labels.

The v3 optimizer incorrectly checked the 20-artist support threshold before
spherical updates converged. A tiny initial Voronoi cell could prematurely stop
a heterogeneous branch containing hundreds or thousands of artists. V4 checks
support after convergence and compares two fixed deterministic initializations
(full-mass and square-root-mass farthest starts), choosing the larger training
objective gain. The regression case has a 4-artist outlier that previously
blocked a valid 34/1,000 split. Neither the change nor its two starts was selected
using withheld-feature scores.

V4 at `.cache/emergent-topics/rich-20260930-v4` yields 16 broad, 245 sub, and 922
micro candidates; artist coverage is 198,409 / 86,230 / 78,811 respectively.
Aphex Twin and Four Tet both have all three resolutions, including a micro
candidate described by club / techno / electronica. This establishes navigable
source-derived coverage, not musical relevance or equivalence to Every Noise.
The frozen implementation SHA-256 is
`95123d96aadc23af326081d916161effab8501d99d6e32ec152a8434579550d0`.

Fine memberships require two distinct musical values and a nongeneric value
whose prevalence distinguishes the child from its emitted parent. The fitted
core assignment is retained with its actual cosine, even below the optional
0.35 overlap threshold. Up to three extra direct overlaps per level can be
proposed; ancestor closure can add further memberships. Scores are uncalibrated.
Labels use top source descriptors and never promote inferred assignments into
native observed facts. Source-supported examples are ordered by cosine then ID,
not independently measured relevance. Full centroid and core-profile artifacts
support audit and evaluation beyond the five displayed descriptors.

## Separate graph initialization experiment

`opennoise.ml.emergent_feature_graph` tests another broad initialization while
leaving the evaluated spherical implementation frozen. It constructs canonical
musical-value cooccurrences, collapsing duplicate facets and weighting each
artist by `1 / max(1, canonical_degree - 1)`. Cooccurrence cosine requires at
least two shared artists and retains mutual top-20 feature neighbors.
Deterministic modularity local moves with aggregation use fixed resolution one.
Disconnected graph components cannot merge. No area, time, artist names, or
historical data enters this graph.

Each exact musical profile selects its strongest feature basin by summed source
IDF, with the same generic-term downweight. Basins with fewer than 20 artists
abstain. The broad count is graph-derived, then the same supported spherical
refinement supplies sub/micro candidates under budgets 256 and 4,096. This
alternative has hard assignments, not overlapping cosine proposals. Its
coherence and predictive diagnostics must therefore be reported as a separate
model, not attributed only to graph initialization. Fine assignments require
at least two canonical values. It is a prespecified source-only experiment,
not a chosen winner or a validated genre system.

## Evaluation boundaries

The independently evaluated v3 model achieved 29.19% held-out Recall@10, versus
57.01% for a conditioned proper-genre baseline. The failed comparison remains
part of the record. Optimizer and graph comparisons reuse that fixed fold and
must be called diagnostics, not new untouched tests. All duplicate facets of a
withheld artist/value are removed together before fitting vocabulary, supports,
IDF, centroids, and assignments. Cold positives remain in the denominator.
Within-source reconstruction, partition coherence, and resampling stability do
not establish listening relevance or factual genre names.

The separate direct-genre artist-map helper now abstains from geometry when
all selected artists have one identical musical profile. Its earlier v2 jazz
cohort therefore does not justify 200 distinct positions. The immutable earlier
map snapshots remain historical diagnostics; current code reports explicit
`abstained_identical_source_profiles` and null coordinates.

## Graph v1 observed construction results

The immutable `.cache/emergent-topics/graph-20260930-v1` uses the same rich-v2
input. Its 3,730 canonical musical values yield 8,821 mutual edges, 1,014
connected components, and 1,051 feature basins. Only 44 resulting artist basins
have sufficient support; 1,056 artists abstain from every level. The output has
44 broad / 231 sub / 1,142 micro communities, covering 197,353 / 85,872 / 84,299
artists. Implementation SHA-256 is
`97fa65a8f4a9eb38f25690552cddd70bbdc07d46f674e5ddd0d3a545abde0b29`.

Source-weighted core centroid cosine is 0.397 / 0.801 / 0.906 for broad/sub/micro,
versus 0.452 / 0.774 / 0.869 for spherical v4. Different partitions, counts, and
coverage mean this is a training diagnostic, not a matched quality improvement.
The graph broad average is worse, although some common families have clearer
source labels. Mixed groups and unfiltered source-noise terms remain. Its hard
fine assignments for Aphex Twin and Four Tet have low cosine affinities (0.206
and 0.158). Therefore graph v1 is not selected as a superior discovery model.
The exact frozen holdout comparison is delegated to the independent evaluator.

The completed reused-fold diagnostic confirms that neither change beats the
conditioned proper-genre baseline. Spherical v4 Recall@10 is **29.06%**, graph
v1 is **22.30%**, and the fixed conditioned baseline is **57.01%**. On tag-only
positives, the values are **14.20%**, **12.25%**, and **15.65%**, respectively.
The graph alternative is also below the global-frequency baseline of 28.26%
on all held-out positives. Increasing community count and apparent training
coherence has not produced a better enrichment predictor. Frozen reports are
`.cache/emergent-evaluation/feature-holdout-20260930-v2/report.json` and
`.cache/emergent-evaluation/feature-holdout-graph-20260930-v1/report.json`.
