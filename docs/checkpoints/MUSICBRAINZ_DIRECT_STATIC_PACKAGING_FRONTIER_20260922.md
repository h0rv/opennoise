# MusicBrainz direct static packaging frontier

This is a read-only sizing and delivery audit for a possible future, separately
authorized direct artist catalog. It does not create a payload, authorize
publication or serving, modify `dist`, run a build, or change the current v2
release.

## Measured boundary

The exact-MBID name-join checkpoint has 115,269 named candidate-only direct
artist--genre pairs on 412 placed candidate-only seeds. Its deterministic
minimal JSONL shape (`artist_mbid`, `canonical_name`, and `seed_id`) is exactly
12,206,295 uncompressed bytes, or 105.89 bytes per pair. This is a lower-bound
candidate shape only: it has no production envelope, evidence, hash, source,
or authorization semantics. See [the name-join checkpoint](MUSICBRAINZ_DIRECT_NAME_JOIN_FRONTIER_20260922.md).

The current certified single-file v2 discovery asset is 2,865,604 raw bytes
and 288,854 gzip bytes for 3,859 evidence rows, 3,484 memberships, 344 genres,
and 1,126 artists. A mechanical same-schema extrapolation is about 85.7 MiB
raw and 8.6 MiB gzip for 115,269 rows. It is not a forecast: the current format
duplicates artist memberships in genre and artist views and retains bounded
shared-artist records, while the 12.2 MB JSONL number intentionally does not.

## Small static-only path if later authorized

Keep the atlas and v1/v2 assets unchanged. Use a separately reviewed sharded
discovery revision with a small, fingerprinted manifest. Stream one
content-addressed genre chunk per placed genre and split at 1,000 direct pairs:
412 chunks is the minimum here and 527 is the maximum at this pair count. The
minimal-row bound is about 104 KiB raw per full chunk; a real release must
record and gate each emitted raw and gzip byte count rather than treat that
bound as a production size.

The manifest should map each map genre to its chunks and hashes, describe
lazy artist-search partitions, and list deterministic artist-profile buckets.
Load a genre only after it is opened; load a search partition only after a
two-character query; load an artist bucket only after artist selection. Cache
immutable URLs with a small browser LRU, show a bounded initial genre list on
mobile, and never prefetch the catalog. Preserve direct-source evidence and
reciprocity checks. Do not calculate unbounded related-artist pairs: the
current exporter forms pairs within each genre, so a high-fanout future genre
needs an explicit guard or an unavailable related-artists state.

## Required release checks

After authorization, add deterministic chunk-boundary and replay tests;
require pair uniqueness, genre/artist reciprocity, source and coverage
accounting, and SHA-256/byte-count validation for every manifest entry. Extend
the existing browser certification with lazy genre, search, artist deep-link,
missing-chunk, cache, and mobile-list bounds. Keep the existing immutable
asset cache policy and run the normal `poe check` and authorized build/deploy
gates only then.
