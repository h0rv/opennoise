# Musix

Musix is an open, metadata-only music graph. It builds explainable genres,
artist membership, similarity, hierarchy, and representative album and recording metadata examples,
and a semantic map from bounded public data.

The default public model has 603 independently built genres. The 6,291 Every
Noise labels and coordinates are a separate, dated historical reference. They
do not train, place, or score the public model.

No music, preview, or audio bytes enter the project.

## Run

Python is pinned to 3.13.14. mise installs Python and uv. uv installs the
locked environment. Poe runs project tasks.

```sh
mise install
mise run sync
uv run poe check
```

Build or verify a sealed local release before serving a production map. The
release uses only its local cache and never fetches data during serving.

```sh
uv run poe release-certify
MUSIX_DATABASE_PATH=data/public.sqlite \
MUSIX_PRODUCTION_MAP_PATH=data/model/production-map-v1.json \
uv run poe dev
```

Open <http://127.0.0.1:3001>.

`release-certify` fails closed until the qualified source cache, public model,
map artifact, and renderer evidence agree. The product only serves a configured
map artifact that passes those checks.

## Stack

- Python 3.13.14, uv, mise, Poe, Ruff, and ty.
- Litestar async routes, Jinja templates, Pydantic models, and standard-library
  SQLite persistence. If an ORM becomes necessary, the project choice is
  SQLModel rather than declarative SQLAlchemy.
- HTMX 4 for search, detail fragments, ordinary URLs, and history.
- A vendored Cytoscape.js 3.34 island for pan, wheel or pinch zoom, graph
  selection, and semantic level of detail.
- Local content-addressed object storage behind a small adapter. R2 or S3 can
  implement the same interface later.

The graph island is optional. Search and genre URLs remain ordinary HTML links.
The server-rendered SVG is the no-script fallback, not the production renderer.

## Data boundary

Source adapters are small and explicit. They ingest approved metadata from
Wikidata, MusicBrainz, ListenBrainz aggregates, and user-authorized local
inputs. Each source has a snapshot, hash, policy, provenance, and bounded
parser contract. The public model uses only sources whose policy permits the
specific output.

ListenBrainz contributes privacy-thresholded aggregate artist co-listens. Raw
listens and listener identifiers are not published. Anna's Archive is never a
default source or downloader. A user-authorized local source remains local and
subject to its policy.

## Product model

The production map has one view. At a distance it shows umbrella regions.
Zooming keeps prior context and introduces genres, then deeper subgenres. The
taxonomy remains a DAG. Any single display parent is a versioned presentation
choice, not a claim that a multi-parent genre has one true parent.

A selected genre exposes compact direct and one-hop membership components plus
ranked similarity scores. Representative album and recording metadata examples
show their direct-evidence rank and source count, never imply quality or
popularity, and link only to exact external metadata pages.

See [the stack and architecture](docs/STACK.md),
[the source-to-release pipeline](docs/PUBLIC_RELEASE_PIPELINE.md), and
[the historical reconstruction boundary](docs/EVERY_NOISE_REPRODUCTION.md).
