# Last.fm versus ListenBrainz source-isolated genre holdout design

## Status

This is a pre-registered **proposal**, not an authorized run. The completed
local Last.fm 360K aggregate still declares `model_input_allowed=false`; it must not be
read by a diagnostic ranker unless a new local-research policy and a separate
receipt explicitly permit this one evaluation role. It never changes a public
model, factual membership, serving output, or release gate.

## Purpose and frozen inputs

If a later local-research policy authorizes it, compare two independently collected
aggregate listening signals on exactly the same held-out, direct
MusicBrainz-proper-genre positives:

1. verified portable direct proper-genre custody is labels only;
2. the completed, hash-verified Last.fm 360K aggregate is one ranking arm;
3. the existing hash-verified ListenBrainz privacy-filtered aggregate is the
   other ranking arm.

Neither listening source may supply labels, seed aliases, taxonomy mappings,
candidate memberships, or a fallback edge to the other. The direct custody
labels are not inputs to either aggregate. Bind the completed Last.fm artifact
and working-database SHA-256, the ListenBrainz receipt/database SHA-256, the
direct-custody receipt/object SHA-256, target normalizer, exact catalog artist
ID set, and all code hashes before opening either aggregate database.

## Cohort and strata

For each direct-custody seed with at least five distinct direct artists, sort
`SHA-256(seed_id, NUL, artist_mbid)` and hold out the lowest fifth; retain at
least four artists for that seed's train set. The pair-level target is
`(seed_id, artist_mbid)`. The cohort is then restricted, identically for both
arms, to targets whose artist MBID is an endpoint in **both** privacy-filtered
aggregate graphs. Report every exclusion: insufficient seed support,
Last.fm-only endpoint, ListenBrainz-only endpoint, neither endpoint, and
invalid exact ID. Do not replace unsupported targets.

Report two disjoint artist strata and one orthogonal support conditioning rule,
without tuning on any of them:

| Stratum | Definition |
| --- | --- |
| artist-seen | Target artist has a direct label for another seed in the retained train set. |
| artist-cold | Target artist has no direct label for any train seed. |
| source-support | The exact target reaches the shared both-source endpoint cohort; this is a conditioning rule, not an artist-seen/cold label. |

The split is pair-level, so artist-seen is expected to dominate. Artist-cold
results are separately reported with their denominator and no threshold is
chosen from them.

## Source-isolated ranking

For one source at a time, remove target artists already attached to the seed
in train. Rank candidates only through that source's co-listen edges from the
seed's retained train artists, with the predeclared score
`sum(log(1 + distinct_user_count))`. Use the same `Recall@10`, `Recall@20`,
macro `Recall@20`, MRR@20, and support definition for both arms. Also report
the common-support intersection and each arm's source-specific support; do
not fill a missing Last.fm edge from ListenBrainz or vice versa.

Last.fm's aggregate uses all-time play counts and a capped first-ten exact
artists per contiguous user block. ListenBrainz uses timestamped daily
listens. Their counts, edge density, and popularity are therefore not
commensurate. Normalize only within each arm for ranking and never compare raw
counts or treat the larger score as stronger musical evidence.

## Privacy, popularity, and custody

Both arms require their source's fixed minimum of five distinct contributors;
the evaluator must reject a lower threshold. The Last.fm raw archive, profile
member, user SHA-1 values, artist names, and per-user plays are never opened
by the evaluation. It may read only the completed aggregate database after
its receipt/hash verification; output contains no Last.fm user identifiers.
ListenBrainz raw listens and user IDs likewise remain out of scope.

Report source-specific target degree/support quintiles and the two-dimensional
Last.fm-quintile × ListenBrainz-quintile cell counts. These are bias
diagnostics, not reweighting features. Separately report seed train size,
candidate count, and the share of targets supported in each source. Last.fm's
top-artist collection, all-time window, historical population, and
non-commercial terms; and ListenBrainz's opt-in, timestamped population can
all induce source and popularity bias.

## Permitted conclusion

A completed run can say only that, conditional on exact MBID endpoints, the
fixed direct-custody positive cohort, a five-user privacy floor, and matched
candidate rules, one aggregate source retrieved more held-out positives than
the other. It cannot estimate precision (absent labels are unknown), prove
genre membership, establish musical similarity, measure either source's
population coverage, establish causal user preference, validate a production
model, or authorize combining the two sources.
