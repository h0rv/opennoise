# Data pipeline

All source jobs are metadata-only. The enforced boundary and its archive,
transport, storage, and dependency checks are documented in
[`CONTENT_POLICY.md`](CONTENT_POLICY.md). Audio and music bytes are never valid
source artifacts.

The first Wikidata music slice is documented in
[`WIKIDATA_INGESTION.md`](WIKIDATA_INGESTION.md). Source adapters only parse and project verified
artifacts. The shared runner owns source snapshots, attempts, checkpoints, quarantine, policies,
transactions, provenance, and idempotency. Catalog projectors own direct SQLite normalization.

Musix uses SQLite for source metadata, import history, normalized music data,
search text, model evidence, and map publication. Migrations are ordered under
`migrations/`. A sealed public release copies verified local inputs into a
serving database. Application requests do not fetch sources or rebuild models.

Exact source bytes stay outside SQLite in a content addressed vault. The
importer hashes each file with SHA256 before parsing it. The lowercase digest
is also its `vault_key`. A vault object should live at a path derived from that
key, and no private source path should be stored in SQLite.

## Rights

Each source has a versioned policy. A policy decides these uses separately:

| Use | Meaning |
| --- | --- |
| `normalize` | Convert source records into catalog data. |
| `local_search` | Put approved text in local search. |
| `display` | Show data in the app. |
| `embed` | Use data as embedding input. |
| `train` | Use data to train or tune a model. |
| `export` | Copy data outside this installation. |

A missing, expired, denied, or unknown permission means denied. Policies and
permissions cannot change after they are sealed. A review creates a new policy
version. A policy marked `local_only` cannot allow export.

Anna's Archive input is treated as user supplied local data. The user must be
authorized to use that data. Musix does not download it or provide a way to
redistribute it. Its policy should use `user_authorized_local` and
`local_only = 1`.

## Import

Source ingestion is split by responsibility:

- `clients/` owns HTTP transport and resumable, checksum-verified vault writes.
- `sources/` owns explicit adapter registration, bounded parsing, and projection.
- `pipeline/` owns manifests, policy, snapshots, attempts, checkpoints, quarantine,
  provenance, idempotency, and transactions.
- `catalog/` owns direct-SQL repositories for typed catalog projections.
- Strict shared models live under `models/`; constrained scalar types live in
  `types.py`. The previous `models.py` imports remain available through
  `models/__init__.py`.

Adapters never write pipeline lifecycle SQL. Projectors never discover or
download artifacts. Registries are explicit and do not use reflection. Direct
SQLite remains the persistence layer; there is no ORM. If an ORM is approved
later, the project standard is SQLModel rather than SQLAlchemy's declarative ORM.

The laptop-safe MusicBrainz bootstrap is a deterministic SHA256 prefix partition:

```sh
uv run poe ingest-musicbrainz-artists
```

The default prefix `0` selects exactly 1/16 of the source-ID hash space while the
adapter scans and validates every source record. Use an empty prefix for a full
import. The archive remains content-addressed and ignored under
`data/source-cache`; reruns reuse verified bytes and completed attempts.
MusicBrainz artist records are capped at 64 MiB because a small number of
relationship-heavy upstream records exceed 50 MiB even though only bounded core
fields are projected. Larger records are hashed, quarantined, and skipped without
desynchronizing the following JSON line.

Artist records also carry bounded positive official-genre counts. These are
common catalog claims projected into append-only `artist_genre_evidence`, not a
source-specific lifecycle table. The hard cap is 128 unique genre UUIDs per
artist. Counts remain raw and source-qualified; ingestion does not normalize
them, select membership thresholds, or turn them into similarity.

`poe ingest-musicbrainz-research` reuses the verified artifact under a separate
local-only policy that permits noncommercial embedding and training while
denying export. The ordinary MusicBrainz JSON task does not grant those uses.
Public model builds exclude the research source until output attribution and
ShareAlike obligations have been explicitly approved.

The ListenBrainz bootstrap uses the pinned daily incremental listen dump:

```sh
uv run poe ingest-listenbrainz
```

The source is an official CC0 public dump. The manifest records its exact byte
count, SHA256, snapshot identifier, retrieval URL, and license URL. The
so-called 2025 ListenBrainz sample dump was inspected and is not a listen
fixture: it contains metadata JSONL, popularity CSV, and Spark Parquet only.
The 205 GB Spark full dump is deliberately disabled for laptop use.

