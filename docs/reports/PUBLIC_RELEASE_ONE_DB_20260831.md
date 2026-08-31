# One database public release

`poe build-public-release` builds `data/public.sqlite` only from the two bounded Wikidata queries
and the seven pinned ListenBrainz increments dated 2026-08-24 through 2026-08-30. Start with an
absent database for a fresh release. An interrupted run can be resumed only while the database
contains this task's allowlisted public sources. The local MusicBrainz research imports use
another database and are rejected by the preflight check.

The Wikidata query runner verifies each response before the shared adapter projects it. The
ListenBrainz step verifies all seven manifest hashes, totaling 1,514,835,361 bytes, then passes all
artifacts to one joint adapter call. It never runs seven independent pair projections or sums
already anonymized counts. The joint adapter deduplicates listener and artist sets across the
whole corpus, emits disjoint UTC event-day aggregates at a privacy floor of five, and discards its
transient listener state.

The multi-artifact lifecycle records each input snapshot and provenance row. It persists the joint
records atomically under one generated content-addressed aggregate artifact and records derived
lineage to every input provenance row. A failed aggregation leaves no partial joint evidence. An
identical completed attempt is reused.

The model builder reads the same `data/public.sqlite` as both catalog and listening input. The
publisher resolves every declared model artifact back to exact provenance in that database and
selects policy 2, the bounded Wikidata genre source policy. On a nonfresh database, confirm that
policy 2 still belongs to `wikidata_public_genres_20260831` before publication.

## Verified run

The 2026-08-31 run completed on Python 3.13.14. The joint ListenBrainz pass took 536.539
seconds and used 396,005,376 bytes of peak resident memory. It read 30,469,708 listens,
including 993,589 with an artist MusicBrainz ID, and observed 79,673 artists in 40,782 user
windows. The bounded candidate stage considered 8,420,452 pairs and emitted 30,903 pair
records. One 456-byte invalid listen was quarantined as malformed. No user or raw-listen row was
persisted.

The joint ingest accepted 30,904 records in total, with no duplicates, and recorded seven
derivation edges. Its generated aggregate SHA-256 is
`6c30524486b47af9fe0fe554830b50639f716ba39e265c7560d60b84124208b7`.

The final exact Wikidata enrichment boundary contains 140 QIDs. Its query SHA-256 is
`4564bdc178e49efee7eacf0fd936da604ace356c8e541c58fac35eb1fb2c0379`; the verified response
SHA-256 is `f397ec0fabc8918c17e1ca6cef17301e61c89d33ee42b08ee5a8e515b43c1976`.
It accepted all 140 entity projections, quarantined none, and left no identifier-only display
name in the selected model.

The selected public model is revision 2 with logical output SHA-256
`24d75a2f13708aa5434c30f0bbcc8bac4179aae23a8b8b2bdeb05add9c14b9e4`. It contains 71
named genres, 20 placed genres, 113 representative metadata links, and 60 direct P279 edges
whose endpoints both occur in the model. The JSON artifact is 145,603 bytes with file SHA-256
`741bf224fbf2d6688905147b819ec35f372aaa5b0d7b73043bce0cb503c28071`.

The integrated SQLite database is 109,432,832 bytes with file SHA-256
`2d5a8a0a921f02088b685d861fdc25e8d98d845fb395ef4b3e840d3711c4e9e9`. SQLite's integrity
check returns `ok`. These file hashes describe this completed local run; the recorded source,
query, aggregate, and logical model hashes are the reproducibility boundary.
