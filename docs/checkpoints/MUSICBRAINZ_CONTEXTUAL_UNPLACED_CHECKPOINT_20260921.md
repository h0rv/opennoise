# MusicBrainz contextual-tag unplaced checkpoint

The exact spelling-normalized intersection of the current layout's 3,346
explicitly unplaced seed names with the retained MusicBrainz contextual-tag
rows is **zero**: 0 matched seeds, 0 rows, 0 artists, and 0 tag identities.
This is a negative *artifact-overlap* result, not evidence that MusicBrainz
has no relevant tags for the unplaced names and not a placement or membership
decision.

| Exact overlap measure | Count |
| --- | ---: |
| Explicit unplaced seeds | 3,346 |
| Exact normalized contextual-tag seed matches | 0 |
| Matching contextual rows / artists / tag identities | 0 / 0 / 0 |
| Unmatched explicit unplaced seeds | 3,346 |
| Total contextual rows scanned | 212,696 |

## Provenance and reproduction

The read-only audit loaded the retained source artifact once, normalizing
only `ContextualArtistTag.tag_name` and each current unplaced seed name with
`opennoise.taxonomy.seeds.universe.normalize_label`. It did not read Every
Noise fields other than the retained seed names embedded in the layout, did
not write a database or public asset, and did not use tags as memberships.

Inputs are the v3 layout logical hash
`469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38`
(file SHA-256 `e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972`)
and seed-target artifact logical hash
`1cfe14b7dfce41c5f1b45c423407c7c1ad528abbafa3b3b859770e49c8debe46`
(file SHA-256 `481eb68f7d75d8562fe16aa1f9faef327d24e8afd5145fa5c7d136ed9ac69dfe`).
The result JSON SHA-256 was
`654fb5fc33e7a0aa6e3700c87527ddbf1b0bb811e2953d71de5e72913eb09b35`.

Reproduce locally with:

```sh
uv run python scripts/audit_musicbrainz_contextual_unplaced.py \
  --layout .cache/semantic-map-layout-v3/artifact.json \
  --source-artifact .cache/musicbrainz-full-seed-targets/musicbrainz-seed-targets-v1.json \
  --output .cache/musicbrainz-full-seed-targets/contextual-unplaced-audit.json
```

Ruff and Ty pass for the script.

## Leakage and circularity caution

This zero is expected to be structurally censored. The extractor retains a
contextual tag only for an artist already matched to some seed, and excludes
any tag identity that itself matched a seed target (`target_tag_identities`).
An exact tag for an unplaced seed would therefore be emitted as direct target
evidence, not retained as contextual data. Consequently this matrix cannot
measure new exact-tag seed lift for the unplaced set, nor can a zero overlap be
used as a negative label.

Contextual rows are also selected conditional on direct-anchor artists. Any
model trained or calibrated on them risks direct-label leakage through artist
selection and tag co-occurrence. A future test must begin from a source slice
that retains all tags independently of seed matching, hold out complete label
identities before feature construction, bind source hashes, and keep its output
review-only until independently evaluated.