The ListenBrainz adapter scans the complete selected incremental artifact and
keeps listener identifiers only in bounded in-memory dictionaries. It never
stages a username, numeric listener ID, track name, or submitted artist name.
For each fixed UTC day it counts an artist pair at most once per listener, then
emits only MusicBrainz-qualified artist IDs and a distinct-listener count. A
configurable minimum listener count is a privacy floor. The official
incremental can contain backfilled listens, so the adapter uses bounded
unordered windows and fails if active windows, user-windows, artists, pairs,
members, records, lines, decompression, or runtime exceed their declared
limits. A strict newest-first mode remains available for sources that promise
ordered windows.

`artist_co_listen_runs` records coverage, source and adapter hashes, window
policy, elapsed time, and peak memory. `artist_co_listen_evidence` stores the
time-windowed aggregate counts. Incomplete attempts are hidden from the
normalizable evidence view. These counts are evidence only: ingestion does not
turn them into similarity, normalize them, or choose model weights.

Daily incremental files are publication batches and can contain backfilled listens. Counts from
separate files must not be added after listener identities have been discarded because the same
listener and event day can occur in several files. The graph validation job scans its pinned files
together and deduplicates each listener and artist set before aggregation. It uses disjoint event
days and a privacy floor of five. Raw listener-bearing archives remain local and cannot be exported
or redistributed by the project manifest.

First, the importer creates a `source_snapshots` row and one or more
`source_artifacts` rows. Each artifact records its exact hash, byte count,
media type, and vault key.

Second, the importer records the parser in `parser_releases` and starts an
`ingest_attempts` row. The attempt records the parser, configuration, policy,
and safety limits. `ingest_attempt_events` stores progress and failures.

Third, the parser writes records to `staged_records`. Accepted records contain
valid JSON and exact hashes. Invalid input stays in `quarantine_events`.
Database triggers reject a record that comes from the wrong snapshot or breaks
an attempt limit.

Fourth, `source_objects` gives each upstream object a stable identity within
its source, record kind, namespace, and scope. `source_object_observations`
records present and deleted versions. `current_source_objects` returns the
latest objects that are still present.

Finally, an accepted and permitted observation can create a
`normalization_exports` row. A quarantined, denied, or suppressed record cannot
be normalized.

## Catalog

The main music chain is:

```text
work -> recording -> track -> medium -> release -> release_group
```

The schema also keeps artists, labels, credits, contributors, instruments,
territories, availability, identifiers, names, genres, descriptors, metrics,
collections, and assets. Provider values remain tied to their source and
provenance. External identifiers are indexed but are not assumed to be unique.

Claims are append only. A source can make several claims about one field, and
`canonical_claim_selections` records the accepted claim. Entity redirects need
a recorded match decision, and the schema rejects redirect and genre cycles.

## Search and maps

`search_documents_fts` is an SQLite FTS5 index. Queries must join its row ID to
`searchable_documents`, because that view checks the current policy and
suppression state. Display code should use views such as
`displayable_entity_names`, `displayable_assets`, and
`displayable_map_points`.

The public model and production-map artifact are immutable derived outputs. The
map artifact records its source-model hash, topology, display-parent decisions,
coordinates, LOD choices, label decisions, and quality evidence. A complete
release becomes visible only after certification selects it.

`content_fragments` prepares approved text for later embedding work.
`embeddable_content_fragments` and `trainable_content_fragments` apply separate
policy checks. The first schema does not choose an embedding model, vector
store, training method, or similarity score.

## Deletion

`suppression_events` can stop one use immediately. Policy aware views recheck
the latest suppression state. Search suppression also removes the affected FTS
rows.

A purge starts with `deletion_requests` and records progress in
`purge_run_events`. The importer removes vault bytes and staged payloads. It
then records only the approved digest in `tombstone_ledger`. Releasing a
suppression does not restore deleted data.

## Validation

Run the standard library tests with:

```sh
uv run python -m unittest tests.test_schema
```

The tests apply the migration to a fresh database and load the smoke fixture.
They check foreign keys, integrity, FTS5, map views, import gates, local policy,
and normalized catalog constraints. `migrations/smoke/validate.sh` runs the
same fixture with the SQLite command line tool and checks extra rejection
paths.
