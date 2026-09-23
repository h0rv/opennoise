# MusicBrainz release-group genre recovery hash sample

This local-only experiment replaces the first 10,000 archive-order groups with
a deterministic content-hash sample from the complete pinned release-group
archive. It uses only positive native MusicBrainz genres as target labels.
Positive tags remain separate sample fields and never become target labels.
The result does not authorize export, serving, model input, or artist
membership claims.

## Source and selection

The source is the 2026-09-05 MusicBrainz release-group archive. Its compressed
size is 1,159,485,640 bytes and its pinned SHA-256 is
`6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43`. The
evaluator verifies the archive hash and size and checks the source-cache
receipt against the current manifest entry, then checks the receipt and its
declared manifest hash against pinned digests. Targets use the pinned
6,291-name seed reconciliation with SHA-256
`a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0`.

The evaluator streams every release-group JSON record. Before model parsing,
it selects records when the first eight bytes of
`SHA-256(domain || SHA-256(raw record bytes))`, interpreted as an unsigned big
endian integer, are divisible by 450. This selects about one record in 450,
without using archive position, genre labels, or artist IDs to decide
selection. It fails closed above 15,000 selected records, 2,000 retained facts
for one group, 128 MiB of selected record bytes, or 1,000,000 retained facts
overall. The sample stores the selected groups' native genres and positive
tags in separate fields.

The source cache receipt and seed reconciliation are local research inputs.
MusicBrainz genre and tag associations have restricted research terms, so the
report and retained sample stay under `.cache` and are not portable or public.

## Holdout

The evaluator partitions exact release-group IDs by SHA-256, with the first
unsigned 64 bits modulo five equal to zero assigned to test. No group appears
on both sides. Artist overlap remains allowed because artist transfer uses
training labels attached to credited artists. The transfer rule sums training
label counts across a held-out group's credited artists and picks one label,
breaking ties by normalized label. It abstains when none of those artists has
training labels. The baseline picks the most frequent label among training
group/label pairs. Both scores include warm and full-test denominators,
cold abstentions, coverage-adjusted accuracy, and macro recall across each
held-out label.

The sample is a reproducible hash selection over this pinned archive, not a
claim that the archive represents all music or that one holdout establishes
quality. The full input requires a compressed-byte hash pass and a complete
streaming decompression pass over about 18.1 GB of member data. Stop the local
run if laptop resource pressure or elapsed time becomes unacceptable, and
record the incomplete status rather than treating partial output as a result.

## Result

The completed run scanned all 4,499,326 source records in 2 minutes and 28
seconds. It selected 10,010 records, of which one was malformed and 10,009
parsed as complete release groups. No source record exceeded the 2 MiB limit.
The selected records totaled 39,804,368 bytes. The evaluator retained 33,156
artist, genre, and tag facts under the declared limits.

The sample contains 3,457 groups with at least one positive proper genre that
matches a seed name. The ID split placed 2,757 labeled groups in training and
700 in test. The test has 1,654 group and label pairs across 247 labels, and
18 labels have no training examples.

| Rule | Correct top one | Scoreable groups | Cold abstentions | Accuracy | Coverage adjusted accuracy | Macro recall by seed |
|---|---:|---:|---:|---:|---:|---:|
| Artist transfer | 59 | 99 of 700 | 601 | 59.6% | 8.4% | 0.62% |
| Training popularity | 226 | 700 of 700 | 0 | 32.3% | 32.3% | 0.40% |

Artist transfer has higher accuracy on its 99 scoreable groups and higher
macro recall, but it abstains on 601 of the 700 test groups. After abstentions
count against coverage, training popularity is correct on more than three
times as many held-out groups. Macro recall stays below one percent for both
rules, so these results do not support a claim of useful recovery across the
seed vocabulary.

The archive-order v1 sample had 6,449 labeled groups among its first 10,000
records. The hash sample has 3,457 among 10,009 parsed groups. This difference
shows why the prefix sample should not stand in for archive-wide selection.
The hash sample removes dependence on the first records in this archive, but
it remains one snapshot and one deterministic holdout, with no population
quality claim.

The evaluator is `scripts/evaluate_musicbrainz_rg_genre_recovery_v2.py`. Its
local output is `.cache/musicbrainz-rg-genre-recovery-hash-sample-v2/report.json`.
The report output hash covers the source receipts, sample facts, limits,
split, denominators, and scores. The completed report has logical SHA-256
`132f265926724d8a46756bd4056264f927d7602b40d498ca339cad7b51bc96fe`, which
was replay-verified after the write.
