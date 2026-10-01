# Emergent community evaluation contract

The target is finer musical structure learned from open source observations. The
697 existing direct genres are a baseline and optional parent-context diagnostic,
not a ceiling or a required output vocabulary. Learned groups remain **inferred
feature communities** until independent evidence supports established genre names.

## Non-negotiable evidence boundaries

- Never train on Every Noise coordinates, artist assignments, or genre labels.
  A historical reference may be used only as a separately disclosed evaluation.
- Compare canonical musical feature **values**, merging duplicate source facets
  and votes. Artists with identical musical profiles must receive identical
  primary and overlapping assignments. Geography, dates, artist names, vote
  totals, or layout coordinates cannot justify subdividing those profiles.
- Count exact observations and independent profiles, not duplicated release
  editions, credits, tags, or votes. Report source coverage, abstentions, community
  sizes, distinct musical profiles, and dominated/single-profile communities.
- Descriptive words attached to a cluster are model descriptors. They do not
  create factual artist-to-genre memberships or established subgenre names.

## Independent diagnostics

`opennoise.analysis.emergent_community_evaluation` accepts musical profiles and
one disjoint primary assignment per artist, independently of the fitting code.
Evaluate each declared hierarchy depth; overlapping secondary memberships require
a separate evaluation and are explicitly excluded from these scores.

1. **Profile integrity:** audit the complete cohort for identical musical profiles
   split across communities. Any split fails the core constraint, regardless of
   how convincing a layout or coherence score looks.
2. **Coherence versus null:** compare mean within-community IDF-weighted cosine
   against 99 assignment permutations within exact musical-feature-degree strata.
   This preserves community sizes and degree composition. Use a fixed, at-most
   10,000 artist UUID hash sample, chosen before seeing assignments. Report the
   sampled count, null mean, excess coherence, and empirical upper-tail probability.
   This is an in-sample diagnostic, not held-out accuracy, and its probability is
   not corrected for trying several models or resolutions.
3. **Stability:** independently refit declared source resamples without selecting
   favorable runs. Report label-invariant adjusted Rand agreement and the jointly
   assigned fraction for every run. Single-community and all-singleton partitions
   do not receive a stability score. Stability alone cannot establish musical
   validity; a consistently arbitrary partition can also be stable.
4. **Held-out evidence:** use source independence groups. All editions of a release
   group share a group; repeated votes for one tag share an artist/source/tag group.
   Connected duplicate artist-feature pairs must stay on one side of the split.
   `split_feature_evidence` and `assert_feature_holdout_isolation` enforce these
   supplied boundaries. Callers must establish correct upstream grouping; hashes
   cannot discover that two purported sources copied the same evidence.

For a predictive evaluation, freeze fitting settings on training/validation
groups, fit without held-out evidence, and measure recovery of held-out positive
features against frequency and existing direct-genre baselines. Include cold and
unsupported artists in denominators; absence is not a verified negative. An
artist's release tags must not appear as both its training features and supposedly
independent target evidence through another edition or credit path.

The first predictive run uses a prespecified 20% hash split of canonical
artist-feature pairs, removing each withheld value from **all** source facets
before fitting. It measures within-source reconstruction, not independent-source
genre truth. Distinct tag values in one artist response can fall on opposite
sides; repeated votes and artist-genre/tag copies of the same value cannot.
Release-derived features require release-group grouping across artists before
this boundary can be used. Artist-only input is required for the initial run.
Rank 10 is fixed. Compare score-weighted centroids at the deepest actually assigned
topic level against global training frequency and mean training conditional
feature probability given retained proper genres. The conditional baseline uses
frequency when no proper genre remains; unsupported model artists abstain.

## Interpretation

Aphex Twin and Four Tet are useful inspection anchors, not tuning targets or gold
labels. Report their exact source profiles, assigned hierarchy, closest supported
neighbors, and distinguishing evidence. A useful result separates diverse musical
profiles reproducibly, improves frozen held-out recovery, and exposes uncertainty.
More nodes, nicer names, or a visually separated map do not establish finer genres
or Spotify/Every Noise parity. Until independent refits and held-out prediction
run, those evaluation fields must remain unavailable.

