# Native open metadata for richer artist communities

This local research acquisition expands the model's available descriptors beyond
the 697 native proper-genre seeds in the direct MusicBrainz catalog. It retains
official MusicBrainz artist tags, origin/time metadata, and independently sourced
release-group styles. It uses no audio, Spotify private data, historical Every
Noise artist assignments, or externally inferred genre memberships. The direct
catalog's source facts remain unchanged.

## Observed acquisition

| Separate artifact under `.cache/` | Resolved entities | Positive native observations | Retained requests |
| --- | ---: | --- | ---: |
| `musicbrainz-open-artist-features-final` | 38,985 artists | 124,740 raw artist tags, 14,241 raw labels | 341 reused exact-ID artist-search pages plus 50 new pages |
| `musicbrainz-open-artist-features-additional-15000` | 14,997 artists | 47,789 raw artist tags, 6,691 raw labels | 150 new exact-ID artist-search pages |
| `musicbrainz-native-credited-artist-features` | 55 artists | 33 raw artist tags and 17 native artist genres | 55 exact artist lookups |
| `musicbrainz-native-release-group-features` | 959 release groups | 2,274 raw release-group tags and 1,933 native release-group genres | 14 bounded browse pages for 10 artists |

The three artist shards are disjoint. Together they contain 54,037 native artist
records, 53,985 positively tagged artists, 172,562 positive raw tag observations,
and 17,859 distinct positive raw labels. These labels are community metadata,
not 17,859 validated genres. The base direct cohort has rich metadata for
53,982/198,409 artists (27.2074%). The other 55 identities are exact native
release-credit artists outside that cohort, independently looked up to acquire
names and artist facts. An unreturned exact identity remains unavailable.

The initial acquisition requested 5,000 additional artists, resolved 4,999, and
retained 33,986 already acquired native artist records. It contains Aphex Twin,
Four Tet, Boards of Canada, Autechre, Burial, Squarepusher, Floating Points,
Caribou, Brian Eno, and Jon Hopkins by exact native UUID. Aphex Twin has 28
positive raw artist tags and Four Tet has 20. Their native release-group rows
contain 123 and 142 release groups respectively. Release-group styles are kept
as release-group facts, independently of those artist tags.

The supplemental cohort contains no artist-name special cases. It excludes the
38,985 retained artist UUIDs, orders candidates with SHA256 using domain
`opennoise-additional-native-rich-artists-v1`, reserves 7,500 degree-one artists
via native-seed round robin, then fills the cohort via all-seed round robin.
The selected 15,000 identities include 8,136 degree-one artists, 616 native
proper-genre seeds, and 29,447 direct pairs. Its three absent responses produce
no rows. This stratification broadens source coverage; the proper-genre seed
vocabulary does not filter, rename, or define the emitted raw tags.

The supplemental acquisition retained 12,110,605 response bytes from
2026-09-30 19:48:33 through 19:52:10 UTC. New requests are sequential at least
1.1 seconds apart, with three attempts maximum and a 2 MiB response cap. Artist
search pages query at most 100 exact UUIDs. Release browse pages query at most
200 groups per selected artist. The credited-artist lookup is bounded to 100
identities and observed 55. This is bounded acquisition, not an ongoing crawl.

## Source rights and roles

