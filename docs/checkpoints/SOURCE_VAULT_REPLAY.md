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
`listenbrainz_joint_*` object are recorded as unsupported, rather than silently
skipped or treated as equivalent evidence.

The result is explicitly `certified_database: false` and
`byte_identical_database_replay: false`. The release manifest does not retain
the original per-source downloader declarations needed to reproduce its stored
source-manifest hashes, and it does not retain the historic ListenBrainz joint
aggregation configuration/provenance. Current schema and ingestion timestamps
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
