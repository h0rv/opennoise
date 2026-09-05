# MusicBrainz artist genre coverage

Status: completed local research measurement, 2026-09-04.

The reported scope is the completed adapter-v3 attempt for SHA256 source-ID
prefix `0`. It scanned 2,970,393 archive records and selected and accepted
185,779 records. It quarantined 0 records and found 0 duplicate source
objects. The first run took 1,140.390 seconds. A replay returned
`reused_attempt: true` in 0.024 seconds with identical counters and no archive
parse.

The source archive is the retained object
`data/source-cache/raw/sha256/396fb476984234dd68650c59219d5e0bd0d900abccd6f4e3fe1a6160918ffe1d`.
Its SHA256 is
`396fb476984234dd68650c59219d5e0bd0d900abccd6f4e3fe1a6160918ffe1d`.
The research database is
`.cache/musicbrainz-v3-research/musicbrainz-v3.sqlite` and is ignored by
Git. It returned `ok` from `PRAGMA integrity_check` and no rows from
`PRAGMA foreign_key_check` after the completed prefix-0 attempt.

## Coverage

The Every Noise side contributes only 6,291 retained genre names from
`data/musix.sqlite`. Coordinates, historical memberships, representatives,
and source ordering are not read by the evaluator or baseline.

| Measure | Prefix-0 result |
| --- | ---: |
| Imported MusicBrainz genres | 1,077 |
| Imported genre aliases | 0 |
| Imported positive genres | 1,077 |
| Imported positive artists | 13,150 |
| Imported positive evidence rows | 28,610 |
| Imported positive evidence weight sum | 34,307 |
| Exact seed-name matches | 697 / 6,291 (11.078%) |
| Normalized seed-name matches | 724 / 6,291 (11.506%) |
| Matched MusicBrainz genre IDs | 724 |
| Matched positive artists | 12,481 |
| Matched positive evidence rows | 24,363 |
| Matched positive evidence weight sum | 29,348 |
| Unmatched seed names | 5,567 |

Normalized matching applies NFKD, casefolding, combining-mark removal,
punctuation-to-space conversion, and whitespace collapsing. The imported
artist archive has no genre-alias field, so the alias count is explicitly
zero. Positive evidence means an official artist `genres` entry with a count
greater than zero. Missing, zero, and negative counts are not evidence.

For matched seed names, the positive-weight distribution is: `1`: 21,821,
`2`: 1,695, `3`: 458, `4`: 148, `5`: 74, `6`: 52, `7`: 29, `8`: 13, `9`: 15,
`10`: 9, `11`: 10, `12`: 8, `13`: 6, `14`: 2, `15`: 5, `16`: 2, `17`: 1,
`18`: 1, `19`: 3, `21`: 1, `22`: 3, `23`: 3, `30`: 1, `38`: 1, and `111`: 2.

## Source-only overlap baseline

The typed reconstruction artifact contains 724 matched MusicBrainz genres,
12,481 artists, and 24,363 unique positive artist-genre edges. Its SHA256 is
`3dcfcc5e44d745df42f045c9273ef55fb911a3e88c2602c50947e84507634d14`.

Both weighted baselines used ten neighbors, 28,936 pair visits, 8,289
candidate/retained similarity edges, and 724 genre neighbor lists:

| Metric | Genres | Artists | Edges | Pair visits | Similarity edges | Neighbor lists |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Weighted Jaccard | 724 | 12,481 | 24,363 | 28,936 | 8,289 | 724 |
| Weighted cosine | 724 | 12,481 | 24,363 | 28,936 | 8,289 | 724 |

These are candidate approximations from direct MusicBrainz evidence. They do
not claim to recover the historical Every Noise method and do not use its
geometry or memberships.

## Rights boundary

MusicBrainz core identity fields are CC0. Genre associations are supplementary
data under CC-BY-NC-SA-3.0. The stored local research policy permits local
normalization, search, display, embedding, and training, while denying raw
export, metadata export, and redistribution. The database, coverage report,
reconstruction inputs, and baselines are therefore local noncommercial
research artifacts and are not public-exportable without a separate rights
review, attribution, and ShareAlike decision.
