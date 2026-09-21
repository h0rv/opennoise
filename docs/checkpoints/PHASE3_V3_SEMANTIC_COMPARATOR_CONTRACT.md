# Phase 3 v3 semantic comparator contract

The reusable comparator is a read-only comparison of four caller-pinned bytes:
the v3 model and serving SQLite database, plus the sealed model and SQLite
database. It verifies all SHA-256 pins before parsing a model or opening a
database. SQLite uses `mode=ro&immutable=1` and `PRAGMA query_only=ON`.

Each projection is a sorted array of JSON tuples. Canonical bytes are
`json.dumps(rows, ensure_ascii=False, allow_nan=False, separators=(',', ':'),
sort_keys=True).encode('utf-8')`; the reported SHA-256 is of those bytes. The
comparison never depends on SQLite primary keys, model output hashes as a
semantic equality value, resource timings, or database run IDs.

The model boundary is parsed once into strict typed Pydantic records containing
the named fields in the table below, plus `input_sha256`, `settings_sha256`,
and `output_sha256` for the database-run binding. Other model fields are
intentionally excluded from this source-neutral semantic contract; the
caller-supplied byte SHA-256 pins still bind each complete model file.
Provenance rows require a SQLite model run whose output, input, and settings
hashes exactly match the parsed model. The comparison never selects the latest
run or treats a database run ID as a semantic equality value.

| Projection | One tuple per row, in tuple order | Sort order |
| --- | --- | --- |
| Source artifact identities | `source`, `snapshot`, `artifact_key`, `content_sha256`, `export_allowed` | whole tuple |
| Genre universe | `genre_id`, `name` | whole tuple |
| Direct / one-hop memberships | `genre_id`, `artist_id`, `score`, sorted component tuples `(component_kind, raw_value, normalized_value)` | whole tuple |
| Co-listen raw windows | `left_artist_source_id`, `right_artist_source_id`, `window_start`, `window_end`, `distinct_user_count` | SQL fields in that order |
| Artist-pair supports and windows | `left_artist_source_id`, `right_artist_source_id`, `sum(distinct_user_count)`, `count(*)` | artist IDs |
| Neighbors | `genre_id`, `neighbor_genre_id`, `profile_kind`, `metric`, `score`, `shared_artist_count`, `rank` | whole tuple |
| Representatives | `genre_id`, `entity_kind`, `entity_id`, `name`, `rank`, `direct_evidence_value`, `source_count` | whole tuple |
| Layout coordinates | `layout_key`, `genre_id`, `x`, `y`, `component` | whole tuple |
| Layouts and unplaced | `layout_key`, `is_default`, `method`, `method_version`, `input_kind`, `metric`, `seed`, sorted unplaced tuples `(genre_id, reason)` | whole tuple |
| Normalized provenance bindings | `source_key`, `provenance.snapshot_ref`, `provenance.artifact_sha256`, `provenance.record_fingerprint`, `provenance.parser_release_ref`, `binding artifact.sha256` | SQL fields in that order |

One-hop membership and component evidence-reference strings are the sole
intentional exclusion: v3 compacts their representation. All other fields in
the listed tuples are exact. The comparator returns a nonzero CLI status for
any unequal projection but still emits its precise per-side counts and hashes.
For an unequal projection, it also reports multiplicity-aware `v3_only_rows`
and `sealed_only_rows` counts; these are not a normalization exception.