Run the independent artifact check with
`python scripts/evaluate_emergent_topics.py --model-directory <local-run> --output <new-cache-file>`.
It verifies the model receipt and all four bound output files, requires complete
primary assignments, and writes its own receipt-bound evaluations. The standalone
`evaluate_feature_recovery` helper supports future frozen rankings with cold and
unseen-feature positives retained in the denominator; using it does not establish
independent-source gold or validate genre names.

## Recorded comparison, 2026-09-30

The fixed input is `.cache/microgenre-features-rich-v2/artist-features.jsonl`
(SHA-256 `32c9d3332854988d89432343e7cc567eaa406c8f53617d835a9a3907d89cb577`).
The v3 and v4 evaluations use byte-identical training partitions and 85,109 held
positive artist-value pairs. They include 25,570 positives from artists with no
retained musical feature and 2,023 positives whose value is unseen in training.

| Scorer | All positive Recall@10 | Tag-only Recall@10 | Tag-only MRR@10 |
| --- | ---: | ---: | ---: |
| Global training frequency | 28.26% | 0.00% | 0.00000 |
| Retained proper-genre conditional baseline | 57.01% | 15.65% | 0.07146 |
| v3 deepest assigned topic centroids | 29.19% | 12.46% | 0.07188 |
| v4 deepest assigned topic centroids | 29.06% | 14.20% | 0.08087 |

The v4 optimizer fixes premature rejection of a split before convergence and
compares two fixed initializations by training gain. This change was justified
from training diagnostics before its predictive evaluation. The second run is
nevertheless a **reused-fold comparative diagnostic**, not a new untouched test.
There is no overall predictive superiority over the proper-genre baseline.
Higher tag-only reciprocal rank is a narrower result and does not erase lower
tag-only recall or establish fine-genre truth.

The full v4 cohort contains 198,409 artists and 36,085 distinct musical profiles.
An independent refit exactly reproduces primary assignments and preserves all
primary and overlapping assignments for identical musical profiles. Replayed
core support validates 20,365 fine core-partition memberships and 353,683 fine
cosine memberships: each shares at least two canonical musical values and at
least one nongeneric value enriched 1.25 times relative to its parent. The
75,177 additional fine ancestor memberships have supported descendants and are
explicitly inherited, rather than independent fine-topic evidence.

Three fixed 80% cohort refits give v4 micro adjusted Rand agreement
0.8394 / 0.8455 / 0.8391, but only 29.64% / 30.26% / 30.00% of the full reference
cohort is jointly assigned. Broad agreement is weaker: 0.6496 / 0.7485 / 0.5420.
Neither metric validates names or guarantees unseen-artist performance.
A separate synthetic fixture produces 1,024 micro nodes from 1,024 distinct
musical profiles with 20 artists each, preserving identical-profile assignments.
This establishes capacity beyond 512 nodes, not 1,024 real musical genres.

Immutable local evidence:

- v3 model: `.cache/emergent-topics/rich-20260930-v3/`; heldout:
  `.cache/emergent-evaluation/feature-holdout-20260930-v1/report.json`.
- v4 model: `.cache/emergent-topics/rich-20260930-v4/`, report identity
  `b29069eea8b2f0920b8906445f96ac74377f3c4d46ee9b51816e2370524a9532`;
  heldout `.cache/emergent-evaluation/feature-holdout-20260930-v2/report.json`.
- v4 profile/null audit: `.cache/emergent-evaluation/rich-20260930-v4.json`;
  three refits: `.cache/emergent-evaluation/stability-20260930-v2/report.json`.
- Full membership replay:
  `.cache/emergent-evaluation/membership-audit-20260930-v4.json`;
  synthetic capacity: `.cache/emergent-evaluation/capacity-20260930-v2/report.json`.
