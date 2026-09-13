# OpenNoise Pages static staging

This release branch stages only the accepted semantic `production-map-v1`
artifact for a later reviewed static UI export. It deliberately does not emit
HTML, SVG, product copy, or a second coordinate projection. The existing UI
work supplies the map presentation after its commit is rebased here.

The sole input is an explicit, `export_allowed` production-map artifact. Its
Pydantic validation checks its complete semantic graph contract; the staging
receipt binds both its byte hash and its logical artifact hash. The staged
directory contains:

- `assets/production-map-v1.json`, byte-identical to the explicit input;
- `opennoise-static-staging-manifest.json`, with node, taxonomy-edge,
  similarity-edge, and unplaced counts plus both hashes.

It contains no backend API and must not be deployed by itself. After the UI
static exporter is integrated, it must consume this exact staged artifact and
precompute all SVG geometry, LOD, labels, and genre pages. The only permitted
browser code is the separately reviewed, deferred static search/navigation
module; it must not calculate graph geometry or layout.

The checked sealed input at this release checkpoint has byte SHA-256
`7b92fc8a2f45fc721d12eafc7ae117260045143282e36bde41938f8d602481df`,
logical SHA-256
`017fc6f0eeebbac1f59df907b69f1229083ad221a36a64986ad878fa47ee02fc`,
603 mapped nodes, 3,274 similarity edges, 712 taxonomy edges, and zero
unplaced nodes. Its deterministic staging receipt has logical SHA-256
`584456116ad7de16252d507ada77a6d90bd5dda73f7257500de7249384da7d10`.

Build staging into a new or empty directory:

```bash
UV_OFFLINE=1 uv run --no-sync python scripts/export_opennoise_pages.py \
  --production-map data/model/production-map-v1.json \
  --output dist
```

Once that UI export exists and local checks pass, Pages Direct Upload is:

```bash
npx wrangler pages deploy dist --project-name=opennoise
```

The committed `wrangler.jsonc` declares only the static `dist` output and has
no Pages Functions or backend bindings. Remote deployment and custom-domain
configuration remain a separate, authorized release action.
