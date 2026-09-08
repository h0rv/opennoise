# MusicBrainz evidence checkpoint

## Current status

The full MusicBrainz release-group build completed from the verified 2026-09-05 archive and source-cache receipt. It streamed 4,499,326 release-group records into a local research candidate outside the public catalog.

The final candidate is `.cache/musicbrainz-release-group-evidence-candidate-v1/evidence.sqlite`. Its SHA-256 is `980b2c58e16b024d282ca1acc58b98dcab292f0e1a50917812d1b59df0340c8a` and its size is 3,259,346,944 bytes. `PRAGMA integrity_check` returned `ok`. The matching artifact is `artifact.json`, with logical SHA-256 `caebeff8f0a0abe8c6afd90c9e37c141d235faba3fdb2ce08feb3e55526e9851`, and `receipt.json` binds the same logical artifact and database hash and size.

The reported union covers 2,570 seed names and 1,772,416 distinct seed and artist pairs. The persisted aggregate diagnostic is `.cache/musicbrainz-release-group-evidence-candidate-v1/evaluation/release-group-support-evaluation.json`. It is not a receipt verifier by itself; the external artifact and receipt binding above was checked separately. The completed candidate is local research only.

## Evidence meaning

The builder preserves two different kinds of evidence.

- `artist_direct` comes from the earlier MusicBrainz artist extraction. It connects a stable seed ID to an exact MusicBrainz artist ID and keeps the `musicbrainz_genre` or `musicbrainz_tag` facet.
- `release_group_support` comes from a release group whose artist credit has an exact MusicBrainz artist ID. It is separate support for a seed and artist. It is not a direct artist membership claim.

The builder caps release-group support at three release groups for each seed, artist, and facet. Contextual tags from the larger artist artifact are not copied into this database. No result should relabel direct tags as contextual evidence.

The release-group parser rejects a tag with a boolean, zero, negative, or non-integer count, but permits a missing tag count as an unweighted support claim. This is intentionally not the artist extractor's policy: the artist extractor excludes missing tag counts, while it permits a missing genre count as one observation. The two sources therefore must not be described as having identical count handling.

## Completed tools and boundaries

The builder verifies the source-cache receipt, archive hash, source size, member path, and bounded stream before it writes the final database. It verifies the seed-target artifact before using its direct anchors. A partial database remains inspectable but is not queryable.

The local direct-artist query tool verifies the evidence artifact, database hash and size, SQLite integrity, the all-seed reconciliation sidecar, and the existing MusicBrainz adapter report. The sidecars bind the same seed target and all 6,291 stable seed IDs. The query reports verification time separately from SQL time. An opt-in loopback-only panel can use the same completed inputs after startup checks them once. It is not a public API or public UI path. A loopback HTTP smoke passed with the completed evidence and final metadata artifacts.

## Acceptance steps

The builder atomically wrote the final database. The artifact and publication receipt match its verified hash and size. The aggregate evaluator ran after that external custody check. It found 815,723 `artist_direct` and 4,775,264 `release_group_support` typed rows, no cap violation, and deduplicates a release group that appears in both facets before independent-support accounting. It reports overlap as corroboration, never precision: 195,276 of 1,546,265 support pairs also have an observed direct anchor, so 87.37% lack an observed direct overlap. That absence is unknown, not a negative label.

The local query smoke checks also completed with matching sidecars and whole-file verification. Hip hop returned 23,755 direct and 36,812 support artists; jazz returned 18,240 and 49,524; modern rock returned 48 and 29; lo-fi returned 5,362 and 13,476; and an unsupported seed returned zero in both sections. An exact-MBID reverse query returned five direct and six support seeds. SQL time ranged from 0.00037 to 2.562 seconds after the roughly 19 to 37 second full-file verification step. All six commands retained `local_research_only`, `export_allowed=false`, and `serving_allowed=false`.

## Remaining discovery gaps

The fixed seed vocabulary has 6,291 names, while direct MusicBrainz evidence exists for only an observed subset. A missing direct result remains an explicit empty result. The release-group build may add separate support, but it does not recover every name as a direct membership and it does not make unsupported names observed.

The candidate remains local research. It is not integrated into the production map, public artist navigation, or any public similarity or discovery claim. A separate policy and publication decision would be required before any serving change.
