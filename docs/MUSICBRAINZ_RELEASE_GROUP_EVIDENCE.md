# MusicBrainz release-group artist support

The release-group expansion is a local, research-only source. It uses the
official MusicBrainz JSON release-group dump pinned in `config/data_sources.toml`:
snapshot `20260905-001001`, `release-group.tar.xz`, 1,159,485,640 bytes, SHA-256
`6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43`.
Its sole `mbdump/release-group` member is 18,124,249,055 expanded bytes. The
builder records that member size in its artifact and applies a 20 GiB default
member ceiling: tight enough to reject unexpected expansion while allowing the
pinned dump.

Acquire exactly that one raw source before building. The source-cache command
uses one worker, places raw bytes under their SHA-256 object key, and writes a
local-vault receipt. A partial transfer is never input to the builder.

```sh
uv run poe cache-musicbrainz-release-group-20260905
uv run poe build-musicbrainz-release-group-evidence
```

Checkpoint status: the verified source archive and
`.cache/musicbrainz-release-group-source-receipt.json` are present. No
release-group evidence artifact or publication receipt exists. The old
`.cache/musicbrainz-release-group-evidence/evidence.sqlite` is malformed
staging data and must not be reused. The example environment sends a new build
to a separate `musicbrainz-release-group-evidence-candidate-v1` directory
and keeps the verified raw source receipt immutable. A new build writes only a
`<database>.partial` staging SQLite file, uses durable checkpoints, and runs
SQLite integrity validation before atomically replacing the final *database*
path. An interrupted partial is retained for inspection; there is no automated
resume, and no artifact or receipt is published until the completed database
has passed that boundary.

The builder requires the source-cache receipt and independently verifies the
archive size and SHA-256 before decompression. It streams `mbdump/release-group`
into SQLite and does not read release, recording, audio, artwork, preview, or
H3 data.

Artist-dump seed matches remain `artist_direct`. A release-group `genres` or
positive-count `tags` claim joined through an artist-credit MBID becomes only
`release_group_support`. The SQLite `typed_evidence` table carries the two
evidence kinds explicitly. It retains source facet (`musicbrainz_genre` or
`musicbrainz_tag`) and a deterministic release-group provenance reference.

To avoid a prolific discography creating an unbounded vote, support is capped
at three release groups per `(seed, artist, facet)` by default. The compact
Pydantic artifact and publication receipt record both the capped SQLite hash
and the source-cache receipt hash. Coverage reports support-only genre and
membership additions plus a deterministic 20% held-out direct-anchor recovery
measurement. It is a separate local research source and does not alter public
direct membership facts.
