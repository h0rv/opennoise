# Adaptive coarse evidence cut

This separate experiment addresses a structural limitation observed in the
frozen 16-parent topic models: a fixed small coarse frontier can put unrelated
residual families under one parent even when finer groups have useful source
support. It retains the frozen lexical representation and changes the coarse
stopping rule, rather than selecting a target number of genre names.

## Prespecified stopping rule

Before fitting this experiment to either real corpus, the following gates were
fixed. A coarse leaf qualifies when its artist-weighted mean cosine to its
centroid is at least 0.60 in the lexical/source representation and at least 0.50
in the original observed-source representation. It must also have at least 0.10
mean representation cosine between distinct canonical musical-profile groups.
The latter excludes all identical-profile self-pairs: two orthogonal profiles
each have cosine 0.707 to their common centroid but provide no cross-profile
similarity. A single indivisible source profile has no comparison pair and can
form one coarse leaf; it cannot justify additional fine communities.

Leaves failing these gates are refined by artist-weighted coherence deficit.
Each split retains the frozen minimum 20 artists per child and representation
split-gain checks, and additionally needs original-source mean-cosine gain at
least 0.002. Refinement stops at 128 coarse leaves or when no supported split
remains. The cap is a safety limit, not a count objective. Coarse leaves that
still fail are explicitly marked `abstained_no_supported_coarse_split`,
`abstained_insufficient_source_split_gain`, or
`abstained_coarse_budget_exhausted`. They remain auditable inference candidates,
not a claim of coherent established taxonomy.

The sub/micro budgets and membership evidence gates are unchanged. Identical
musical profiles remain indivisible, singleton musical evidence cannot qualify
for fine membership, differentiating values must be observed source values,
and every fine membership retains ancestry. Scores describe the lexical
representation; labels and predictive centroids are projected back to actual
observed source features after fitting.

## Implementation and comparison

The isolated `emergent_adaptive_topics.py` adapter accepts the constructed
frontier while retaining the frozen v4 assignment contract. Neither v4,
feature-graph, nor lexical source files is modified. The original-source
comparison uses rich-v2; the new primary corpus is a separate fit. Parameters
were fixed and regression tests completed before receiving the lexical
predictive result; no adaptive parameter grid is run. The fixed-fold comparison
remains a reused diagnostic, not an untouched predictive test.

Implementation SHA-256:
`b3e8c15e11346d77af5c4cb4d82ca4fe4ab1c4779c29fe576c5b004962a05ddf`.
The builder receipt also binds the lexical, graph, and original topic modules.
Tests cover the orthogonal-profile self-similarity error, one-profile stopping
without forced community counts, and unsupported source splits.

## Completed construction comparisons

On pinned rich-v2, adaptive v1 produces 76 broad, 212 sub, and 985 micro nodes.
Seventy-five broad nodes meet the declared evidence gates; one 80-artist core
(dangdut / polka / choro) remains explicitly unsupported. Source-weighted core
cosine becomes 0.623 / 0.793 / 0.880, versus fixed lexical 0.463 / 0.788 / 0.880.
The higher broad count changes the comparison; this does not validate taxonomy.
Drum and bass / jungle / breakcore and country / rockabilly / country rock now
have separate coarse parents. Residual mixed descriptors still occur.

The primary-v1 corpus produces 95 broad, 194 sub, and 919 micro nodes, with
198,409 / 82,010 / 83,127 artists assigned at those levels. Ninety-two broad
nodes pass the gates. Three unsupported terminal cores total 245 artists:
synthwave / darksynth / cyberpunk (87), dangdut / merseybeat / beat music (48),
and arabesk / fantezi / canzone napoletana (110). Failure means the construction
could not meet the declared evidence threshold; it is not a judgment that the
descriptor words are musically incompatible. Source cosines are
0.642 / 0.799 / 0.869. The 128-node safety cap is not reached in either corpus.

Aphex Twin has a source-derived idm / glitch / ambient micro candidate. Four Tet
has a melodic house / electronica / edm micro candidate. Four Tet has no emitted
sub node in this adaptive fit because qualifying former sub nodes became coarse
parents. A branch can therefore go directly from broad to micro. Missing
intermediate levels are explicit; repeating one node at multiple resolutions
would invent hierarchical detail unsupported by the fitted tree.

## Sealed export projections

