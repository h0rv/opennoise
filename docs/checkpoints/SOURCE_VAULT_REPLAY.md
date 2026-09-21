# Source vault replay preflight

`replay_source_vault.py verify` is an offline, manifest-bound preflight for the
raw inputs of the qualified Phase 3 release. It first runs the full checked-in
release-manifest validator, then streams every declared object at
`raw/sha256/<artifact_sha256>`, checking its byte count and SHA-256. The report
binds the exact release-manifest file hash and all 62 object identities.

```sh
poe verify-release-source-vault \
  --vault .worktrees/phase3-public-evidence/data/phase3-final-vault \
  --report .cache/source-vault-replay-v1.json
```

`restore` requires the same manifest again, rejects an existing destination,
stages every pull through `LocalObjectStore`, and atomically publishes the
fresh restored directory only after all hashes pass:

```sh
poe restore-release-source-vault \
  --report .cache/source-vault-replay-v1.json \
  --object-store .worktrees/phase3-public-evidence/data/phase3-final-vault \
  --destination /tmp/phase3-restored-vault
```

## Candidate SQLite replay

`candidate-database` is an offline, fresh-database replay boundary. It requires
the successful custody report, rehashes each raw object it consumes from the
supplied local vault, and refuses an existing output database. It does not
rehash the unsupported ListenBrainz blobs after the custody report has already
verified them. It never reads or replaces the sealed Phase 3 SQLite cache, and
it does not make a network request: a missing consumed vault object fails in
the downloader's explicit offline mode before an HTTP client is created.

```sh
poe replay-release-source-vault-candidate \
  --report .cache/source-vault-replay-v1.json \
  --vault .worktrees/phase3-public-evidence/data/phase3-final-vault \
  --candidate-database .cache/phase3-raw-vault-candidate.sqlite \
  --replay-report .cache/phase3-raw-vault-candidate-replay.json
```

The supported subset is exactly the 54 `wikidata_phase3_*` SPARQL JSON objects.
They replay through `wikidata_music_sparql_slice_v1` into a new local candidate
database. The seven `listenbrainz_incremental_*` artifacts and the generated
`listenbrainz_joint_*` object are recorded as unsupported by this Wikidata-only
command. They have a separate candidate command below.

The result is explicitly `certified_database: false` and
`byte_identical_database_replay: false`. The release manifest does not retain
the original per-source downloader declarations needed to reproduce its stored
source-manifest hashes. The retained joint artifact does bind the fixed-window
ListenBrainz aggregation configuration, but not the historical source
declarations. Current schema and ingestion timestamps
also differ from the sealed Phase 3 cache. The existing Phase 3 publication
command therefore still starts from that separately certified SQLite cache.

A local run on 2026-09-21 ingested all 54 supported objects into a fresh
schema-v12 candidate and reported all eight ListenBrainz objects as
unsupported. `PRAGMA integrity_check` returned `ok` and `foreign_key_check`
found no violations. The candidate has the same 1,331 artist rows and the
same 746 genre slug/name pairs as the sealed public database. Genre row IDs,
provenance, and the database bytes differ, so those matches do not constitute
release certification.
The sorted projection of Wikidata identifier plus claim type, key, normalized
value, language, and validity dates also matches between candidate and sealed
database (CSV SHA-256
`6049f458c9130008c9c032f904f0d9c0c62a8d4aaba8bfe1e6947ec1f7c78e5a`).
This compares open source claim content, not release provenance or rights.

## ListenBrainz candidate replay

The separate `candidate-listenbrainz-database` path hashes the seven daily
objects and the 1,534-byte sealed joint receipt before parsing. It checks the
recovered aggregation configuration hash before opening the large archives,
and it requires the regenerated joint receipt to match the sealed artifact
byte-for-byte. It creates a fresh derived candidate database and temporary
derived vault. It never mutates the sealed database or source vault. The
report remains uncertified because current source declarations do not reproduce
the historical declaration hashes.

```sh
poe replay-release-source-vault-listenbrainz-candidate \
  --report /tmp/phase3-source-vault-replay.json \
  --vault .worktrees/phase3-public-evidence/data/phase3-final-vault \
  --candidate-database /tmp/phase3-listenbrainz-candidate.sqlite \
  --replay-report /tmp/phase3-listenbrainz-candidate-replay.json
```

On a laptop without the execution time limit, the exact command used for the
uncompleted local attempt is:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/replay_source_vault.py candidate-listenbrainz-database \
  --manifest .worktrees/phase3-public-evidence/config/releases/phase3-public-20260831/release-manifest.json \
  --report /tmp/phase3-source-vault-replay.json \
  --vault .worktrees/phase3-public-evidence/data/phase3-final-vault \
  --candidate-database /tmp/phase3-listenbrainz-candidate.sqlite \
  --replay-report /tmp/phase3-listenbrainz-candidate-replay.json \
  --source-manifest .worktrees/phase3-public-evidence/config/data_sources.toml
```

The 62-object vault was reverified on 2026-09-21: 1,541,940,352 bytes,
release-manifest SHA-256
`795992807586432e2b285e2ddca9a24a00a16e9fc83b6c382a3e914539333232`.
The recovered configuration matched the 1,534-byte sealed joint receipt in
preflight. A full seven-day candidate database did **not** finish in this
execution environment: repeated jobs were terminated before source rows were
committed, and no persistent process session was available. The command above
is reproducible on a machine without that tool limit. No success count or
certification is claimed for the unfinished candidate.
