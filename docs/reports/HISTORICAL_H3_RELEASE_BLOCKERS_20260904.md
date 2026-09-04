# Historical H3 release blockers

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
