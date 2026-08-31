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
