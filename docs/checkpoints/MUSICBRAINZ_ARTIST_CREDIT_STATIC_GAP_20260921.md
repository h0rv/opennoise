# MusicBrainz artist-credit static gap

This is a read-only, exact-MusicBrainz-ID audit of the 20 candidate artists
that have public direct claims but are absent from static discovery. It changes
no database, static asset, map node, bridge, membership, or serving output.

## Hash-bound inputs

| Input | SHA-256 |
| --- | --- |
| Local artist-credit candidate | `100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63` |
| Public SQLite | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |
| Semantic atlas | `730bca93300870d35b527f377eb883ae95a3f931aad7e820b013fa592c5bf4ac` |
| Static discovery | `b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8` |
| Derived gap report | `8e5638b474c04a9f06a831fe5425132e82011b0b237b14284047f88f0529a68e` |

## Exact-ID result

The candidate has 352 exact artist MBIDs. Of its 121 public-direct MBID
overlaps, 101 occur in static discovery and 20 do not. The 20 excluded MBIDs
have 48 direct public observations. All 48 are export-authorized, and every
excluded artist has exactly one public artist entity and exactly one
export/display-authorized canonical MBID. No exclusion is caused by artist-name
matching, MBID ambiguity, or an inferred membership.

| First failing static-export gate | Artists | Direct observations |
| --- | ---: | ---: |
| No exact one-to-one placed catalog-label bridge | 20 | 48 |

Static discovery admits a direct observation only after its catalog genre can
be matched, casefolded, to exactly one placed semantic-atlas label and that map
label has exactly one matching catalog genre. Each of the 48 source-backed
observations fails that presentation-only bridge. This is not evidence that a
different genre should be substituted, and it does not authorize a bridge
change.

The excluded exact MBIDs and their direct-observation counts are:

| MBID | Observations |
| --- | ---: |
| `1d11e2a1-4531-4d61-a8c7-7b5c6a608fd2` | 5 |
| `301b45a4-b8b9-410e-8344-4b4eaf96691a` | 1 |
| `37b2cb82-ef79-4d46-a184-a549450aa231` | 2 |
| `37c61bf2-5fb1-47ae-9605-80025d956958` | 1 |
| `5dca4d22-d6c8-4e70-8ca1-4543e43353c7` | 1 |
| `5f6ab597-f57a-40da-be9e-adad48708203` | 3 |
| `6143403a-df6c-429e-8ee6-ef869896b0da` | 2 |
| `793e220b-64f8-46d9-954d-e033dbcfeef4` | 2 |
| `800760de-bdf8-43a2-8fe0-44a2401a5515` | 5 |
| `81435053-e1a2-48a4-adfd-e89f310c7b38` | 1 |
| `9f42ba3d-3cfc-499c-ba16-7226f56b622f` | 1 |
| `a16e47f5-aa54-47fe-87e4-bb8af91a9fdd` | 1 |
| `a17ce9c3-8f6f-4dcc-a1b7-2a04ab9e31f0` | 2 |
| `addb00fd-733c-4223-8fdf-f78be2488acd` | 1 |
| `bce6d667-cde8-485e-b078-c0a05adea36d` | 3 |
| `bdbd48f5-abf3-4a4f-9a21-4551dbc3fde9` | 1 |
| `ca891d65-d9b0-4258-89f7-e6ba29d83767` | 3 |
| `d721866d-5640-44ee-87f7-23dd062abd8a` | 3 |
| `dff0d392-4cd5-4052-9fbb-f485df3891e5` | 6 |
| `f82bcf78-5b69-4622-a5ef-73800768d9ac` | 4 |

## Reproduction

```sh
UV_CACHE_DIR=/tmp/opennoise-uv-cache uv run python \
  scripts/audit_musicbrainz_artist_credit_static_gap.py \
  --candidate .cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final.sqlite \
  --public-database data/public.sqlite \
  --semantic-atlas dist/assets/semantic-atlas.730bca93300870d35b527f377eb883ae95a3f931aad7e820b013fa592c5bf4ac.json \
  --static-discovery dist/assets/static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json \
  --report /tmp/artist-credit-static-gap-v1.json
```

The script parses `StaticDiscoveryPayload` before use and requires its `ready`,
direct-source, supplied-public-SQLite-bound state. The renderer atlas has no
typed model, so the audit honestly uses a pinned fallback contract: renderer
revision `semantic-scatter-map-v2`, source revision `semantic-map-layout-v2`,
and declared logical layout hash
`469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38`.
It joins candidate and public artists only on exact MBID, follows the static
export policy and canonical-MBID gates, and reads atlas labels only to
reproduce the existing exact one-to-one presentation bridge.
