# ListenBrainz user-disjoint holdout abstention

This fixed local-only feasibility slice tested whether the seven retained raw
ListenBrainz daily archives can support a genuinely user-disjoint retrieval
holdout without reusing the already qualified aggregate's time split. It
changes no source, model, static asset, deployment, or playlist artifact.

## Fixed design

The run hash-verified all seven retained daily archives from the source vault
and read the first 10,000 JSONL records of each archive, for exactly 70,000
records. It accepted only syntactically valid, source-provided MusicBrainz
artist UUID strings from the mapping field (falling back to the
source-submitted additional-info field when no mapping was present). This is
identifier availability, not a verified artist identity or catalog join. A
fixed SHA-256 bucket of the numeric
ListenBrainz user ID assigned each user to one of two disjoint arms before
any co-listen aggregation. User IDs existed only in the in-memory accumulator.

Each retained user contributed a deduplicated artist set capped at 20 artists;
an over-cap user was discarded rather than retaining more history. Within each
arm, an unordered artist pair needed support from at least five distinct users.
The proposed held-out comparison required that this privacy floor hold
separately in both arms. It would have compared train-pair support ranking at
10 with train artist-degree popularity over an exact-ID candidate cohort, but
only if the held-out arm had eligible pairs.

The ignored local aggregate receipt is
`.cache/listenbrainz-user-disjoint-holdout-20260923/report.json`, SHA-256
`60a5ee71b518cf6dfaaed4b824ffa3f16c386bf03b359741751f3ab85fd9d09e`.
It contains source object hashes and aggregate counts only, with no listener
IDs, listens, artist IDs, pairs, rankings, or source text.

## Result and decision

All 70,000 records parsed as valid listens, but only 4,439 carried a
syntactically valid source-provided artist UUID. The deterministic split retained 629 train users and 615 test
users after the artist cap. No test-arm artist pair met the separate
five-distinct-user floor, so there is no valid fixed held-out cohort and no
ranker-versus-popularity result.

The experiment therefore abstains. Do not expand the prefix, lower the
privacy floor, merge the arms, or select a different slice after seeing this
outcome. A future user-disjoint experiment needs a separately declared sample
budget and a new receipt before it can make any comparison. Listener
co-occurrence would still not establish a genre, factual membership, or
musical-similarity claim. This run used no playlist input and makes no claim
about account independence, repeated playlists, or human/manual curation.
