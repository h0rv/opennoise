# Phase 3 source-vault replay timestamp delta

This is a bounded, read-only comparison of the retained historical-declaration
candidate and the sealed public database. It changes no candidate, vault,
sealed input, public database, model, static artifact, or deployment.

## Bound inputs

| Input | SHA-256 |
| --- | --- |
| historical-declaration candidate | `327bbf377cb9ad8a1ed48821718979606622175f255ece5958d674146aba6763` |
| sealed public SQLite | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |

Both files are schema 12. The comparison joined `source_snapshots` by its
shared `snapshot_ref`, then compared the persisted `acquired_at` field.

## Exact remaining difference

All 62 matching `source_snapshots.snapshot_ref` rows have unequal
`acquired_at` values. For example:

| source key | historical candidate `acquired_at` | sealed public `acquired_at` |
| --- | --- | --- |
| `listenbrainz_incremental_20260824` | `2026-09-21T18:55:23.639Z` | `2026-08-31T23:48:00.847Z` |
| `listenbrainz_incremental_20260825` | `2026-09-21T18:55:23.640Z` | `2026-08-31T23:48:00.848Z` |
| `listenbrainz_incremental_20260826` | `2026-09-21T18:55:23.641Z` | `2026-08-31T23:48:00.849Z` |

The sorted `source_key|acquired_at` projections therefore hash differently:

| Projection | Rows | SHA-256 |
| --- | ---: | --- |
| historical candidate | 62 | `eca10b0cd4814b873d600446366d753eb1b143e147272ae47e2d5df5008a8b0b` |
| sealed public | 62 | `d404463c96e15ec70532af7d77cdca35db9c1d8ba55d6e0d37c43f2a4fc9678c` |

This confirms one exact cause of non-byte-identical SQLite output: replay
persists current ingestion/acquisition timestamps rather than the sealed
historical values. It is evidence only, not certification or permission to
copy, replace, or normalize timestamps in either database.

## Bounded replay improvement

The combined 62-object replay now rehashes its complete manifest-bound vault
after both projectors finish and before checkpoint/publication. This detects a
persistent raw-object mutation that occurs during the long replay, before a
candidate can be published. It is not a full time-of-check/time-of-use closure:
an object changed and restored between the two hash passes is outside this
bounded check. A fixture mutates a raw object during replay and confirms that
no candidate database is published.
