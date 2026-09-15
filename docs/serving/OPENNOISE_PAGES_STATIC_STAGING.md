# OpenNoise static Pages release

OpenNoise has one delivery path: the semantic atlas exported as a static
Cloudflare Pages directory. The export creates no Functions, server-side
routes, API endpoints, database connection, or runtime graph service.

## Export

```sh
export OPENNOISE_SEMANTIC_MAP_LAYOUT=.cache/semantic-map-layout-v1/artifact.json
export OPENNOISE_PAGES_OUTPUT=dist
UV_OFFLINE=1 uv run --no-sync poe export-semantic-pages
```

The input is verified before export. The resulting static payload contains the
complete renderer view: 6,291 total names, 2,945 placed nodes, 3,346 unplaced
names, 24 overview regions, and 34,937 bounded structural edges. The map client
loads only `assets/semantic-atlas.json`; focused neighborhoods are selected from
the checked-in edge index in the browser.

`opennoise-static-manifest.json` binds the exact input byte and logical hashes,
coverage accounting, and checksums for every emitted file. It is the release
receipt.

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

Set `OPENNOISE_SEMANTIC_MAP_LAYOUT` and `OPENNOISE_PAGES_OUTPUT` first. The
gate writes `artifacts/semantic-map/browser.json` and screenshots, uses port
3001 for the loopback server, and atomically replaces an existing validated
output after the gate passes. To inspect an export manually on another port,
use `uv run poe dev -- --port 3010` (the passthrough separator is supported).

## Deploy

Cloudflare Pages uses `wrangler.jsonc` and uploads `./dist` directly:

```sh
wrangler pages deploy dist --project-name opennoise --branch main
```

The same directory is used locally and in production.
