# MusicBrainz direct static quality report

The quality report reads the pinned portable MusicBrainz custody object, the
existing local candidate, and the pending policy-review input. It does not read
the larger raw source archive. It checks the exact 412 placed seed IDs and the
candidate's direct artist record IDs against the pinned custody rows.

The report records source and name coverage, duplicate and exclusion counts,
missing and unexpected source rows, exact-ID failures, and every genre row
count. It does not measure ambiguous-name exclusions because the candidate and
direct custody inputs retain accepted names, not the rejected-name ledger. It
states that limit as `null` instead of assigning a cause to a missing row. It
also lists the five largest and five smallest genres. Its deterministic review
links include hash-selected rows and rows from the high and low count ends of
the distribution. The links are generated for later human review. They have
not been manually reviewed or approved.

The report measures source integrity and distribution only. It does not prove
that a MusicBrainz observation is correct, appropriate for display, or ready
for release. Public export, serving, membership claims, and the release gate
remain false.

The local run on 2026-09-23 found 139,268 source claims and 139,268 candidate
rows. Source and name coverage were both 1.0. It found zero duplicates, source
exclusions, missing rows, unexpected rows, and exact-ID failures. Ambiguous
name exclusions were not measured. The five largest seed IDs were `item5`
(23,033), `item1` (12,174), `item114` (10,636), `item99` (7,946), and
`item1154` (7,848). The five smallest were `item3368` (3), `item1184` (4),
`item4239` (4), `item6046` (4), and `item3568` (5). The generated extreme
samples include Totengräber and The Beatles from the two largest seeds, plus
Djeli Moussa Diawara and 3Phaz from the two smallest seeds. These are review
priorities from row-count extremes, not evidence that a row is bad.

The report's byte SHA-256 was
`ea4f6eb6b742c27faa6785088fcb5f5ef39c6da568518ecb2599cf1b8b8d7260`.

Run it after the existing local candidate and policy-review input are present.

```sh
.venv/bin/python scripts/report_musicbrainz_direct_static_quality.py \
  --direct-custody-receipt config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json \
  --direct-custody-object-store data/release/musicbrainz-direct-proper-genre-custody-v1/objects \
  --local-candidate-directory .cache/musicbrainz-direct-local-static-candidate-v1 \
  --policy-review-input .cache/musicbrainz-direct-static-policy-review-input-v1.json \
  --output .cache/musicbrainz-direct-static-quality-report-v1.json
```
