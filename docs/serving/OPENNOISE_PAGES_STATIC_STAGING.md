# OpenNoise static Pages release

OpenNoise has one delivery path: the semantic atlas exported as a static
Cloudflare Pages directory. The export creates no Functions, server-side
routes, API endpoints, database connection, or runtime graph service.

## Build

```sh
poe build
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

Artist detail also presents at most eight bounded similar-artist peers, each
derived only from shared directly observed genres; opening one retains a shared
direct genre as its URL and detail context.

## Local verification

```sh
poe dev
```

This starts a loopback static file server for `dist` at
<http://127.0.0.1:3001>. It fails clearly when no export exists. It does not
build an application backend.

The release gate combines sealed semantic-layout verification, static export,
the loopback server, and the CDP browser harness:

```sh
poe build
```

For local `poe build` work only, the gate defaults to the canonical v3 layout and `dist`; set
`OPENNOISE_SEMANTIC_MAP_LAYOUT` or `OPENNOISE_PAGES_OUTPUT` to override either
path. `poe deploy` rejects these overrides and pins the canonical layout and
discovery database hashes before export. It writes `artifacts/semantic-map/browser.json` and screenshots, uses
port 3001 for the loopback server, and atomically replaces an existing
validated output after the gate passes. Set `OPENNOISE_PAGES_CERTIFY_PORT` to
use another certification port when 3001 is occupied. To inspect an export
manually on another port, use `poe dev -- --port 3010` (the passthrough
separator is supported).

## Deploy

Deploy only through Poe. It builds and certifies `dist` before it uploads the
directory to Cloudflare Pages:

```sh
poe deploy
```

The same directory is used locally and in production.
