# MusicBrainz derived entity tag adapter checkpoint

The local adapter verifies the exact byte count and SHA-256 declared for
`musicbrainz_postgres_derived_20260829` before it opens the archive. It streams
the `mbdump/tag` lookup and then streams `mbdump/recording_tag`,
`mbdump/release_tag`, and `mbdump/release_group_tag` in separate passes. It writes no data and exposes no public
model, export, or serving path.

Fixture replay covers positive entity-native tag counts, the three requested
entity tables, and rejection for altered bytes, a missing member, an unknown
tag foreign key, a nonpositive count, and an unsafe member path. Artist tags
are intentionally outside this first adapter. The parser decodes standard
PostgreSQL COPY text escapes and rejects unsupported escapes.

The 513,721,489 byte declared archive is absent locally, so no real archive
member names, row order, row counts, or full-dump limits have been verified.
The derived archive alone cannot establish an official MusicBrainz genre. The
adapter emits a genre fact only when a caller supplies an exact tag-ID mapping
from an official genre table or mapping. The adapter does not verify that map,
and no supplied map or receipt currently establishes a real genre identity or
MusicBrainz genre MBID. It never treats a matching tag label as a genre
identity.
