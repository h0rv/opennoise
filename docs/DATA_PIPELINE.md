# Data pipeline

Musix uses one SQLite database at `data/musix.sqlite`. The schema is in
`migrations/0001_initial.sql`. The database stores source metadata, import
history, normalized music data, search text, and map layouts.

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

`layout_runs` records an algorithm version, input hash, parameters, status, and
policy. `layout_points` stores coordinates. A complete run becomes visible only
after `current_layouts` selects it.

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
