# MusicBrainz direct publication gate

The local-only `musicbrainz-direct-publication-gate-v1` is a bounded review
receipt, not a release input. It streams the retained MusicBrainz seed-target
archive, accepts only literal exact proper-genre artist observations with an
exact UUID MBID, exact `musicbrainz:artist:<MBID>` record ID, source-record
SHA-256, source evidence reference, and a target genre ID already reconciled
to the retained seed. Tags, release/support rows, peer rows, inferred rows,
and historical assignments are not read.

## Measured retained-input scan

The 2026-09-22 scan of the 682 MiB local seed-target archive found 389,131
distinct exact source proper-genre rows over 875 seed IDs and 198,875 MBIDs.
The stricter reconciliation-safe receipt retained 387,435 rows over 697 seed
IDs and 198,409 MBIDs. Its semantic-map-v3 overlap was 686 placed seeds and
11 unplaced seeds.

This does not establish the broader 2,377-seed direct frontier. That number
is from the separate release direct-anchor/evidence graph, which this gate
does not read because release evidence is not an artist-direct fact.

The compact receipt stores counts, a deterministic claim-stream SHA-256, and
a 64-row exact-provenance sample. It does not materialize a large membership
JSON. A path-based verifier rebuilds it from the pinned layout,
reconciliation, and source archive; a self-hash alone is therefore not
treated as source verification.

## Status

Publication remains blocked. The adapter continues to declare
`export_allowed=false`, and the gate fixes `public_export_authorized=false`.
The receipt is about 31 KiB but depends on the ignored local 682 MiB source
archive. It is not fresh-checkout portable custody, a published claim set, or
a change to static release policy.

Rebuild locally with:

```sh
.venv/bin/python scripts/build_musicbrainz_direct_publication_gate.py \
  --layout .cache/semantic-map-layout-v3/artifact.json \
  --reconciliation .cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json \
  --seed-target .cache/musicbrainz-full-seed-targets/musicbrainz-seed-targets-v1.json \
  --output /tmp/musicbrainz-direct-publication-gate.json
```
