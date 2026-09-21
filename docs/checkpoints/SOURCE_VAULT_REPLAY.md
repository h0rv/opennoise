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

This checkpoint proves raw-object custody and safe restoration. It does not
ingest restored payloads into SQLite, rerun the source adapters, or prove a
byte-identical derived database/model. Those remain the next replay boundary;
the existing Phase 3 publication command starts from a sealed SQLite cache.
