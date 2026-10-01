# OpenNoise

OpenNoise is an open, metadata-only music graph and a static semantic atlas.
Offline Python tooling ingests bounded source snapshots, builds evidence and
layout artifacts, and exports one backend-free web directory. The browser only
loads precomputed JSON, HTML, CSS, and JavaScript; it never calls an OpenNoise
API or computes a graph layout.

No audio recordings or audio previews enter the project.

The [open foundation](docs/foundation/README.md) now includes runnable CC0
examples, a stage/input inventory, overlapping style-model research, separate
sonic and cultural comparisons, and historical evaluation tooling. The
[2026-10-01 checkpoint](docs/checkpoints/OPEN_FOUNDATION_IMPLEMENTATION_20261001.md)
records the simpler discovery UI, credited music links, confirmed rare-style
recovery gain, and remaining musical parity gaps. Full-corpus research and
canonical publication still require additional retained inputs.

The latest local research combines a named-style atlas, learned broad/sub/micro
communities, and source genres in one static discovery export. It includes all
198,409 source artists, 3,920 default candidate style names, and 3,505 bounded
artist maps. Candidate names and source geometry do not establish Every Noise
musical parity. The [product checkpoint](docs/checkpoints/LOCAL_DISCOVERY_PRODUCT_20260930.md)
records reproduction, exact receipts, and real-browser certification. The
[bulk source checkpoint](docs/checkpoints/MUSICBRAINZ_BULK_ARTIST_TAG_SOURCE_20260930.md),
[paired evaluation](docs/checkpoints/EMERGENT_COMMUNITY_EVALUATION_CONTRACT_20260930.md),
and [bulk atlas checkpoint](docs/checkpoints/NAMED_STYLE_ATLAS_BULK_BUILD_20260930.md)
record source coverage, measured gains, and remaining gaps. These research
artifacts are separate from the canonical publication below.
The [AcousticBrainz pilot](docs/checkpoints/ACOUSTICBRAINZ_BENCHMARK_METADATA_20260930.md)
verifies a bounded additional source of recording-level sonic metadata; it
changes no model or published artist genres.

## Static delivery

The canonical publication path is the verified semantic atlas. It accounts for
all 6,291 retained names: 2,945 placed nodes, 3,346 honest abstentions, 24
overview regions, and bounded local structural edges.

```sh
mise install
poe sync
poe check
poe build
poe dev
```

Open <http://127.0.0.1:3001>. `poe dev` is a loopback file server for the
already-exported `dist` directory. Cloudflare Pages deploys that same directory;
there is no application server, server-side route, or backend API to configure.

A fresh clone can run `poe sync` and `poe check`. Building the canonical release
also requires the retained, ignored `data/public.sqlite` and
`.cache/semantic-map-layout-v3/artifact.json` inputs. Release integration tests
skip explicitly when their sealed inputs are absent; checkout checks do not
replace the release and browser certification gates.

`dist/opennoise-static-manifest.json` is the release receipt. It binds the
semantic-layout input hashes, coverage accounting, and every served asset.

Deploy a certified `dist` directory with `poe deploy`.

The supported Poe commands are `sync`, `bootstrap`, `check`, `dev`, `build`,
and `deploy`. `poe bootstrap` is only needed when preparing the historical
Every Noise source cache. Archived checkpoint and research documents can name
retired Poe invocations. Run the named scripts directly instead of treating
those invocations as supported tasks.

## Offline construction

Source adapters remain explicit and provenance-bound. They ingest approved
metadata from Wikidata, MusicBrainz, ListenBrainz aggregates, and
user-authorized local inputs. Every model build records its source snapshots,
parameters, and hashes. Historical Every Noise labels and coordinates remain a
dated reference, never a training or serving input for the open model.

See [the static release contract](docs/serving/OPENNOISE_PAGES_STATIC_STAGING.md),
[the semantic layout contract](docs/serving/SEMANTIC_MAP_LAYOUT.md), and
[the historical reconstruction boundary](docs/ingest/EVERY_NOISE_REPRODUCTION.md).
The [local album-context query](docs/serving/LOCAL_ALBUM_DISCOVERY_CONTEXT.md)
connects verified album, artist, and playlist research inputs by exact IDs.
The [source model and UI checkpoint](docs/checkpoints/SOURCE_MODEL_UI_BATCH_20260930.md)
provides reproducible local workflows for the portable MusicBrainz model,
metadata enrichment, source-model explorer, and revised public-data UI preview.
The [Every Noise parity checkpoint](docs/EVERYNOISE_PARITY.md) measures remaining
coverage gaps and reproduces the fuller local explorer with complete source
artist navigation, artist maps, name enrichment, and release metadata.
The [emergent community checkpoint](docs/checkpoints/EMERGENT_MUSIC_COMMUNITIES_20260930.md)
records the richer open-tag pipeline, learned broad/sub/micro communities,
independent predictive and stability checks, exact reference-artist coverage,
and the static hierarchy explorer. Initial source genres are not its vocabulary
ceiling; measured semantic and predictive gaps remain explicit.
