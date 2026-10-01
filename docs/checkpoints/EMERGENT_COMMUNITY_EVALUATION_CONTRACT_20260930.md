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

### Separate feature-graph experiment

The frozen `emergent_feature_graph.py` experiment changes both broad initialization
and membership assignment: it uses hard core memberships without the v4
individual parent-enrichment gate. Its comparison therefore does not isolate an
initialization effect. All identical-profile primary constraints pass, but the
44-community broad partition has in-sample cosine coherence 0.1539 versus v4's
0.2532. The graph model's fixed-fold Recall@10 is 22.30% overall and 12.25% on
tag-only targets, below v4, global frequency overall, and the conditioned
proper-genre baseline. These results do not support promoting it as a quality
improvement.

The source module and shared v4 dependencies were byte-pinned before training;
the evaluator accepted an explicit `TopicFitterBinding` without changing the
default fitter. The training file and targets match the earlier fold exactly.
Evidence is `.cache/emergent-evaluation/graph-20260930-v1.json` and
`.cache/emergent-evaluation/feature-holdout-graph-20260930-v1/report.json`
(receipt `ca3d4fde3d9349bc06d258c8af68b5ee6bf0fda245ba6c4b09576e856037f0e3`).

### Frozen native-tag lexical representation

The separately prespecified lexical/cooccurrence representation improves the same
reused-fold diagnostic to 35.33% overall Recall@10 and 16.56% tag-only Recall@10.
The conditioned baseline remains stronger overall at 57.01%. Tag-only recovery
is 1,303 versus 1,231 positives for that baseline, a narrow 72-positive gain;
tag-only MRR@10 is 0.09247 versus 0.07146. These are source-feature reconstruction
results, not independent musical validation. All three implementation dependencies
were frozen, with no parameter selection on these scores. The training and target
bytes exactly match the earlier experiments. Evidence:
`.cache/emergent-evaluation/feature-holdout-lexical-20260930-v1/report.json`,
receipt `db90059d366100bd672b3a83b641a0759486094dde2a4f4a63aaa263ff8a60d2`.

The subsequent prespecified adaptive coarse frontier uses the same frozen
representation and retains the source-support membership guards. On the same
reused fold, overall Recall@10 increases to 36.56% (31,113/85,109), still below the
conditioned baseline's 57.01%. Tag-only Recall@10 is 18.09% (1,423/7,868), versus
15.65% for that baseline; tag-only MRR@10 is 0.10575 versus 0.07146. All four code
dependencies and exact training/target bytes are bound in
`.cache/emergent-evaluation/feature-holdout-adaptive-20260930-v1/report.json`,
receipt `9162a51b437e0f37672786fb039657b620fa608029b414cdf6462f1531c7c341`.
Unsupported coarse groups remain explicitly marked candidates. The original
corpus has one such group with 80 core artists but 107 total and primary broad
assignments; these must not be represented as evidence-supported taxonomy.

### Independent replay of nested feature enrichment

The separate predictor uses a newly declared outer split on the already explored
corpus, and chooses smoothing from 4/16/64 using an inner split only. An independent
audit reproduces both split files byte-for-byte, the selected sparse association
and support matrices exactly, all saved enrichment rankings for 198,409 artists,
every reported outer metric, and the inner selection rule. No outer-target
training leakage was found in this implementation. Evidence:
`.cache/artist-feature-enrichment-nested-v1-independent-audit.json`, receipt
`a349f398c390daef372ed092b4e6ee9bd3fd18ea0aba4e8410b5fd9fee494fed`.

On 85,755 outer positives, enrichment Recall@10 is 45.83% versus 56.99% for the
conditioned baseline. Prespecified strata improve: tag-only 24.12% versus 16.48%,
one retained musical value 68.18% versus 65.40%, and training support at most five
2.71% versus 0.67%. All 25,769 cold positives remain in the denominator; enrichment
abstains while the baseline guesses 11,481 correctly. This explains much of the
overall gap without permitting their removal from the primary score.
Proposals remain inferred, uncalibrated metadata suggestions; they cannot count
as new independent observations, native memberships, or validation evidence.

### Bulk source audit and paired increment protocol

The independent raw bulk audit fetched the official checksum manifest again,
verified the complete derived archive, verified the bounded core prefix and
complete artist member, and replayed every selected name, numeric/UUID join,
aggregate tag/count, source ordinal, and row hash with a separate COPY decoder.
Actual core and derived schema, replication sequence, and timestamp agree.
The whole core archive remains unverified. Primary-v1 and primary-v2 selections
contain exactly the same 198,409 UUIDs. Of these, 28 are absent from the current
core dump, 25 matched artists have no positive tag, and 198,356 have positive
aggregate tags. The raw projection contains 616,440 positive observations and
40,825 raw label strings, which are not automatically musical or incremental
features. It preserves nonpositive counts as raw evidence; model input must
exclude them. Audit receipt:
`.cache/bulk-artist-tag-independent-audit-20260930-v1/report.json`, identity
`5278e0bba1f17ce548f1efec3e0edc87c25d1da6538d5b67c6b4a3afe4d0f6e3`.

The finalized v2 projection preserves all 198,381 audited present records exactly
and adds 28 explicit absent/empty records, completing the selected cohort. Source
archive/member/selection/capture bindings are unchanged; local noncommercial
research input is authorized and public export is not. Independent v2 audit:
`.cache/bulk-artist-tag-independent-audit-20260930-v1/v2-semantic-report.json`,
identity `61f8995ae1ab9964c56819d6d508370ce1fe49bf25f7e90009712a3d58642f4a`.

