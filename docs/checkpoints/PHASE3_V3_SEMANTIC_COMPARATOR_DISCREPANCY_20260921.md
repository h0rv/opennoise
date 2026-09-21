# Phase 3 v3 semantic comparator discrepancy (2026-09-21)

The hash-pinned, read-only comparator finds the model projections, 30,903
co-listen windows, 13,175 artist-pair aggregates, 2,002 layout coordinates,
and provenance-binding row counts equal between v3 and sealed inputs. It fails
overall because one normalized provenance binding is unique to each side.

| Field | v3 | sealed |
| --- | --- | --- |
| Source key | `listenbrainz_joint_20260824_20260830` | same |
| Snapshot / source artifact / bound artifact | `listenbrainz_joint_20260824_20260830:joint:6c30524486b47af9fe0fe554830b50639f716ba39e265c7560d60b84124208b7` / `6c30524486b47af9fe0fe554830b50639f716ba39e265c7560d60b84124208b7` / same | same |
| Parser release | `listenbrainz_incremental_listens_v1:1.0.0:7627291b1acc30a6f7f11c8c300cd40d7b676780871ac21ce45604e9147def3b` | same |
| Provenance record fingerprint | `b759b28149d3a9576c09aa456c0f4a6b2f8fca3fb423bd8cb080075872727920` | `3d3ddb75e9f8d31097eb6d33b0c6bb047087164089087df53a2e544ded84601e` |

This is not only a construction timestamp difference. The linked normalized
`artist_co_listen_run` records have identical fixed-window configuration and
aggregate counts, but different generated external IDs, adapter-build SHA-256
values, elapsed times, and peak RSS. The v3 row was observed at
`2026-09-21T19:00:53.397Z`; the sealed row at `2026-08-31T23:52:18.059Z`.
The comparator retains the fingerprint and exits nonzero for this pinned pair.
