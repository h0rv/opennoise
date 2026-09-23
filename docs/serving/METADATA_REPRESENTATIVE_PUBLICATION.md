# Metadata representative publication

The public serving catalog already persists selected release-group and recording
representatives in `public_genre_representatives`. The displayable projection
applies the selected public-model and genre-suppression boundaries. It does
**not** independently recheck the provenance policy named by each selected
metadata evidence reference. In particular, a row in that projection is not
authorization to publish its genre-to-recording or genre-to-release-group
assertion.

The separate JSON artifact is a deterministic, immutable exchange form for the
same selected rows. It is an archived, non-Poe workflow and is not consumed by
the static Pages build. Before it can publish through any `ObjectStore`, the
publisher requires the sealed catalog database and proves that every
`catalog:metadata:<provenance-id>` reference actively allows both `display` and
`export`, and that the complete artifact exactly reproduces the selected catalog
rows for its declared public-model run. A missing, malformed, substituted,
display-denied, or export-denied reference fails closed.

Build it from the selected serving database, then publish it with that same
sealed database:

```sh
python scripts/build_metadata_representatives.py \
  data/public.sqlite \
  --output data/model/metadata-representatives-v1.json

python scripts/publish_metadata_representatives.py \
  data/model/metadata-representatives-v1.json \
  --catalog-database data/public.sqlite \
  --object-store data/objects \
  --output data/model/metadata-representatives-publication-v1.json
```

Publication parses the JSON with its Pydantic boundary model and verifies every
evidence policy against the supplied sealed catalog before writing.
It accepts only `release_group` and `recording` metadata examples whose exact
typed identifier resolves to a MusicBrainz or Wikidata metadata page. It writes
the artifact to `metadata-representatives/sha256/<file-sha256>.json`; replays of
the same bytes are reused and conflicting bytes fail.

This path never fetches a source adapter, audio, previews, media assets, or
catalog/playback URLs. A recording is a track-level metadata proxy only. It does
not assert a recording-to-release relation, popularity, quality, consensus,
influence, or that every genre has an example of either kind.

The current static Pages export does not include this artifact or its
release-group/recording rows. Any future API or HTML surface must consume only
the policy-verified artifact; it must not query
`displayable_public_genre_representatives` directly.

The public-release custody cache is not a substitute for this selection catalog.
If custody includes the optional `metadata-representatives` objective gate, it
must receive an explicit, sealed metadata catalog database to reconstruct the
selection and recheck its evidence policy. Otherwise custody rejects that
objective gate.
