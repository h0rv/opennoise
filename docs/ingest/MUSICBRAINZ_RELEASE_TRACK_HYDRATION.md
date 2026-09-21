# Bounded MusicBrainz release and track metadata hydration

`opennoise hydrate-musicbrainz-releases` closes the representative catalog gap with a small, deterministic, replayable metadata slice. It starts from an existing `MetadataRepresentativeArtifact`, sorts the selected release-group and recording representative IDs, and chooses a bounded number of already-selected examples per genre (two by default; the ingest API supports up to three). A release-group seed is resolved through MusicBrainz's release-group endpoint and a recording seed through its recording endpoint. Each selected concrete release is then resolved through the release endpoint with `inc=release-groups+recordings`.

The output records concrete releases, ordered media, ordered track listings, exact MusicBrainz release/track/recording/release-group UUIDs, and duration milliseconds when MusicBrainz supplies them. Every track is marked `track_metadata_not_playable_media`. It contains no audio, preview, stream, download, artwork, cover-art, URL, genre, tag, rating, or supplementary noncommercial genre data.

The adapter is sequential by design: it shares a one request per second MusicBrainz rate boundary, identifies itself with a versioned contact user agent, and retries only transient 429 and 5xx responses up to the configured bound. Parsed safe response projections are cached by endpoint; raw API responses are deliberately not retained. Terminal adapter failures are cached as a typed endpoint, failure-kind, and bounded safe message, so an offline batch reproduces the same abstention without a network request. An online run retries a cached failure and replaces it if the endpoint recovers. `--offline` still fails on a cache miss.

The command writes canonical JSON and pushes the same bytes into the configured `ObjectStore` under `musicbrainz-release-hydrations/sha256/<sha256>.json`. The receipt reports release, medium, and track metadata counts. The retained artifact records each input's `metadata_example` classification and is independent from ranking: it does not promote a candidate, recording, or release into a published choice or into a quality, popularity, genre, or playability claim.

```sh
OPENNOISE_METADATA_REPRESENTATIVES_ARTIFACT=out/metadata-representatives.json \
OPENNOISE_MUSICBRAINZ_HYDRATION_OUTPUT=out/musicbrainz-release-tracks.json \
OPENNOISE_MUSICBRAINZ_HYDRATION_OBJECT_STORE=.cache/musicbrainz-hydration-objects \
OPENNOISE_MUSICBRAINZ_HYDRATION_CACHE=.cache/musicbrainz-hydration-cache \
OPENNOISE_MUSICBRAINZ_USER_AGENT='opennoise/0.1 (maintainer@example.org)' \
uv run poe hydrate-musicbrainz-releases
```

For a deterministic test or recovery run, use the same representative artifact and `--offline`; all needed endpoint projections must already be in the cache. A fresh network run should be intentionally small and is not part of public-model publication.
