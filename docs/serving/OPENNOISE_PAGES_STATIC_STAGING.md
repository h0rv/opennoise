# OpenNoise static Pages release

OpenNoise has one delivery path: the semantic atlas exported as a static
Cloudflare Pages directory. The export creates no Functions, server-side
routes, API endpoints, database connection, or runtime graph service.

## Export

```sh
uv run poe rebuild-semantic-map-layout
export OPENNOISE_SEMANTIC_MAP_LAYOUT=.cache/semantic-map-layout-v2/artifact.json
export OPENNOISE_PAGES_OUTPUT=dist
UV_OFFLINE=1 uv run --no-sync poe export-semantic-pages
```

The input is verified before export. The resulting static payload contains the
complete renderer view: 6,291 total names, 2,945 placed nodes, 3,346 unplaced
names, 24 overview regions, and 34,937 bounded structural edges. The map client
loads the content-addressed semantic-atlas path recorded under `semantic_atlas`
in `opennoise-static-manifest.json`; focused neighborhoods are selected from the
checked-in edge index in the browser.

`opennoise-static-manifest.json` binds the exact input byte and logical hashes,
coverage accounting, and checksums for every emitted file. It is the release
receipt.

The content-addressed discovery asset adds 260 genres with directly observed
artists and 1,008 artists from the public catalog snapshot. Search covers placed
genre names, aliases, and those artists. A genre opens its artist list; choosing
an artist shows direct genre memberships and other artists observed in that same
genre. Shared direct genre counts order those peers. They are not learned
similarity scores. Artist and genre selections are shareable URL state.

## Local verification

```sh
uv run poe dev
```

This starts a loopback static file server for `dist` at
<http://127.0.0.1:3001>. It fails clearly when no export exists. It does not
build an application backend.

The release gate combines sealed semantic-layout verification, static export,
the loopback server, and the CDP browser harness:

```sh
uv run poe certify-static-pages
```

The gate defaults to the canonical v2 layout and `dist`; set
`OPENNOISE_SEMANTIC_MAP_LAYOUT` or `OPENNOISE_PAGES_OUTPUT` to override either
path. It writes `artifacts/semantic-map/browser.json` and screenshots, uses
port 3001 for the loopback server, and atomically replaces an existing
validated output after the gate passes. Set `OPENNOISE_PAGES_CERTIFY_PORT` to
use another certification port when 3001 is occupied. To inspect an export
manually on another port, use `uv run poe dev -- --port 3010` (the passthrough
separator is supported).

## Deploy

Cloudflare Pages uses `wrangler.jsonc` and uploads `./dist` directly:

```sh
wrangler pages deploy dist --project-name opennoise --branch main
```

The same directory is used locally and in production.
