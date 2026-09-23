# MusicBrainz release group Album example candidate adapter

The local adapter at
`src/opennoise/ingest/musicbrainz/release_group_album_examples.py` completed one
replay of the pinned 2026-09-05 MusicBrainz release-group JSON archive. The
persisted report is `.cache/musicbrainz-release-group-album-examples-v1/report.json`.
Its 1,159,485,640 source bytes have SHA-256
`6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43`. The
report records 4,499,326 raw records, 40 malformed records, no over-limit
records, 4,499,286 parsed release groups, and 2,315,330 Album release groups.
It records 2,827,660 positive native proper-genre observations and 2,317,369
exact seed-positive observations. The report contains 893 seed rows and 4,238
retained examples.

The report gives examples ranked by positive native proper-genre vote count.
For ambient, it lists *Selected Ambient Works, Volume II* (18) and *Ambient 1:
Music for Airports* (17). For hyperpop, it lists *10,000 gecs* (7) and *1000
gecs* (6). For post punk, it lists *Unknown Pleasures* (17) and *Closer*
(13). These are source-context examples ranked by native genre votes. The
ranking does not identify a defining album or assert artist membership.

Source: `.cache/musicbrainz-release-group-album-examples-v1/report.json`,
seed rows `ambient`, `hyperpop`, and `post punk`.

The persisted report passed Pydantic JSON parsing and logical hash replay.
Its logical `output_sha256` is
`1b252f2b16f9cff55754acd7c1db419a926d58b01b169c977462b5fc42b98f74`. The
serialized report file SHA-256 is
`1244d97da606ace2ffd1e5c71b0431fe2e8783bcf6844a8848c4be60ed6f075f`. The
source cache receipt SHA-256 is
`2b2ae54fe057e5dd41d46a3a8ebeafad698a6ce8474135780ffd3b988c5c1dde`.
The fixed v3 seed reconciliation SHA-256 remains
`a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0`.

The adapter verifies the pinned archive bytes and source cache receipt. It also
checks the fixed v3 seed reconciliation byte hash
`a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0` and its
6,291 exact normalized seed names before it reads release-group rows.

The stream accepts a row only when its MusicBrainz `primary-type` is `Album`.
For each positive native proper genre observation, it joins the normalized
native genre name to one exact normalized seed name. Native tags are not used.
The report keeps a separate context row when one Album has proper genres that
join to different seeds.

Each retained row records the exact release-group MBID, title, first release
date, ordered credited artist MBIDs, secondary types, source record hash,
native proper genre UUID, native genre name, and positive native vote count.
Secondary types remain source metadata. The adapter does not filter
compilations, soundtracks, live releases, or any other secondary type.

For each seed, the stream retains at most five unique release groups by default.
It orders candidates by descending native positive vote count and then by
release-group MBID. If multiple proper genre UUIDs on one release group
normalize to the same seed, it keeps the higher vote and then the lower genre
UUID. The full observation counters still include every matching positive
observation, including rows outside the retained five.

The Pydantic report fixes its logical hash and marks itself local only, not
exportable, not serving input, not model input, and not an artist membership or
editorial status claim. It does not designate a defining or quintessential
album. The create-only script writes only under `.cache` and refuses an
existing output.

The fixture test covers signed vote exclusion, non-Album exclusion, exact name
matching, per-seed bounded retention, same-release-group genre deduplication,
stable tie ordering, source-order artist credits, secondary types, and report
hash replay. Focused Ruff, ty, and unit checks passed before the archive replay.
