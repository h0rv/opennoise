# MusicBrainz release and track discovery-signal audit

## Decision

Retained MusicBrainz data can support local discovery context for albums and
tracks, but it cannot add artist--genre memberships or a factual track/release
genre label. The safe next model is a source-partitioned, entity-native genre
observation layer. It must preserve the observation entity (`recording`,
`release`, or `release_group`) and make every artist association a separately
labelled credit-context join.

This checkpoint is local research only. It neither changes the public model nor
authorizes serving, export, factual-membership propagation, or ranking.

## Retained, byte-bound inputs

| Input | SHA-256 | Relevant retained role |
| --- | --- | --- |
| Release-group evidence artifact | `0a626b524a2e5976f47be13b29b8d44b1dabe54098443512b548c1abd4348de6` | Receipts for the source partition and capped release-group genre/tag support. |
| Release-group evidence database | `980b2c58e16b024d282ca1acc58b98dcab292f0e1a50917812d1b59df0340c8a` | Genre/tag support rows at release-group level. |
| Artist-credit catalog report | `f9ab6d74552935ecf198e28ea9f3875caf67cfcad9ee95883328c59954fcde00` | Core-metadata-only catalog receipt. |
| Artist-credit catalog database | `100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63` | Exact release, track, recording, release-group, and ordered credit identity. |

The source partition is `musicbrainz_json_release_group_research_20260905`,
snapshot `20260905-001001`, source archive SHA-256
`6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43`.
Its artifact reports 4,499,326 parsed release-group records, 1,546,265 capped
support memberships, 1,954 support genres, and 421,427 direct-anchor pairs.
Those aggregate figures are source coverage, not claims about the smaller
hydrated catalog cohort.

## Exact local diagnostic

The existing typed `musicbrainz-release-credit-genre-report-v1` replayed from
the four files above. Its persisted file SHA-256 is
`87ccec2dbb08e14fa2f553d744d7e96968480d78f86b3e364b130fba5a888770`; its
logical output SHA-256 is
`b9a3434816e8d3bbc7f8ecfd04323539f8f87ea2a985171dab208b03574bc64a`.
It sets both `export_allowed` and `serving_allowed` to `false`.

| Measure | Count | Meaning |
| --- | ---: | --- |
| Hydrated catalog release groups | 87 | Exact catalog cohort considered by the join. |
| Release-group support claims in that cohort | 284 | Contextual genre/tag support rows before credit expansion. |
| Exact contextual credit matches | 3,132 | Rows after exact artist-MBID and entity-credit joins; not independent genre claims. |
| Recording-context rows | 2,848 | Credited recording appearances attached to matched release-group support. |
| Release-context rows | 284 | Credited release appearances attached to matched release-group support. |
| Release groups with at least one output row | 57 | The remaining catalog groups had no exact support/credit overlap in this report. |
| Distinct contextual genre/tag IDs | 86 | Includes the facet below; not a reviewed public taxonomy. |
| Proper-genre rows / tag rows | 1,456 / 1,676 | Tags remain a separate positive-count facet. |
| Exact matched artists | 55 | Credited/support-artist ID overlap only. |
| Distinct joined entities | 689 | `recording` and `release` entities, not deduplicated music works. |

The catalog receipt says it contains 87 release relations, 1,031 recording
relations, 1,032 tracks, 1,031 distinct recordings, and 352 artists. Its
content policy is explicitly `core_metadata_only_no_audio_preview_artwork_or_genres`.
Accordingly, it contributes identity and credits, not recording- or
release-level genre observations. Of the 1,031 recordings, 1,030 currently
have exactly one retained release-group path; one has multiple retained release
groups and must remain multi-group rather than being arbitrarily assigned.

## Permitted interpretation

For a local album or track detail experiment, a result may say that an exact
release-group genre/tag observation provides *context* for an exact credited
appearance. It must show the native entity, facet, source snapshot, and credit
position. The release-group label must not be rewritten as a recording or
edition label, and a credited appearance (including featured artists and
compilations) must not be rewritten as an artist genre membership.

The 3,132 rows are a fan-out of 284 support rows across exact credits and
entities. They are therefore unsuitable as frequency, confidence, popularity,
or artist-similarity weights without a separately designed, held-out local
evaluation.

## Next safe modeling step

Add a new checksum-pinned MusicBrainz source partition before any new
projection. Parse proper `genres` and tags into separate, typed facts at their
native levels:

1. `recording MBID × genre MBID` is a recording fact; a tag is a distinct
   recording-tag fact with its positive count.
2. `release MBID × genre MBID` is an edition fact, linked to its exact release
   group; it does not label other editions.
3. `release-group MBID × genre MBID` is an album-concept fact.
4. A join from any of those facts to ordered artist credit is only
   `artist_credit_context`, preserving entity ID, credit position, and
   collaboration/compilation status. It is never an artist membership.

Require a pinned archive URL/snapshot/checksum, a row-level source reference,
separate genre/tag facets, an explicit policy declaration, and a replay receipt.
Keep multi-group recordings as multiple observations. Freeze the source
partition and downstream mapping before a held-out diagnostic, and exclude
MusicBrainz labels from any evaluation whose labels may already have entered
MusicBrainz tags.

The already-implemented local diagnostic and its unit tests are the appropriate
template: strict typed rows, exact-MBID joins, byte verification before and
after reads, logical output hashing, and hard `false` serving/export fields.
