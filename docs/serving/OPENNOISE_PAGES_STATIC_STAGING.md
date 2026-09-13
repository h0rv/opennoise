# OpenNoise static Pages export

`export_opennoise_pages.py` builds the entire OpenNoise public surface into an
empty directory for Cloudflare Pages. It creates no Pages Functions, API, or
runtime graph library. The browser receives pre-rendered SVG, ordinary links,
and one small deferred search module that filters a static name index.

The visible map is bound to the sealed, export-allowed
`production-map-v1.json` receipt. At this checkpoint that receipt contains 603
public mapped genre nodes, 3,274 similarity edges, and 712 taxonomy edges. Its
byte SHA-256 is
`7b92fc8a2f45fc721d12eafc7ae117260045143282e36bde41938f8d602481df`; its
logical SHA-256 is
`017fc6f0eeebbac1f59df907b69f1229083ad221a36a64986ad878fa47ee02fc`.

Search has a deliberately different contract. It retains all 6,291 permitted
legacy names from `open-construction-graph-v2`, but a result gets a map link
only when its sealed factual `canonical_catalog_identity` edge resolves to a
node in the production map. The export receipt records the two counts
separately. In the current inputs, 433 names are directly mapped and 5,858 are
searchable only. A searchable-only name has no coordinate, neighborhood, or
implied genre identity.

The v2 input is accepted only when every historical-construction input-audit
field is false, including coordinates, memberships, neighbors, artist
membership evidence, listening aggregates, and audio. The exporter consumes
only its retained names and factual exact identity edges; it never uses its
layout or historical data.

Build into a new or empty directory:

```bash
UV_OFFLINE=1 uv run --no-sync python scripts/export_opennoise_pages.py \
  --production-map data/model/production-map-v1.json \
  --open-construction-v2 data/model/open-construction-graph-v2.json \
  --output dist
```

`index.html` is the clean Fit view. `levels/1.html` through `levels/3.html`
are ordinary, back-navigable detail links. Each level pre-renders a cumulative
LOD set from the sealed artifact, while higher levels enlarge the SVG in an
`overflow:auto` viewport for native mouse, keyboard, and touch scrolling.
Genre pages are ordinary URLs and list bounded production-map similarity peers.
All level, genre, stylesheet, and search paths are relative, so the directory
also works under a plain static server.

This is a static navigation preview, not a claim that the current source
projection has solved map-quality review. The sealed input still has visible
boundary pileups and a level-3 vertical concentration. Those are upstream
model/layout defects and are deliberately not hidden or reinterpreted by this
exporter's CSS.

`opennoise-static-manifest.json` is the release receipt. It binds the input
artifacts, counts, deterministic output hash, and raw/gzip bytes of every
served file. The full production input is not copied into `dist`: the receipt
binds it by byte and logical hash, while the public output contains only the
precomputed presentation and search index.

`wrangler.jsonc` declares `./dist` as a static Pages output directory and no
backend bindings. Deployment, remote renaming, and custom-domain work remain
separate authorized actions.
