# MusicBrainz direct local static candidate preparation

This is a local-only candidate-preparation boundary. It is not a public static
asset, an addition to static discovery v2, a model input, a membership
authorization, a serving input, a build input, or a deployment artifact.

The builder accepts only the portable exact MusicBrainz proper-genre custody
stream, its exact-MBID canonical-name custody stream, and the exact-MBID
recovered-name stream. It pins every receipt's file SHA-256, verifies that the
canonical and recovery receipts bind the same direct claim object, and refuses
any source with a public-export flag. A membership carries the direct
`musicbrainz:artist:<MBID>` source-record identity, source record hash, and
evidence reference. Tags, release rows, peer rows, aliases, inferred rows, and
historical assignments cannot be represented by its schema.

Candidate seed scope is recomputed from the verified direct-custody seed IDs,
the manifest-certified static discovery, and semantic atlas:
`(direct-custody IDs − static-discovery IDs) ∩ placed-atlas IDs`. This is not
the much broader set of all placed atlas IDs absent from static discovery. The
pinned delta proves 697 direct-custody IDs, 423 candidate-only IDs, and 412
placed candidate-only IDs (11 candidate-only IDs are unplaced). The real run
pin is therefore exactly 412 IDs. Every candidate seed must have a literal
direct proper-genre pair, and every pair must have exactly one canonical name
through the two exact-MBID name custody streams; otherwise writing fails.

Rows are ordered by `(seed_id, artist_mbid)` and stored in local
`genres/<seed SHA-256>/<ordinal>.<content SHA-256>.jsonl` files. Each shard
contains at most 1,000 rows. The checked local manifest records each path,
row count, byte count, content SHA-256, all source identities, and its own
logical SHA-256. It fixes all public/export/serving/release flags to `false`.

The fresh ignored-cache run completed after the Last.fm scan, then passed an
independent local output-integrity verifier. That verifier checks the manifest
and shard tree only; the builder separately verified the pinned source receipts,
objects, and certified assets before it wrote the output. Its manifest hash is
`a8f0059e7c53c802af88f27d473f6fec35b8e2f137218470e9fc3bee1b71ee70`.

| Measured local-only property | Value |
| --- | ---: |
| Placed candidate-only seed IDs | 412 |
| Direct, exact-named membership rows | 139,268 |
| JSONL shards (at most 1,000 rows each) | 503 |
| Shard content bytes | 77,833,931 |
| Manifest bytes | 157,833 |
| Total cache-file bytes | 77,991,764 |

The 11 unplaced candidate-only seeds account for 130 of the 139,398 direct
candidate-only rows and are intentionally absent. There were no missing exact
names or missing direct pairs inside the 412 placed-seed scope; either condition
would have made the writer fail. The old 115,269-row packaging estimate is not
reused. This remains an ignored local cache, not a public/export/build/serving
artifact or authorization.

Use `scripts/build_musicbrainz_direct_local_static_candidate.py` only with
explicit receipt hashes and an ignored-cache output directory such as
`.cache/musicbrainz-direct-local-static-candidate-v1/`. The writer refuses an
existing output directory and has no Poe, build, or deployment integration.
