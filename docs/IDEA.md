# Musix

Musix is a local reproduction of the Every Noise genre map. The first demo displays 6,291 microgenres from a pinned and verified snapshot. Search and map focus work without a client application framework.

## Stack

The project uses Python 3.13 or newer and uv. mise pins Python and uv, while Poe runs project tasks.

Litestar provides asynchronous routes and application lifecycle. Jinja renders HTML and the SVG map on the server. The app self-hosts exactly htmx 4.0.0 for search and map fragment replacement. It does not use Alpine or custom JavaScript.

Pydantic parses settings, source records, import options, catalog values, and web response models. Async routes use a small bounded worker boundary around short standard library sqlite3 operations. Each operation owns its connection. The project has no ORM.

Ruff enables all rules, with documented exceptions for rules that conflict with its formatter or this project's error policy. ty treats all supported diagnostics as errors.

## Storage

One SQLite database and one baseline migration store the catalog, search index, published layout, rights, provenance, ingest attempts, and quarantine events. Source bytes stay in an external content addressed vault. Raw bytes and local source paths do not enter SQLite.

SQLite uses foreign keys, a five second busy timeout, write ahead logging, and normal synchronous mode. Each web and import operation opens its own short lived connection and completes one whole database operation before the worker returns.

## Data

The initial map uses a pinned snapshot of the Every Noise reproduction by Quint T. The adapter verifies the exact byte count and SHA256 before parsing. It keeps genre names, source identifiers, coordinates, colors, and display sizes. It removes preview links, Spotify identifiers, track names, and sample artist names.

The source policy is user authorized and local only. It allows normalization, local search, display, embedding, and training. It denies export. Running the bootstrap twice produces the same 6,291 entities and layout points.

MusicBrainz, Wikidata, and ListenBrainz adapters provide public metadata for later enrichment. Each adapter emits separate typed source claims. Enrichment must not overwrite the historical Every Noise coordinates.

## Pipeline

The importer hashes every artifact, stores it in the external vault, parses bounded JSONL records, and records each attempt. Limits cover artifact bytes, record bytes, record count, nesting depth, and run time. Invalid records go to quarantine. Accepted records produce normalized entities, names, identifiers, search documents, and provenance links.

The bootstrap then publishes a versioned layout. Building a layout does not change the current map until the run is complete and selected.

## Machine learning

The first demo is metadata first and does not process audio. Later work can use genre relationships, artist links, listening co-occurrence, and text metadata to learn embeddings. Each training choice, split, metric, and evaluation result should be reviewed with the user before it becomes part of the default pipeline.

Small metadata models and embedding experiments are viable on an older laptop. Start with sparse graph methods, truncated singular value decomposition, or small CPU models. Audio models and large end-to-end training are deferred.

## Interface

The main page contains only the map, search, and a small entity count. Jinja renders the SVG points. CSS handles hover, keyboard focus, and the selected point. htmx returns search results and replaces the map fragment when the user selects one.

## Tasks

`uv run poe bootstrap` downloads, verifies, imports, and publishes the initial map. `uv run poe dev` starts the local server. `uv run poe check` runs formatting verification, Ruff, ty, tests, and schema validation.
