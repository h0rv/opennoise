# OpenNoise

OpenNoise is an open, metadata-only music graph and a static semantic atlas.
Offline Python tooling ingests bounded source snapshots, builds evidence and
layout artifacts, and exports one backend-free web directory. The browser only
loads precomputed JSON, HTML, CSS, and JavaScript; it never calls an OpenNoise
API or computes a graph layout.

No music, preview, or audio bytes enter the project.

## Static delivery

The canonical publication path is the verified semantic atlas. It accounts for
all 6,291 retained names: 2,945 placed nodes, 3,346 honest abstentions, 24
overview regions, and bounded local structural edges.

```sh
mise install
uv run poe sync
uv run poe check

uv run poe rebuild-semantic-map-layout
export OPENNOISE_SEMANTIC_MAP_LAYOUT=.cache/semantic-map-layout-v2/artifact.json
export OPENNOISE_PAGES_OUTPUT=dist
UV_OFFLINE=1 uv run --no-sync poe export-semantic-pages
uv run poe dev
```

Open <http://127.0.0.1:3001>. `poe dev` is a loopback file server for the
already-exported `dist` directory. Cloudflare Pages deploys that same directory;
there is no application server, server-side route, or backend API to configure.

`dist/opennoise-static-manifest.json` is the release receipt. It binds the
semantic-layout input hashes, coverage accounting, and every served asset.

## Offline construction

Source adapters remain explicit and provenance-bound. They ingest approved
metadata from Wikidata, MusicBrainz, ListenBrainz aggregates, and
user-authorized local inputs. Every model build records its source snapshots,
parameters, and hashes. Historical Every Noise labels and coordinates remain a
dated reference, never a training or serving input for the open model.

See [the static release contract](docs/serving/OPENNOISE_PAGES_STATIC_STAGING.md),
[the semantic layout contract](docs/serving/SEMANTIC_MAP_LAYOUT.md), and
[the historical reconstruction boundary](docs/ingest/EVERY_NOISE_REPRODUCTION.md).
