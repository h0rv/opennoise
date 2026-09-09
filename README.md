# Musix

Musix is an open, metadata-only music graph. It builds explainable genres,
artist membership, similarity, hierarchy, and representative album and recording metadata examples,
and a semantic map from bounded public data.

The default public model has 603 independently built genres. The 6,291 Every
Noise labels and coordinates are a separate, dated historical reference. They
do not train, place, or score the public model.

## Open construction graph

The retained legacy vocabulary can also be rendered as a bounded,
public-taxonomy-only graph. It retains all 6,291 labels, records confidence and
edge evidence, and treats compositional anchors as review links rather than
memberships or factual parentage. See
[the open construction graph contract](docs/serving/OPEN_CONSTRUCTION_GRAPH.md).

When the app is started with the checked-in defaults, Open v2 is the main
surface: `data/model/open-construction-graph-v2.json` contains 7,037 nodes and
3,317 typed edges (including all 6,291 legacy names). The v1 Open artifact is
the compatibility fallback when v2 is explicitly disabled. Run
`uv run poe open-v2-qa -- --base-url http://127.0.0.1:3001` against a running
app to write a bounded API and no-script fallback report.

For repeatable Chromium evidence, set `MUSIX_OPEN_V2_BROWSER_URL` to the local
app URL and run `uv run poe open-v2-browser-qa`; the task writes desktop light,
mobile dark, and no-JavaScript captures plus interaction checks under the
configured output directory.

No music, preview, or audio bytes enter the project.

## Local MusicBrainz name-seed research graph

The prefix-0 MusicBrainz research cache can produce a separate 724-genre,
metadata-only research graph. It uses only matched legacy *names* as vocabulary
seeds plus direct positive MusicBrainz artist--genre evidence. The builder opens
the completed research SQLite read-only to verify every retained evidence
reference. The output records evidence references, weighted Jaccard and cosine
overlap, bounded neighbors, and a deterministic topology landscape seeded from
genre IDs and names. It is
`CC-BY-NC-SA-3.0-local-research`, is explicitly not an exportable public model,
and never contains audio or music files.

```sh
uv run poe build-musicbrainz-research-graph
MUSIX_MB_RESEARCH_GRAPH_SHA256=<logical-output-sha256> \
  uv run poe evaluate-musicbrainz-research-graph
```

The build rejects any input that contains historical coordinates, historical
artist assignments, or historical neighbors. Evaluation is a separate command:
it first verifies the graph's logical output hash, then reads only historical
node names/IDs and neighbor ranks to report name overlap and topology recall.

## Run

Python is pinned to 3.13.14. mise installs Python and uv. Poe is the sole
project task runner and uses uv to install the locked environment.

```sh
mise install
uv run poe sync
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
map artifact that passes those checks. This checkout's retained sealed cache is
used automatically when `data/phase3-public-qualified.sqlite` is absent; see
`docs/serving/PUBLIC_RELEASE_PIPELINE.md` for the release inputs and outputs.

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
[the source-to-release pipeline](docs/serving/PUBLIC_RELEASE_PIPELINE.md), and
[the historical reconstruction boundary](docs/ingest/EVERY_NOISE_REPRODUCTION.md).
