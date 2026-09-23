# AcousticBrainz Discogs validation exact-overlap receipt

## Decision

The official AcousticBrainz Genre Dataset Discogs validation TSV is now
retained only in ignored local research custody for a counts-only exact-ID
overlap audit. It is not a model input, public artifact, artist-membership
gold set, precision measurement, or release gate.

## Source custody

- Locator: <https://zenodo.org/records/2553414/files/acousticbrainz-mediaeval-discogs-validation.tsv.bz2?download=1>
- Zenodo record: [MediaEval AcousticBrainz Genre v1](https://zenodo.org/records/2553414)
- Published MD5: `1b9ae2055c3b4b32c5219ee93992de9e`; the downloaded bytes matched.
- Local raw SHA-256: `d5b9eaef344864cd3c4d0bf1551e29b2fbcb23f9e28d1b7180cbdfa4dee704e3`.
- Catalog SHA-256: `100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63`.
- Raw object and receipt remain under ignored
  `.cache/acousticbrainz-genre-dataset-discogs-validation-v1/`.

The official [format documentation](https://mtg.github.io/acousticbrainz-genre-dataset/data/)
defines the first two TSV fields as MusicBrainz recording and release-group
IDs. The audit reads only those two fields and explicitly neither parses nor
retains any label columns. It accepts only the fixed Zenodo locator and
published MD5 above, limits compressed input to 10 MiB, decompressed input to
32 MiB, lines to 16 KiB, and data rows to 200,000.

## Exact bridge result

The local artist-credit materialization contains 1,031 exact MusicBrainz
recording IDs. Its direct join to the validation TSV produced:

| Count | Result |
| --- | ---: |
| Validation source rows | 193,392 |
| Duplicate source recording IDs | 0 |
| Exact recording-MBID overlap | 71 |
| Exact release-group-consistent overlap | 64 |
| Release-group-mismatch abstentions | 7 |
| One-primary-artist exact overlap | 69 |
| One-primary-artist and release-group-consistent overlap | 63 |

The 63 rows are a cohort ceiling for a later frozen-prediction,
positive-only, recording-level diagnostic. They do not establish artist genre
membership: a recording label must not be generalized to an artist.

The hardened reproducible local-only receipt was written to
`.cache/acousticbrainz-genre-dataset-discogs-validation-v1/exact-overlap-receipt-v2.json`
by:

```sh
.venv/bin/python scripts/audit_acousticbrainz_discogs_validation_overlap.py \
  --source .cache/acousticbrainz-genre-dataset-discogs-validation-v1/acousticbrainz-mediaeval-discogs-validation.tsv.bz2 \
  --catalog .cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final.sqlite \
  --output .cache/acousticbrainz-genre-dataset-discogs-validation-v1/exact-overlap-receipt-v2.json
```

The conservative artist count requires one distinct primary artist-credit
relation, one distinct credited artist, and one credit position. It does not
accept an otherwise single-artist credit if a recording has multiple primary
credit relations.

## Leakage boundary

The [MetaBrainz genre-matching project](https://github.com/metabrainz/genre-matching)
imported AcousticBrainz Genre Dataset source annotations, including Discogs,
into MusicBrainz tags. A future diagnostic can use this 63-row ceiling only
after it freezes predictions and proves their receipts exclude MusicBrainz
tags, recording genres, release genre support, and models derived from them.
It must also keep this TSV out of construction, label normalization, public
export, and deployment. The source labels remain positive-only; their absence
is never a negative claim.
