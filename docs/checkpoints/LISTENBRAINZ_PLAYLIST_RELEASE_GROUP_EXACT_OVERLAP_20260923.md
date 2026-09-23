# ListenBrainz playlist to MusicBrainz release-group exact overlap

This is a local-only UUID join across retained source artifacts. It does not
interpret playlist membership as genre evidence, artist membership, or a
curation-quality signal. The report is
`.cache/listenbrainz-playlist-release-group-overlap-v1/report.json`; its
logical SHA-256 is
`8b237db0f84561b3b2389cb81c69c4151a254cda9f115972ce10ac0edfb6852a`.

The retained ten-playlist bundle contains 527 distinct exact recording UUIDs.
Every snapshot retains `curator_kind=unknown`. The separate route receipt
classifies its listing route as `user_created`, which does not establish
human, manual, or editorial curation. The bundle SHA-256 is
`2166a81d5f4f217971c38c2af6131e1c8e82b493851b3d6dab1c1b6a9466920c`.

Two retained MusicBrainz catalogs give different exact recording coverage:

| Catalog | Recording UUIDs | Playlist UUID overlap | Release-group path |
| --- | ---: | ---: | --- |
| `data/public.sqlite` | 623 | 11 of 527 | No track rows are retained, so no release-group path is available. |
| Artist-credit materialized candidate | 1,031 | 2 of 527 | Two exact recording-to-release-group paths. |

The artist-credit candidate is pinned by database SHA-256
`100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63`. The
public catalog is pinned by SHA-256
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`. The
join uses each database's semantic `identifier_types.type_key`, not numeric
type IDs, and deduplicates repeated track paths while preserving multiple
release groups per recording.

The two release-group IDs were looked up by exact UUID in the retained pinned
2026-09-05 MusicBrainz release-group archive. The scan verified the 1,159,485,640
byte archive SHA-256
`6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43` and the
source-cache receipt SHA-256
`2b2ae54fe057e5dd41d46a3a8ebeafad698a6ce8474135780ffd3b988c5c1dde`. It
streamed 4,499,326 records, counted 40 malformed records and zero over-limit
records, and found both requested release groups. One group has no retained
proper genre and one positive tag (`shoegazer`, count 1). The other has three
native proper genres (`blues`, `jazz`, `soul`, each count 1) and three positive
tags with those same names and counts; the cross-facet name match does not
collapse a tag into a proper genre.

These facts describe only the two exact release groups reached from this
single-account playlist cohort. No genre was assigned to a playlist or
recording, and no support was promoted to an artist claim. The report fixes
`export_allowed=false`, `serving_allowed=false`, and
`model_input_allowed=false`.

The focused fixture covers exact UUID joining, shuffled database-local
identifier type IDs, rejection of a wrong Wikidata identifier, duplicate path
deduplication, source-role retention, source hash rejection, and deterministic
report-hash replay. Run it with
`python -m unittest tests.analysis.test_listenbrainz_playlist_release_group_overlap`.
