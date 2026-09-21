# MusicBrainz direct proper-genre frontier

This bounded local-only audit measures retained, exact MusicBrainz artist
genre observations for canonical map seeds that are both unplaced and not
currently served by a Wikidata direct artist claim. It does not construct a
membership, alter a layout, or read historical Every Noise assignments.

## Pinned inputs

- v3 semantic layout: logical `469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38`, byte `e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972`.
- sealed all-seed evidence frontier v5: logical `edf01e96b8ab12d7c90b49cf9119aa5fb0a01ccdea253924b7923ed3e0ecbef8`, byte `4c0dbc32b28d01b95ce79f988750b39db74241368a8b1257d6e2a9345c1c0db2`.
- complete seed reconciliation: logical `842a2b91836822bae52e01e98a635c7cbb17a0cb0a131f65c7fc5d6701f2a3aa`, byte `c87fe5b67c0974b30d5ae1d2a9f66b22b122126230cd2561837c94897514f022`.
- retained MusicBrainz seed-target artifact: logical `1cfe14b7dfce41c5f1b45c423407c7c1ad528abbafa3b3b859770e49c8debe46`, byte `481eb68f7d75d8562fe16aa1f9faef327d24e8afd5145fa5c7d136ed9ac69dfe`.

## Results

The layout has 3,346 unplaced canonical seed IDs. Two already have a current
Wikidata direct artist claim, leaving 3,344 unplaced-and-unserved IDs in the
bounded scope.

| Retained evidence class | Rows | Seeds | Exact artist MBIDs |
| --- | ---: | ---: | ---: |
| Strict direct MusicBrainz proper genres | 318 | 69 | 317 |
| Proper genres also bound to the seed's reconciled MusicBrainz genre identity | 130 | 11 | not separately promoted |
| Proper genres abstained because the target is not that reconciled identity | 188 | 58 | not separately promoted |
| Exact loose MusicBrainz tags | 1,022 | 544 | 945 |

“Strict direct” means a literal `facet=genre`, `match_kind=exact`, identical
seed and target spelling, `musicbrainz_genre_id` namespace, lower-case UUID
artist MBID, matching `musicbrainz:artist:<MBID>` source record, and source
record SHA-256. The report found no malformed source rows.

The tag row is deliberately separate: it is a larger positive review frontier,
not a factual proper-genre claim. The reconciliation-bound proper-genre subset
is the narrowest identity-safe increment: 11 seed IDs and 130 retained direct
rows. The remaining 58 proper-genre seed IDs are recorded as identity
abstentions, not inferred mappings.

A fresh local rerun reproduced those 130 observations and 11 seed IDs, with
188 identity-abstained rows, zero malformed source rows, and zero publishable
memberships. Its seed-target byte binding is
`481eb68f7d75d8562fe16aa1f9faef327d24e8afd5145fa5c7d136ed9ac69dfe`.

No release, peer, one-hop, or inferred membership row was read or used. The
report fixes `historical_assignments_read=false`,
`membership_construction_performed=false`, and
`publishable_membership_count=0`.

The scoped reconciliation states are 2,724 unresolved, 528 review-only, 61
MusicBrainz-only, 29 public-only, one reconciled, and one ambiguous. They
explain why source-positive coverage must not become automatic serving or
placement coverage.

Reproduce the compact JSON report locally with:

```sh
.venv/bin/python scripts/audit_musicbrainz_direct_genre_frontier.py \
  --layout .cache/semantic-map-layout-v3/artifact.json \
  --frontier .cache/all-seed-evidence-frontier-v5-sealed/artifact.json \
  --reconciliation .cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json \
  --seed-target .cache/musicbrainz-full-seed-targets/musicbrainz-seed-targets-v1.json \
  --output /tmp/musicbrainz-direct-genre-frontier.json
```
