# MusicBrainz release-group candidate evaluation

## Scope

This report records a local research evaluation of the completed MusicBrainz
release-group candidate. It is not a publication decision and it does not add
the candidate to a public API, map, or similarity model.

The candidate database is
`.cache/musicbrainz-release-group-evidence-candidate-v1/evidence.sqlite`. Its
SHA-256 is `980b2c58e16b024d282ca1acc58b98dcab292f0e1a50917812d1b59df0340c8a`
and its size is 3,259,346,944 bytes. `PRAGMA integrity_check` returned `ok`.
The artifact logical hash is
`caebeff8f0a0abe8c6afd90c9e37c141d235faba3fdb2ce08feb3e55526e9851`.
The independently checked publication receipt binds that logical hash and the
database hash and size.

The compact evaluator output is
`.cache/musicbrainz-release-group-evidence-candidate-v1/evaluation/release-group-support-evaluation.json`.
It does not verify the receipt itself. The receipt and database checks happened
before this evaluator was run.

## Observed coverage and accounting

The build processed 4,499,326 release-group records. Its reported coverage is:

- 2,377 seed names and 421,427 seed and artist pairs with direct anchors.
- 1,954 seed names and 1,546,265 pairs with release-group support.
- 2,570 seed names and 1,772,416 pairs in their union.
- 193 support-only seed names and 1,350,989 support-only pairs relative to the
  direct anchors.

The final typed table counts are 815,723 `artist_direct` rows and 4,775,264
`release_group_support` rows. Support is capped at three distinct release
groups per seed, artist, and facet. The evaluator found no cap violations.

The same release group can carry both a genre and a tag facet. It is counted
once for the independent support count, not once per facet. The evaluator found
2,367,386 seed, artist, and release-group combinations present in both facets,
so summing facet rows would overstate independent support.

## Direct overlap is not precision

195,276 of 1,546,265 support pairs also have an observed direct anchor. The
remaining 1,350,989 pairs are 87.37% of support pairs. They lack an observed
direct overlap, but that does not make them false. Direct-claim absence is
unknown, so the overlap rate is corroboration only and is not a precision
estimate.

For a fixed-snapshot diagnostic, the artifact reports recovery of 39,267 of
84,739 held-out direct anchors, or 46.34%. Those labels are a fixed reference
snapshot and this is not a strict forecast or a quality threshold.

The evaluator's direct-overlap rate rises with independently deduplicated
release-group support: 7.28% at one supporting release group, 14.22% at two,
and 28.49% at three. These figures still measure observed overlap rather than
truth.

## Parser and identity limits

Support uses only an exact MusicBrainz artist ID in a release-group credit and
the stable seed identity already bound by the seed-target artifact. It is not a
direct artist genre membership claim.

The release-group parser rejects a tag with a boolean, zero, negative, or
non-integer count. A missing release-group tag count is permitted as an
unweighted support claim. This differs from the artist extractor, which
excludes a missing artist tag count and permits a missing genre count as one
observation. The policies must not be treated as identical.

## Measured local queries

All smoke commands verified the database hash, size, integrity, and sidecar
bindings before SQL. They retained local-research-only, no-export, and
no-serving settings.

| Query | Direct | Release-group support | Verification / SQL seconds |
| --- | ---: | ---: | ---: |
| Hip hop | 23,755 | 36,812 | 37.498 / 1.213 |
| Jazz | 18,240 | 49,524 | 26.235 / 0.813 |
| Modern rock | 48 | 29 | 22.043 / 0.0007 |
| Lo-fi | 5,362 | 13,476 | 20.763 / 0.220 |
| Unsupported seed | 0 | 0 | 20.201 / 0.00037 |
| Exact-MBID reverse query | 5 seeds | 6 seeds | 19.398 / 2.562 |

## Next evaluation

Keep the direct-only baseline unchanged. A later local experiment may compare a
separately normalized, release-group-support-only signal with that baseline on
supported neighborhoods. It must measure whether support improves sparse cases
without simply increasing broad-label density. It must not blend the signals or
promote this candidate by row count alone.
