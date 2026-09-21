# MusicBrainz artist-credit materialized candidate

This is a fresh, local-only SQLite candidate. It is not public, sealed, or
serving input, and its creation did not open or mutate any existing candidate,
public, or sealed database.

The authoritative candidate database is
`.cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final.sqlite`
with SHA-256
`100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63`.
Its local report is
`.cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final-report.json`.
Its SHA-256 is
`f9ab6d74552935ecf198e28ea9f3875caf67cfcad9ee95883328c59954fcde00`.
The v2 report records this exact database path and repeats its byte SHA-256,
making the report an explicit binding to the finalized candidate file.

It is bound to the exact core hydration SHA-256
`9d2a7925eddf2cbf0260e502ca2b71d0a4ec92ac953d9e630f836adc08836ce3`
and independently audited v2 artist-credit artifact SHA-256
`6454e5bfa4b4062e0bb7303629e0b5380af9997518ce386b896de69597496b7d`.
Before SQLite staging, the materializer reparses and rehashes both artifacts,
recomputes all 87 referenced cache projection hashes, and confirms every
source cache projection exactly reproduces its release or recording relation
and ordered credit members.

The candidate has 87 release relations, 1,031 recording relations, 1,344
ordered relation-member rows, and 352 artist entities identified only by exact
MusicBrainz MBID. It has two provenance records: one for core hydration and a
separate one for the artist-credit artifact. Foreign-key checking reports zero
violations. Core hydration's first pass inserted 87 releases, 94 media, 1,032
tracks, and 1,031 recordings; its immediate replay inserted zero rows.

Reproduce only to an unused target path:

```sh
uv run python scripts/materialize_musicbrainz_artist_credit_catalog_candidate.py \
  --hydration-artifact .cache/musicbrainz-catalog-expansion-v1/release-tracks.json \
  --credit-artifact .cache/musicbrainz-catalog-expansion-v1/artist-credit-refresh-candidate-v2-offline.json \
  --cache-directory .cache/musicbrainz-catalog-expansion-v1/artist-credit-refresh-escalated-v2 \
  --database .cache/musicbrainz-catalog-expansion-v1/another-unused-artist-credit-candidate.sqlite \
  --report .cache/musicbrainz-catalog-expansion-v1/another-unused-artist-credit-candidate-report.json
```

Publication stages a new SQLite file and uses atomic no-replace publication.
An existing or symlink target is rejected and never reused or mutated.
The report is also atomically no-replace published only after the database is
finalized and its SHA-256 has been read. If report publication fails, the
database remains an explicit orphaned local candidate and the command fails.
