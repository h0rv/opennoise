# Artist-backed release expansion

The certified public cache has 787 CC0 Wikidata release groups, 4,948 direct
CC0 Wikidata artist-to-genre observations, and no concrete releases or tracks.
This builder makes a bounded, new core-metadata slice from that gap.

It first chooses CC0 Wikidata P136 release-group rows. For each selected genre,
it carries only direct CC0 Wikidata artist-to-genre anchors with exact
MusicBrainz artist IDs. MusicBrainz then supplies a release group's artist
credits and concrete releases. A release is retained only when one returned
credited MusicBrainz artist matches a retained direct artist-to-genre anchor for
the same Wikidata genre. MusicBrainz genres and tags are never read.

The artifact contains exact source observation IDs, policy/provenance IDs,
canonical MusicBrainz projection hashes, core release metadata, ordered media,
and ordered track metadata. Tracks are always
`track_metadata_not_playable_media`. It has
no audio, previews, media files, artwork, URLs, MusicBrainz genres/tags,
popularity, ratings, listener data, quality, or "defining album" claim.

Every seed has either retained releases or an explicit abstention: no matching
direct artist credit, no concrete release, or unavailable MusicBrainz metadata.
The report records both counts and proves an offline replay from the safe
endpoint cache is byte-identical. The final JSON is stored under
`artist-backed-release-expansions/sha256/<hash>.json` through the normal object
store abstraction.

The command also makes a new serving SQLite by backing up the source first. It
checks every retained release's album and direct-artist evidence IDs before
materialization, runs SQLite integrity and foreign-key checks, verifies the
genre → evidence → release-group → release product join, and materializes the
same artifact again to prove zero duplicate inserts. The certified source file
is never opened for writing. Operational cache path, retry count, and offline mode are not
part of the semantic plan hash, so identical source and bounds have identical
artifact identity across cache locations.

```sh
MUSIX_ARTIST_BACKED_RELEASE_SOURCE_DATABASE=/path/to/phase3-public-qualified.sqlite \
MUSIX_ARTIST_BACKED_RELEASE_DATABASE=out/artist-backed-serving.sqlite \
MUSIX_ARTIST_BACKED_RELEASE_OUTPUT=out/artist-backed-releases.json \
MUSIX_ARTIST_BACKED_RELEASE_OBJECT_STORE=out/objects \
MUSIX_ARTIST_BACKED_RELEASE_CACHE=out/musicbrainz-cache \
MUSIX_ARTIST_BACKED_RELEASE_REPORT=out/report.json \
MUSIX_MUSICBRAINZ_USER_AGENT='musix/0.1 (maintainer@example.org)' \
uv run poe build-artist-backed-release-expansion
```

The default is 48 genres with up to two release-group seeds and one concrete
release per seed. The extra seed bound gives the real build enough candidates
to exceed the previous 20-release serving slice even when some seeds abstain.
The adapter is intentionally sequential and rate-limited to one MusicBrainz
request per second. Run `scripts/build_artist_backed_release_expansion.py`
with `--offline` only after the matching cache has been acquired.
