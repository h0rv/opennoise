# AcousticBrainz Wikidata recording diagnostic

## Result

The retained inputs support one local, positive-only, recording-level
diagnostic. It freezes 63 exact recording predictions from direct Wikidata
P136 evidence before parsing or using AcousticBrainz labels. It does not
establish artist truth or gold, negative labels, precision, promotion, or an
input for the public site or a model. The separate existing source-isolation
gate remains a no-go for artist gold and promotion.

The post-freeze label pass found three positive source label occurrences on
three recording rows whose literal normalized label is a unique current target
name. The label is `jazz`. The frozen direct P136 predictions have zero exact
literal overlaps with those three occurrences. This is an aggregate coverage
observation for this tiny recording cohort. It does not say that a recording
is a negative case, and it does not say that an artist lacks a genre.

## Retained artifacts

The local artifacts are under the ignored
`.cache/acousticbrainz-genre-dataset-discogs-validation-v1/` directory.

| Artifact | SHA-256 |
| --- | --- |
| Frozen prediction file | `1ade70e92114f09deb17d7ca4068fe8b78ede8d1b522900af51dbefa0bde3bba` |
| Prediction receipt file | `083cfe8ffc86748f7eae6b5663bcafb59dddf5beb74498f69332bbe260909ffa` |
| Positive-only diagnostic file | `e33046edc417323a63c349a02d21c13f15d293e4e0fe329405ea41ce6b4ba6a4` |

The receipt binds the following actual inputs.

| Construction input | SHA-256 |
| --- | --- |
| AcousticBrainz identifier columns | `d5b9eaef344864cd3c4d0bf1551e29b2fbcb23f9e28d1b7180cbdfa4dee704e3` |
| MusicBrainz credit membership materialization | `100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63` |
| Sealed public database, direct P136 and target names | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |

It also records the construction program SHA-256
`d06dcb763cc3731dcc39335cfa836061880459218a2b93ecb4050d9aee0f1650`.
The prediction artifact has logical SHA-256
`7444d5be1c9ee6eb75674b252bd28275da0d0c0f8788cb069a71f988fc7adfef`.
The diagnostic has logical SHA-256
`7542858dc71b7e7323acf7ec61f220472fff843bae068378ab84765af47fa57a`.

## Construction and verification

The construction code reads full TSV lines, but before the label pass it parses
and uses only the two AcousticBrainz identifier fields. It joins those IDs to
the one-primary-artist credit cohort and uses only direct `wikidata_p136`
artist evidence with current target names from the sealed public database. It
writes the complete prediction file and receipt before the label pass starts.
If receipt writing fails, it removes the newly written prediction file. The
output paths reject the deployable `dist` tree.

The four `used=false` entries in the receipt are declarations. The evidence for
them is the replayed construction code path, whose hash the verifier checks,
combined with the three pinned input hashes and a replay that must reproduce
every prediction row exactly. The verifier rejects altered prediction bytes,
a stale construction-program hash, changed inputs, a changed prediction count,
or an incomplete forbidden-input list. The excluded input classes are
MusicBrainz artist tags, MusicBrainz recording genres, MusicBrainz release-group
genres, and historical Every Noise.

After that verification succeeds, the diagnostic parses and uses source label
fields. It uses strict NFKC, casefolded, whitespace-normalized literal
matching to a unique current target name. It uses no aliases, hierarchy,
fuzzy matching, or semantic mapping. It reports only positive source label
occurrences and exact prediction overlaps. Unmatched labels are left unmapped
and are never negatives. The result is a recording-level coverage diagnostic,
not artist truth, artist gold, or a promotion result.

## Local replay

```sh
.venv/bin/python scripts/audit_acousticbrainz_wikidata_recording_diagnostic.py \
  --source .cache/acousticbrainz-genre-dataset-discogs-validation-v1/acousticbrainz-mediaeval-discogs-validation.tsv.bz2 \
  --credit-database .cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final.sqlite \
  --public-database data/public.sqlite \
  --prediction-output .cache/acousticbrainz-genre-dataset-discogs-validation-v1/wikidata-p136-recording-predictions-v1-final-v2.json \
  --receipt-output .cache/acousticbrainz-genre-dataset-discogs-validation-v1/wikidata-p136-recording-predictions-v1-final-v2.receipt.json \
  --diagnostic-output .cache/acousticbrainz-genre-dataset-discogs-validation-v1/wikidata-p136-positive-only-recording-diagnostic-v1-final-v2.json
```

The command refuses to overwrite any artifact. Use a new local output name for
another replay. These files remain local research artifacts and are not part of
the static export.
