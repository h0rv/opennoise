# ListenBrainz recording co-listen signal probe

This is a bounded local-only experiment. It does not change the model, static
map, discovery asset, deployment, catalog, or source vault.

## Input and boundary

The probe reads a verified retained daily archive only after checking its exact
SHA-256. It streams the archive without extraction, caps compressed and
decompressed bytes, member bytes, JSONL record bytes, active windows, users,
recordings per user-window, and candidate pairs. Listener IDs exist only in
the in-memory fixed-window accumulator. The result contains no raw listens,
listener IDs, recording IDs, pair IDs, rankings, or neighbor lookup.

The artifact at `.cache/listenbrainz-recording-co-listen-v1/artifact-bound.json` is
local only, export disabled, and serving disabled. It consumed the 222,909,169
byte retained archive with SHA-256
`690950fabaac58656df2b5e41ebf90f0f007e3e743b321c09c5c02d9e5fa757d`.
Its exact catalog-overlap input is bound to catalog SQLite SHA-256
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` and
the canonical sorted exact-recording-ID set SHA-256
`dce6e8a7f6975755318badb3b9015c48ac6e6ad06e3c83225d14711230bad8cc`.

## Bounded result

The input was the first 250,000 JSONL records encountered in that archive. It
is an archive-prefix sample, not a representative sample or an evaluation.
The privacy floor was five distinct users per 86,400-second window. Exact
catalog overlap uses only MusicBrainz recording UUIDs from the current local
catalog; no name, title, artist, or release fallback exists.

| Measure | Count |
| --- | ---: |
| Valid listens inspected | 250,000 |
| Server-resolved `mbid_mapping.recording_mbid` values | 0 |
| Submitted `additional_info.recording_mbid` valid UUIDs | 2,176 |
| Selected recording IDs | 2,176 |
| Unique selected recording IDs | 2,098 |
| Exact current catalog recording overlaps | 6 |
| Candidate co-listen pairs | 8,204 |
| Pairs meeting the five-listener floor | 0 |
| Event-time windows encountered | 6 |

The observed submitted-recording availability is 0.8704% of inspected
listens. This small probe cannot support held-out recording-neighbor quality,
artist similarity, or genre claims: no pair reached the privacy floor and the
exact catalog join is only six recordings. It does establish that raw
recording IDs are present but sparse in this retained slice, and that
server-resolved recording IDs were absent in it.

## Next decision

Do not promote this signal. Before a larger scan, measure recording-ID
availability across multiple bounded daily slices and improve exact recording
catalog coverage. Only then run a time-ordered held-out comparison against
popularity and artist-level co-listen baselines; keep all resulting artifacts
local until an independent evaluation supports a declared use.
