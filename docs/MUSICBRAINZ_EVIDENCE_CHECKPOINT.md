# MusicBrainz evidence checkpoint

## Current status

The full MusicBrainz release-group build is pending. The input is the verified 2026-09-05 release-group archive and its source-cache receipt. The build writes a candidate database outside the public catalog. No completed candidate database, evidence artifact, or publication receipt exists yet.

Any small sample is diagnostic only. A sample may check parser behavior, source shape, memory use, or the direct and support table schema. It does not measure full-corpus coverage and it does not permit a public claim.

## Evidence meaning

The builder preserves two different kinds of evidence.

- `artist_direct` comes from the earlier MusicBrainz artist extraction. It connects a stable seed ID to an exact MusicBrainz artist ID and keeps the `musicbrainz_genre` or `musicbrainz_tag` facet.
- `release_group_support` comes from a release group whose artist credit has an exact MusicBrainz artist ID. It is separate support for a seed and artist. It is not a direct artist membership claim.

The builder caps release-group support at three release groups for each seed, artist, and facet. Contextual tags from the larger artist artifact are not copied into this database. No result should relabel direct tags as contextual evidence.

## Completed tools and boundaries

The builder verifies the source-cache receipt, archive hash, source size, member path, and bounded stream before it writes the final database. It verifies the seed-target artifact before using its direct anchors. A partial database remains inspectable but is not queryable.

The local direct-artist query tool is ready for a completed candidate. It verifies the evidence artifact, database hash and size, SQLite integrity, the all-seed reconciliation sidecar, and the existing MusicBrainz adapter report. The sidecars bind the same seed target and all 6,291 stable seed IDs. The query reports verification time separately from SQL time. It is local research only and has no public API or UI path.

## Acceptance steps

First, wait for the builder to atomically write the final database. Second, verify the evidence artifact and publication receipt against that database. Third, run the aggregate release-group support evaluator after that external custody check. It deduplicates release-group IDs across genre and tag facets, checks caps and typed accounting, and reports direct-claim overlap as corroboration rather than precision. Fourth, run the direct and reverse local queries with the matching sidecars, including a known empty seed. Fifth, record full-file verification time separately from SQL query time. Sixth, run the focused builder, query, evaluator, format, lint, and type checks.

## Remaining discovery gaps

The fixed seed vocabulary has 6,291 names, while direct MusicBrainz evidence exists for only an observed subset. A missing direct result remains an explicit empty result. The release-group build may add separate support, but it does not recover every name as a direct membership and it does not make unsupported names observed.

The candidate remains local research. It is not integrated into the production map, public artist navigation, or any public similarity or discovery claim. A separate policy and publication decision would be required before any serving change.
