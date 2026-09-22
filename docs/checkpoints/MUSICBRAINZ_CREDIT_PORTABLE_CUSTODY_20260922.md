# MusicBrainz credit portable custody

The retained MusicBrainz artist-credit candidate is now available from a fresh
checkout without reading `.cache` or making a network request. This is source
custody and a byte-pinned catalog artifact, not deployment approval.

`config/releases/musicbrainz-credit-catalog-v1/custody-scope.json` declares
the only permitted purpose: artist-detail credit metadata under the existing
`musicbrainz-core-metadata-hydration` policy. It explicitly excludes name
inference, genre or membership claims, discovery changes, audio, previews,
artwork, and deployment.

The portable receipt is
`config/releases/musicbrainz-credit-catalog-v1/portable-release-receipt.json`.
It binds these checked-in object-store members:

- 87 exact `release/{MBID}` safe projections in one 1,373,662-byte source
  object, SHA-256 `13921b94a5a0c77c625713b5e272d40d081c67de3eb5b1299c8c1c48baf6d6ba`.
- Hydration artifact SHA-256
  `9d2a7925eddf2cbf0260e502ca2b71d0a4ec92ac953d9e630f836adc08836ce3` and
  artist-credit artifact SHA-256
  `6454e5bfa4b4062e0bb7303629e0b5380af9997518ce386b896de69597496b7d`.
- The 3,072,000-byte materialized SQLite catalog, SHA-256
  `100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63`, and
  its report SHA-256
  `f9ab6d74552935ecf198e28ea9f3875caf67cfcad9ee95883328c59954fcde00`.

Restoring the catalog verifies all object hashes and the report-to-database
binding. Replaying the checked-in safe projections independently verifies all
87 v2 projection hashes and reproduces 87 release relations, 1,031 recording
relations, 1,344 ordered credit members, and 352 exact-MBID artists. SQLite
creation timestamps make a newly materialized database byte-distinct, so the
receipt pins and restores the original catalog bytes while the source replay
checks semantic provenance and coverage.

Run the fresh-checkout restore with an unused destination:

```sh
uv run python scripts/materialize_musicbrainz_credit_portable_release.py \
  --receipt config/releases/musicbrainz-credit-catalog-v1/portable-release-receipt.json \
  --object-store data/release/musicbrainz-credit-catalog-v1/objects \
  --candidate-database /tmp/musicbrainz-credit-catalog.sqlite \
  --candidate-report /tmp/musicbrainz-credit-catalog-report.json
```

Remaining production work is deliberately separate: create a real deployment
approval binding the public database, v2 discovery asset, and final credit
asset; integrate only into artist-detail UI; then pass `poe build` browser
certification before deployment. No static asset was added or deployed here.