The retained official [MusicBrainz data license page](https://musicbrainz.org/doc/About/Data_License)
distinguishes CC0 core metadata from CC-BY-NC-SA 3.0 supplementary tags and genre
associations. Each source artifact includes the same byte-bound license capture,
MusicBrainz contributor attribution, and local noncommercial research scope.
The artifacts do not authorize public export or deployment. Source and derived
receipts carry the attribution, noncommercial, and share-alike obligations.

The [Last.fm 360K feasibility work](LASTFM_360K_SOURCE_FEASIBILITY_20260922.md)
establishes that its large user/artist play matrix does not provide artist tags.
The older [ArtistTags2007 review packet](LASTFM_ARTISTTAGS2007_STATIC_GENRE_REVIEW.md)
has a separate historical source and unreviewed tag-to-fixed-genre bridge. It is
not silently merged into this acquisition. Official native metadata was chosen
because its exact artist UUID joins, field-level roles, response bytes, and
licensing could be retained and replayed immediately.

Artist search returns raw tags but does not return native proper-genre UUIDs in
these responses. Its `genres` array is therefore empty. A raw tag is never
promoted to a native artist genre. The 55 credited-artist lookups explicitly
request `inc=genres+tags` and retain actual native genre IDs separately. Native
release-group genres and tags retain release-group IDs and native artist-credit
IDs; a credit establishes context, not an inferred artist-genre membership.

## Reader contracts and replay

`verify_open_artist_features` and `iter_open_artist_feature_rows` in
`opennoise.catalog.musicbrainz_open_features` accept either sealed artist-search
artifact. Rows contain `artist_mbid`, `name`, raw `tags` with integer vote counts,
an empty `genres` array for these search responses, `country`, `type`, `area`,
`begin_area`, `life_span`, `source_document`, `source_response_sha256`, and
`source_role="native_artist_search_metadata"`.

`verify_native_artist_features` and `iter_native_artist_feature_rows` in
`opennoise.catalog.musicbrainz_native_artist_features` read the 55-artist shard.
It shares the artist schema, additionally retains actual native `genres`
(`id`, `name`, `count`), and declares `native_artist_lookup_metadata`.

`verify_native_release_group_features` and
`iter_native_release_group_feature_rows` in
`opennoise.catalog.musicbrainz_release_group_features` read release groups.
Rows retain `release_group_mbid`, title, first release date, native artist
credits, native genres, raw tags, `evidence_group_ids=["release_group:<UUID>"]`,
and source refs including `release-group/<UUID>`. All editions, duplicate query
responses, and artists credited to one group share that independence unit.

Every verifier recomputes the JSONL projection from retained official response
bytes and compares source, output, and receipt hashes. Artist-search replay
requires the exact `batch-NNNN.json` filename, permitted category, complete
companion receipt equality, exact query identity set, response containment,
and no source-document symlinks. New pages must partition the selected cohort;
the supplemental artifact binds `selection.json` by byte and logical hash.
Lookup redirects and missing responses abstain; a returned different UUID fails.
Raw spelling variants remain separate native observations. Model extraction may
canonicalize them, but duplicate facets cannot count as independent holdout facts.

## Immutable results

| Artifact | Logical receipt SHA256 | JSONL SHA256 |
| --- | --- | --- |
| Initial rich artist metadata | `19dd657dfb676cd4cf70da671c21610dbfea752c93963b9061d18b6dfd56082a` | `a62e4ed343d8401fdb9e2040ebf3dd37bfdec14143b8452d77269178ae46a342` |
| Additional 15,000 selected artists | `59aba3cf158b7cc197d1e0fc05fb2d95939b2980186d2844091b88ce7d5d9536` | `88e9bae496a387cbc636919b34332fc7fd912b9b6a5d406156d0f786bbb72d12` |
| Native credited-artist lookup | `dfd6112d20367faa5b949069b9810bbacb214ad168fc197d95cdfbab1d3dda4f` | `8f12726cc3087e4af3c9774df6cfab51fa43a74529903e8647af39c5f28dce4e` |
| Native release-group facts | `74f17a06a0832d5179cd79831aa2b136c1bef243446e109555b4e954ae469d9d` | `e2e5c03af87174a4dc9fdaa48334a2ce29360b9b6d4391233f7307f9332bb021` |

The supplemental selection logical hash is
`fcd4524e98d2da257c5980d4eabf2bf75cfbd01d9a0f5ee909fa3c2e25bb630e`.
It binds direct catalog receipt
`43593ab9702da7cc3b2c6837e96cd337cfa924556d1f931a7a383a3a00eed0b0`
and the initial rich artist receipt above.

Reproduce the supplemental selection/acquisition with:

```sh
.venv/bin/python scripts/acquire_musicbrainz_additional_artist_features.py \
  --catalog-directory .cache/musicbrainz-candidate-catalog-final \
  --existing-feature-directory .cache/musicbrainz-open-artist-features-final \
  --output-directory .cache/musicbrainz-open-artist-features-additional-15000 \
  --limit 15000
```

Add `--verify-only` to replay the sealed projection offline. Independent offline
replay passed for all four source artifacts after acquisition. The 23 focused
acquisition tests, scoped Ruff checks, and scoped Ty checks pass. Tests cover
raw tag/vote preservation, exact query/source binding, source and license byte
mutation, cohort partitioning, deterministic disjoint stratification, missing
identity abstention, native genre preservation, release-group deduplication,
and prohibited source-role changes. No model quality or full parity claim
follows merely from acquiring more descriptors; held-out evaluation and source
coverage remain separate evidence.
