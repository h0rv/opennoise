# Experiments

These modules record earlier experiments and reusable contracts. They are not
all disposable: some now feed the active data pipeline or database schema.

## Every Noise reconstruction baselines

Status: reusable evidence contract used by the construction and evaluation pipeline.

`src/opennoise/evidence/reconstruction.py` accepts versioned genre to artist membership observations,
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

Do not delete the shared reconstruction contract as a standalone cleanup: active
ingest, taxonomy, peer, history, and checkpoint code imports it. The evaluation
script can be audited separately from that contract.

## Map exploration data

Status: offline groundwork.

`src/opennoise/serving/exploration.py` defines typed viewport, source, time,
lens, and level-of-detail records used by offline database analysis. It does
not expose a browser route. The public map is generated from the independent
semantic-layout artifact by the static Pages exporter.

## Layout strategy interface

Status: database-facing contract, not the selected static Pages layout.

`src/opennoise/serving/map/layouts.py` defines a versioned strategy protocol,
explicit build inputs, artifact metadata, and a complete artifact output.
`src/opennoise/db.py` imports it; removing it requires a database and caller
migration, not just deleting an experiment.

Historical source coordinates and derived coordinates are separate model variants. The historical variant records its source artifact fingerprint and source units. A derived layout records its own units and strategy revision.

The current static Pages map uses the separate sealed semantic-layout artifact.

## Layout evaluation harness

Status: standalone measurement support.

`src/opennoise/serving/map/layout_metrics.py` evaluates a versioned point layout
without creating a layout, selecting a method, training a model, or writing
database state. `scripts/evaluate_layout.py` loads a published local layout and
reports only metrics that need no additional evidence.

This remains a plausible isolated cleanup candidate, but remove its module,
script, tests, Poe task, and documentation together after confirming no caller.

## Genre detail and provenance

Status: offline catalog groundwork.

The catalog stores display-safe source evidence and genre-detail records for
model construction and audit. The static map does not query a genre-detail API
or render server fragments.

## Albums within a genre

Status: local vertical slice with synthetic source records.

`src/opennoise/evidence/album_genres.py` treats a MusicBrainz release group as
the album and keeps edition selection separate. It stores typed membership
observations and publishes an unweighted evidence baseline.

The strategy contract also accepts transparent user weights and pairwise user judgments, but neither strategy selects default weights or trains a model. MusicBrainz adapters parse release groups and concrete releases. The Wikidata adapter parses direct P136 claims linked through MusicBrainz release group or release IDs.

Migration 0002 is in the current schema chain and representative-catalog code
imports this module. Keep both unless a separate schema migration and caller
removal are designed and tested.
