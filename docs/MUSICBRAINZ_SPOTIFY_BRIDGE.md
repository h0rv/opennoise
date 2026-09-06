# MusicBrainz to Spotify artist bridge

`musicbrainz_spotify_bridge.py` creates a bounded, hash-sealed identity bridge from
MusicBrainz artist JSON to the Spotify artist IDs present in the immutable historical
H3 membership database. It reads artist metadata and relation URLs only. It does not
read recordings, releases, audio, or media bytes.

MusicBrainz JSON uses the nested relation shape
`relation["url"]["resource"]`. The adapter keeps the original URL as evidence and
stores a canonical URL for stable validation. Provider parsing is behind a small URL
registry so another metadata provider can be added without changing the join logic.

The historical H3 database is a positive-observation boundary. Its 306,136 rows
contain 240,007 distinct non-null Spotify IDs. These are unranked observed positive
artist samples, with at most 50 observations per genre, not complete memberships;
their absence is not a negative label. The bridge counts the historical universe and
reports which IDs have a unique bridge.

Spotify IDs are identity-join keys only. No Spotify content, audio, Spotify audio
features, API-derived attributes, or Spotify-trained representation enters the open
model. This follows the platform and source-policy constraints recorded in
[`EVERY_NOISE_PRIOR_ART.md`](EVERY_NOISE_PRIOR_ART.md#spotify-and-archive-constraints).

Identity handling is explicit:

- One MusicBrainz artist may have multiple Spotify aliases. Those rows are retained and
  counted as aliases.
- One Spotify ID claimed by multiple MusicBrainz artists is ambiguous. Every affected
  pair is retained as `conflict` and must not be promoted as a unique identity.
- Every retained row carries the source archive hash, record ordinal, record hash and
  source URL. Archive, record, relation and output bounds are included in the settings
  hash.

The fixture tests cover nested URLs, query and trailing-slash canonicalization,
duplicate claims, malformed URLs, aliases, reverse collisions, tampering, source-schema
failure and extraction bounds.

## Build

Do not run the full archive scan concurrently with another scan. After coordination,
run:

```sh
poe build-musicbrainz-spotify-bridge
```

The task expects these environment variables:
`MUSIX_MB_ARTIST_ARCHIVE`, `MUSIX_HISTORICAL_MEMBERSHIP_DATABASE`,
`MUSIX_MB_SPOTIFY_BRIDGE_OUTPUT`, `MUSIX_MB_SPOTIFY_BRIDGE_OBJECT_STORE`, and
`MUSIX_MB_SPOTIFY_BRIDGE_RECEIPT`.
