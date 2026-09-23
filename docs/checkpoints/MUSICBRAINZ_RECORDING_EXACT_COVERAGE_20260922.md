# MusicBrainz exact recording lookup coverage

This is a local-only feasibility probe. It changes no release catalog, model,
map, static asset, source vault, or deployment. It is not a canonical-recording
redirect result and it does not estimate coverage for the complete cohort.

## Source route and bulk blocker

The official [canonical data documentation](https://musicbrainz.org/doc/Canonical_MusicBrainz_data)
describes the canonical recording mapping as the three columns
`recording_mbid`, `canonical_recording_mbid`, and `canonical_release_mbid`.
That mapping has no artist credit. The canonical metadata table does contain
artist-credit IDs, but the current official [canonical-data index](https://ftp.musicbrainz.org/pub/musicbrainz/canonical_data/musicbrainz-canonical-dump-20260917-080002/)
offers both tables only inside one 2 GB `.tar.zst` archive. It exposes no
per-table/member object or compact exact-ID bulk endpoint. Downloading it is
outside this bounded experiment.

The official [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API)
documents an exact recording lookup at `/recording/<MBID>` and the
`artist-credits` inclusion. It documents an individual lookup, not a multiple
recording-ID batch. Therefore it can establish direct recording identity and
artist-credit cardinality for a small sample, but would require about 2,098
requests for the full cohort. That is deliberately not run.

## Frozen 24-ID feasibility prefix

The first receipt at
`.cache/listenbrainz-musicbrainz-recording-coverage-v1/artifact.json` has SHA-256
`442302900373b31bd41d9fb8420a1714f0db9943c756ced46c7185bda910faa5`. It uses
the first 24 lexically sorted UUIDs from the existing 2,098-ID local cohort,
whose source and full-set hashes remain bound in the receipt. This is a
deterministic prefix convenience sample, not a random sample and not a
representative estimate for all 2,098 IDs. It retained response hashes but not
raw bodies, so it is an observation-only result and cannot prove an offline
artist-credit replay. It is superseded by the v3 custody-backed receipt below.

The accepted cohort file is
`.cache/listenbrainz-recording-id-cohort-v1/artifact.json`, SHA-256
`869c205921afb668585d2357ecb94302475aa90e589bec2426f85c0def2f5f6a`.
The current runner requires that value from the caller and verifies it before
opening the MusicBrainz connection. A structurally valid but substituted cohort
therefore fails before it can produce a receipt.

The fresh v3 receipt at
`.cache/listenbrainz-musicbrainz-recording-coverage-v3/artifact.json` has
SHA-256 `5513b41dbdf87b7651c31c33f9af4ccb6e39faefe410212b1dec0d5e608c3496`.
Its sequential, one-request-per-second run made 24 exact API calls from
2026-09-23T01:24:14Z through 2026-09-23T01:24:37Z. Every response was HTTP 200,
had the exact requested recording UUID, and carried at least one artist-credit
artist ID. Five of 24 responses had more than one credited artist; the 24
credits contained 39 distinct artist IDs.

The v3 receipt binds every raw response to a SHA-256 and byte count. Its 24
objects (14,456 bytes total) live only under
`.cache/listenbrainz-musicbrainz-recording-coverage-v3/raw-responses/sha256/`.
Those objects are raw MusicBrainz JSON and can contain recording titles and
artist-credit display names. They are a bounded, local-only custody cache, are
not included in this checkpoint or any public/static artifact, and are used
solely for offline validation of the safe receipt projection.
The report retains only requested and returned recording UUIDs, artist UUIDs,
HTTP status, UTC fetch time, and content-object receipt; it has no titles,
display names, releases, audio, or genres. A strictly offline parser replay
rehashes every object and reproduced the v3 receipt exactly (`True`), without
making a network call.

404, redirect, other HTTP-error, invalid-body, and nonexact-ID outcomes are
explicit abstentions in the measurement code. They do not become alias joins or
recording-to-artist claims.

## Frontier

The compact canonical dump route is blocked by the 2 GB all-in-one archive;
the documented API has no bulk exact-ID lookup. A safe next route needs an
official, compact, receipt-verifiable extraction of the two canonical tables,
or explicit authorization for a much larger rate-limited API campaign. Neither
is implied by this 24-ID feasibility result.