The next paired diagnostic is prespecified in
`opennoise.analysis.paired_feature_increment`. Its salt is
`bulk-source-increment-paired-positive-fold-v1-fixed-20260930`. Select one target
fold from the augmented corpus, group duplicated values across all facets and
snapshots, preserve global release-group components, and remove those exact
artist-value targets from both old and augmented training inputs. Addition-only
comparison rejects any removed prior musical value or release-group provenance.
Both variants must use identical target identities and denominators, with cold
and unseen positives retained. Fit the previously selected enrichment settings
(smoothing 4) and unchanged adaptive topic settings; compare each to frequency
and proper-genre conditional baselines. No new parameter selection is permitted.
Report existing/new artist-values, existing/new global vocabulary, proper-genre
and tag-only targets, and rare/cold/unseen strata. These are within-source
reconstruction diagnostics: API observations, curated proper genres, and bulk
tags from MusicBrainz are overlapping evidence, not independent gold.

The actual paired inputs apply the same updated quality policy to old and new
sources: `primary-v2-policy-v2` (feature SHA `70f8dd0d…`) and `primary-v4`
(`2b6179b4…`). Independent normalization finds 434,527 versus 549,416 canonical
artist-value pairs, with no removals and no changed pre-existing facet weights.
The 114,889 additional pairs enrich 57,666 artists. Vocabulary grows from 14,057
to 31,864 values, but 15,644 of the 17,807 novel values occur for only one artist;
1,987 occur for two to five, 165 for six to nineteen, and eleven for twenty to
ninety-nine. These are source labels, not newly validated genres. Of 393,856
new musical source facets, 278,967 repeat an already observed artist-value pair.
Audit: `.cache/bulk-feature-increment-assessment-20260930-v2.json`, identity
`c4959d35a2b5e0d83cdb22f4b3a736e7f0a24ad7812af5cfbdfe9c362194454f`.

The authorized vocabulary admission bound grows from 30,000 to 50,000 without
singleton pruning or statistical changes. Independent source comparison confirms
that the community loader differs only in that constant and all eight predictor
statistical/helper function ASTs remain identical. Proof:
`.cache/paired-resource-cap-independent-audit-20260930-v1.json`, identity
`6bced587f55e824e3913399f5e2a8e4f1c7c9556dec977ef0a7f315af8323c0c`.
The paired diagnostic binds the new implementation hashes, reports actual
training vocabulary sizes and previous-bound admissibility, and preserves all
earlier frozen methods and evaluation receipts.

The actual augmented fold holds 110,027 canonical positive pairs (20.026%);
87,260 were already observed in the old source and 22,767 are new observations.
All 578 musical release-group identities fall into ten connected components;
the largest has 442 positives and the largest held component has 110. Both
variants retain the same 198,409 artist identities. Independent row replay
confirms that every target copy is removed and every other feature and row field
is preserved, with receipt `93897c3d3d8d11624c1fb832268b2065b1cc52bc1f9853d6b089c204bfd59185`
at `.cache/paired-bulk-source-increment-split-independent-audit-20260930-v1.json`.
The old training set has 11,961 canonical values and 15,296 namespace-value
identities; augmented training has 26,955 and 30,297 respectively. Thus both
predictor training inputs fit its previous admission bound, while the augmented
community loader requires the authorized extension even for this held-out fit.

### Frozen paired source-increment result

The completed paired report is
`.cache/paired-bulk-source-increment-20260930-v1/report.json`, identity
`e62b92d6c6324b7256d79a1a274c5a0ee20b3da35170a57f1e342a7ba0c8bd33`.
Every row below uses the same 110,027 targets; the tag-only stratum has 31,836.
Settings were fixed before fitting either variant and no score selected a model.

| Scorer | All Recall@10, old → augmented | Tag-only Recall@10, old → augmented |
| --- | --- | --- |
| Adaptive communities | 30.25% → 36.20% | 14.58% → 26.95% |
| Feature enrichment | 39.86% → 47.06% | 19.92% → 35.03% |
| Global frequency | 22.56% → 22.93% | 0.00% → 8.50% |
| Proper-genre conditional | 48.57% → 50.07% | 18.24% → 28.10% |

Added source evidence improves both fixed learned methods on these matched
targets. Enrichment outperforms the conditioned baseline on tag-only values,
but both learned methods remain below it overall, and adaptive communities also
remain below it on tag-only recovery. The conditioned baseline itself loses
proper-genre recovery (60.92% → 59.02%) and previously observed-pair recovery
(56.57% → 55.52%), illustrating a tradeoff from expanded candidate competition.
Cold positives fall from 27,399 to 21,220 and unseen positives from 6,859 to 5,063;
all remain in their variant's shared target denominator.

Of 4,459 targets whose canonical labels were absent throughout the old source,
enrichment recovers only 67 (1.50%), adaptive communities 33 (0.74%), and the
conditioned baseline one. Every training-unseen target fails. Source vocabulary
growth therefore does not establish reliable novel microgenre recovery. The
predictor collapses duplicated canonical values; community vectors retain source
namespaces and weights, so their contrast combines newly observed values with
reweighting from repeated source facets. These results quantify complete source
augmentation, not an isolated effect of novel vocabulary, sonic similarity, or
independently validated taxonomy.

A separate replay verifies the report/file hashes and recomputes every stratum's
Recall@10 and reciprocal-rank sum from all eight saved ranking streams exactly.
Enrichment gains 9,801 target hits and loses 1,883; adaptive communities gain
13,739 and lose 7,186. Within tag-only targets those changes are +4,903/−92 and
+4,768/−830 respectively. Audit:
`.cache/paired-bulk-source-increment-metrics-independent-audit-20260930-v1.json`,
identity `daf9875b6d5546d33ae500bbbe1979deee43bb60f5c956d41579d1157afd4d2f`.
