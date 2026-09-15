# Experiments

These modules define small interfaces for product work after the first map. None of them selects a ranking or layout method.

## Every Noise reconstruction baselines

Status: standalone experiment support.

`src/opennoise/reconstruction.py` accepts versioned genre to artist membership observations,
candidate coordinates, historical coordinates, colors, and neighbor lists. The metadata-only
boundary intentionally has no audio descriptor or audio artifact contract. It records historical
claims as disclosed, observed, inferred, or unknown. The first baselines calculate weighted
Jaccard or cosine similarity only for genre pairs that share an artist. The evaluator bounds total
pair visits, unique candidate pairs, grid runs, aggregate output, and quadratic coordinate neighbor
work. It measures direct overlap neighbor recall, two dimensional Procrustes alignment, normalized
coordinate error, and axis correlations. Results include the input artifact fingerprints, claims,
evaluation settings, and tested parameters. Results always state that they are candidate
approximations and do not claim exact recovery of private historical weights.

`scripts/evaluate_reconstruction.py` reads a JSON experiment manifest up to 16 MiB, validates it, and prints a JSON result. It does not read or write application state. Tests use synthetic data only.

Delete path: remove `reconstruction.py`, `tests/test_reconstruction.py`, and `scripts/evaluate_reconstruction.py`. The application, database, import jobs, and published layouts do not import the harness.

## Map exploration data

Status: offline groundwork.

`src/opennoise/serving/exploration.py` defines typed viewport, source, time,
lens, and level-of-detail records used by offline database analysis. It does
not expose a browser route. The public map is generated from the independent
semantic-layout artifact by the static Pages exporter.

## Layout strategy interface

Status: contract only.

`src/opennoise/layouts.py` defines a versioned strategy protocol, explicit build inputs, artifact metadata, and a complete artifact output. Every artifact records its strategy revision, parameters, input fingerprint, seed, policy, point count, and bounds. No strategy is registered as the default.

Historical source coordinates and derived coordinates are separate model variants. The historical variant records its source artifact fingerprint and source units. A derived layout records its own units and strategy revision.

Delete path: remove `layouts.py`, the layout metadata route, and the `Database.layout_metadata` methods. Existing layout tables and the main map continue to work.

## Layout evaluation harness

Status: standalone measurement support.

`src/opennoise/layout_metrics.py` evaluates a versioned point layout without creating a layout, selecting a method, training a model, or writing database state. It accepts typed optional source neighbor lists, label boxes, community memberships and edges, a previous revision, and a repeated result. The evaluator reports neighbor preservation and conservative trustworthiness, bounded label collisions, viewport density and entropy, within-community fragmentation, direct revision movement, coordinate hashes, repeat agreement, and simple SVG and Canvas budgets. `scripts/evaluate_layout.py` loads a published local layout and reports only metrics that need no additional evidence.

Delete path: remove `layout_metrics.py`, `tests/test_layout_metrics.py`, `scripts/evaluate_layout.py`, and the `evaluate-layout` Poe task. The map, routes, schema, and layout strategy interface do not depend on the harness.

## Genre detail and provenance

Status: offline catalog groundwork.

The catalog stores display-safe source evidence and genre-detail records for
model construction and audit. The static map does not query a genre-detail API
or render server fragments.

## Albums within a genre

Status: local vertical slice with synthetic source records.

`src/opennoise/evidence.py` treats a MusicBrainz release group as the album and keeps edition selection separate. `src/opennoise/album_genres.py` stores typed membership observations and publishes an unweighted evidence baseline. The baseline sorts eligible albums by independent direct source count, then by direct observation count. It records every component and says that no weights were applied.

The strategy contract also accepts transparent user weights and pairwise user judgments, but neither strategy selects default weights or trains a model. MusicBrainz adapters parse release groups and concrete releases. The Wikidata adapter parses direct P136 claims linked through MusicBrainz release group or release IDs.

Delete path for a database that has not applied migration 0002: remove `album_genres.py`, its focused tests and fixtures, and migration 0002. Restore schema version 1 and the single migration path in `db.py`. `evidence.py` can remain as an unused contract, or it can be removed with `tests/test_experiment_contracts.py`.

Delete path for a database that has applied migration 0002: keep migration 0002 unchanged. Add a new migration that first drops `displayable_album_genre_ranking_items` and `displayable_album_genre_memberships`. It should then drop the ranking evidence links, items, runs, and membership observation tables in that order. Remove `album_genres.py`, its focused tests and fixtures, and the adapter additions. The main map, core importer, and current UI do not read these tables.
