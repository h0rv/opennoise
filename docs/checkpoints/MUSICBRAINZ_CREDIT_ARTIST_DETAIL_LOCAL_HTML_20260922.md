# MusicBrainz credit artist detail local HTML preview

This checkpoint adds a local static HTML preview for the existing artist credit
detail seam. It does not change `dist`, public assets, the static page builder,
or deployment. It writes one new directory below an operator selected existing
`.cache` directory. The directory contains `index.html` and the checked JSON
sidecar that the page displays. The page uses no JavaScript. Its HTML comes
from checked-in local preview templates under `src/opennoise/static`; Python
only supplies escaped source values.

The preview calls the existing JSON renderer before it writes HTML. That
renderer checks the metadata asset's static discovery hash, public database
hash, direct-source scope, row counts, deterministic order, and one-to-one
canonical MusicBrainz artist ID binding. It does not independently require or
validate approval. The HTML wrapper checks a separately supplied typed
approval declaration for the already-gated
`musicbrainz-credit-static-metadata-v1` asset. It rejects a row that has the
requested static artist ID but a different MusicBrainz artist ID. Without the
candidate database and report, the wrapper cannot independently recheck the
candidate report or policy.

The HTML shows only the label `MusicBrainz credit metadata`, the local-only
publication status, a MusicBrainz artist identifier, and the retained release
or recording title with its ordered credited names. All source text is HTML
escaped. It contains no genre, membership, map, score, rank, selection, or
representative fields.

The approval and policy boundary stays in
`musicbrainz_credit_static_export.py`. The HTML preview cannot create an
approval, read the candidate database, or select a public output. A public UI
integration remains blocked until an approved versioned publication decision
names the exact candidate, its provenance, and the intended public asset.

After `poe sync`, an operator with an already approved metadata asset can make
a local preview with:

```sh
.venv/bin/python scripts/render_local_musicbrainz_credit_artist_detail_html.py \
  --credit-metadata /path/to/musicbrainz-credit-metadata.json \
  --approval /path/to/musicbrainz-credit-metadata-approval.json \
  --static-discovery /path/to/static-discovery.json \
  --static-artist-id artist:123 \
  --local-root .cache \
  --output-directory .cache/musicbrainz-credit-artist-123
```

The output directory must not exist and must stay below the selected `.cache`
directory. A temporary sibling directory is removed if gate validation or
rendering fails, so a failed preview creates no output directory. The focused
deterministic HTML tests assert escaped source text,
the local-only status, release markup, absence of JavaScript and discovery
claims, an exact-ID rejection, and refusal of an output outside `.cache` or a
cache root below this repository's `dist` tree.