Original construction reports remain immutable. The export requires an explicit
`native_genre_memberships_added: 0`, omitted by the first standalone builder.
`emergent_topic_projection.seal_topic_projection` verifies every source receipt
binding and every community/membership inference role, then copies bound files
byte-identically into a new directory. Its new receipt binds the exact parent
report and adds the verified zero count. It does not refit or change assignments.
Future builders emit the field directly. Regression tests reject tampered source
bytes and native-role assignments, and verify original receipt immutability.

The primary export directory is
`.cache/emergent-topics/adaptive-lexical-primary-source-20260930-v1-export`,
identity `6cf64c4ae6c733c7e4e0887510eaebf4c2779bc1e624cc1de4afa561bb3169e1`.
The old-source comparison projection is
`.cache/emergent-topics/adaptive-lexical-v2-source-20260930-v1-export`, identity
`1dcfacee761a54b856a4ddd5b5a61ad324d7e7d9adbe005310ef92288280541c`.

## Frozen reused-fold prediction result

The independent old-rich-v2 comparison is complete. Adaptive Recall@10 is
**36.56%** (31,113 of 85,109 positives), versus fixed lexical **35.33%**, frozen
v4 **29.06%**, and the conditioned proper-genre baseline **57.01%**. On tag-only
positives the adaptive model reaches **18.09%** (1,423 of 7,868), compared with
lexical **16.56%** and conditioned baseline **15.65%**. Tag-only MRR is 0.10575.
This supports a limited source-tag reconstruction gain. It does not show overall
baseline superiority, validate genre names, or establish Every Noise parity.

All four implementation bindings stayed frozen. The report is
`.cache/emergent-evaluation/feature-holdout-adaptive-20260930-v1/report.json`,
identity `9162a51b437e0f37672786fb039657b620fa608029b414cdf6462f1531c7c341`.
Its source/training/target hashes match earlier old-corpus comparisons. This is
still a reused diagnostic fold; no claim of a new untouched test is made.

Coarse coherence flags concern fitted core profiles, not the complete overlapping
membership set. The old-source unsupported node has 80 core artists and 107
memberships. The three primary-source unsupported nodes have 87/1,071, 48/90,
and 110/129 core/total memberships respectively. Counts of overlapping
memberships should not be substituted for evaluated core support.

## Final fit on cleaned primary source

The final source-only fit uses primary-v2 feature SHA-256
`0c298b1241b03e642dbc7b13981f59b9008cb1fdc4e01186b5fe55e7f2c78748`:
198,409 identities and 615,812 feature observations after the upstream metadata
cleanup. All four model implementation hashes and all settings are unchanged.
No new predictive test or tuning follows this source revision. Earlier reports
and fits remain immutable.

The final directory is
`.cache/emergent-topics/adaptive-lexical-primary-clean-20260930-v1`, output
identity `5a1eb2501a4f72089bb16acdbdb7e1e8dcb751da783f0c88b8da1e7be73c5704`.
The builder directly records zero native membership additions and no historical
or artist-name construction inputs, so an export projection repair is unnecessary.
It produces **106 broad / 182 sub / 954 micro** candidates, covering
**198,409 / 82,170 / 82,842** artists. The retained vocabulary has 5,804 source
facets and 38,376 musical profiles; 107,833 artists still have singleton musical
profiles. Source-core cosine is 0.645 / 0.797 / 0.876.

Of the 106 broad nodes, 104 pass the fixed construction gates. Two unsupported
terminal candidates remain: arabesk / canzone napoletana / dangdut (142 core
artists, 159 overlapping memberships) and synthwave / darksynth / cyberpunk
(83 core, 1,076 memberships). These flags do not evaluate listening relevance.

All ten exact-ID electronic benchmark artists retain micro memberships.
Aphex Twin retains idm / glitch / ambient. Four Tet retains tech house / house /
edm and bassline / uk garage / electronica candidates, with no intermediate sub
node. Some other benchmark affinities remain weak; coverage is not independent
relevance. The bound benchmark and descriptor audit is
`.cache/emergent-topics/adaptive-primary-clean-descriptor-audit-20260930-v1.json`.

A separate audit applies the current upstream metadata filter to tag-derived
community descriptors. The prior primary fit had 13 matching occurrences from
six values, including private tags, debut events, a fire-victim annotation,
baritone, and virtual youtuber. The clean fit has zero descriptor matches to
that filter. This verifies removal of the known metadata categories, not the
absence of every possible noise term or semantic error. The comparison is
`.cache/emergent-topics/clean-primary-descriptor-filter-audit-v1.json`.
