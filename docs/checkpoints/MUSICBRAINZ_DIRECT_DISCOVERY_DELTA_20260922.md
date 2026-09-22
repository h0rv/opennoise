# MusicBrainz direct discovery delta

This local review report compares only the verified portable MusicBrainz
proper-genre custody object with the current certified static discovery asset.
It does not create memberships, change the map, or write `dist`.

## Inputs

The report verified the portable custody receipt and its content-addressed
object before it read any claims. It also verified the current static discovery
asset and semantic atlas against `dist/opennoise-static-manifest.json`.

| Input | SHA-256 |
| --- | --- |
| Custody receipt output | `a6f874aea86f66519801b4b61f89d8150a4102a8c9266ed8f9ad31ceebf54bd9` |
| Custody claims object | `b1fc1ac9428832cb4543710b716e2d47eb8cc62dc052ed4d768ffb27dd1dcc3e` |
| Current static discovery | `4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c` |
| Certified semantic atlas | `730bca93300870d35b527f377eb883ae95a3f931aad7e820b013fa592c5bf4ac` |

## Results

The custody object contains 697 direct seed IDs. The current static discovery
has 344 IDs. Their exact ID intersection contains 274 IDs, so 423 custody IDs
are candidate-only. The candidate-only IDs contain 412 placed atlas nodes and
11 unplaced nodes.

| Scope | Observations | Distinct seed and MBID pairs | Artist MBIDs | Source records | Source evidence references |
| --- | ---: | ---: | ---: | ---: | ---: |
| All verified direct custody | 387,435 | 387,435 | 198,409 | 198,409 | 387,435 |
| Shared with current static discovery | 248,037 | 248,037 | 140,574 | 140,574 | 248,037 |
| Candidate-only | 139,398 | 139,398 | 103,838 | 103,838 | 139,398 |

The report emits one ID-only count row for each of the 423 candidate-only
seeds. A reviewer can use 139,398 distinct seed and MBID pairs as a bounded
review queue. Each future review row must retain only these custody fields:
`seed_id`, `artist_mbid`, `musicbrainz_genre_id`, `source_record_id`,
`source_record_sha256`, and `source_evidence_ref`.

## Limits

The custody object has no exact source-bound artist name field. This report
therefore abstains from artist display-name coverage and from a static UI JSON
size estimate. A static UI cannot publish these candidates without separately
approved source-bound names, or an explicit display abstention. No tags,
aliases, inferred mappings, historical assignments, release rows, or peer rows
were read.

Both `public_export_authorized` and `release_gate` are fixed to `false`.

## Local reproduction

```sh
.venv/bin/python scripts/report_musicbrainz_direct_discovery_delta.py \
  --custody-receipt config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json \
  --custody-object-store data/release/musicbrainz-direct-proper-genre-custody-v1/objects \
  --static-discovery dist/assets/static-discovery.4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c.json \
  --certified-manifest dist/opennoise-static-manifest.json \
  --certified-layout dist/assets/semantic-atlas.730bca93300870d35b527f377eb883ae95a3f931aad7e820b013fa592c5bf4ac.json \
  --output /tmp/musicbrainz-direct-discovery-delta.json
```

The writer creates a new file atomically and refuses to replace an existing
review report.
