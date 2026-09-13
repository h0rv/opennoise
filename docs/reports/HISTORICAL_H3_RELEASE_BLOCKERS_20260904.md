# Historical H3 release blockers

## Custody workflow (implemented)

The operator can now seal the two operator-supplied H3 inputs without adding either
blob to the checkout:

```sh
export OPENNOISE_HISTORICAL_H3_SOURCE=/path/to/spotify_genres_artists_map.json
export OPENNOISE_HISTORICAL_MEMBERSHIP_DATABASE=/path/to/historical-memberships.sqlite
export OPENNOISE_HISTORICAL_OBJECT_STORE=/path/to/local-vault
export OPENNOISE_HISTORICAL_CUSTODY_RECEIPT=/path/to/historical-h3-rebuild.receipt.json
export OPENNOISE_HISTORICAL_MANIFEST=/path/to/historical-compatibility.json
poe custody-historical-inputs
```

The task verifies the configured raw-source SHA-256 and byte count, source and
projection counts, and the source-scoped SQLite rows before publishing both files
through the `ObjectStore` protocol. It uses content-addressed keys below the
configured vault and writes an atomic Pydantic receipt containing both keys and
hashes, H3/H2 manifest hashes, the local-display policy key, model settings, the
exact signal rebuild command, Python version, and code revision. The default
promotion state remains disabled.

The sealed raw H3 JSON and its derived membership SQLite currently exist only
under `.worktrees/final-integration/.cache`. That location is not a release
artifact bundle and can be removed by normal worktree or cache cleanup.

Before any historical-signal promotion, final integration must:

1. Write the pinned raw JSON through `LocalObjectStore` under a
   content-addressed vault key, retaining its expected SHA-256 and byte count.
2. Store the derived SQLite as a separate content-addressed local object and
   bind its SHA-256, the H3 source SHA-256, local-display policy key, H2
   manifest SHA-256, model settings, and rebuild command in a receipt.
3. Rebuild in two independent processes with distinct `PYTHONHASHSEED` values
   and require identical serialized-map and internal artifact hashes.
4. Keep the default promotion state disabled until the source-data rights and
   local-display policy permit the intended release.

Do not commit either raw source or SQLite database to the repository.
