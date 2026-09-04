# Public release pipeline

`poe build-public-release` is the only command that builds a public serving release.

The command uses only the local cache. It never calls a public API, downloads
a source, or reads audio or music files. It needs the ignored local cache at
`data/phase3-public-qualified.sqlite`.

First, the command verifies the cache against the checked in Phase 3 manifest.
The cache stays at schema 10. Next, it copies the verified cache to a serving
database and applies schema 11. Finally, it rebuilds the public graph and
checks the input, settings, and logical output hashes.

The command writes three derived outputs:

- `data/public.sqlite` is the serving database. It includes names, layouts,
  representatives, profile memberships, neighbor rows, and their evidence.
- `data/model/phase3-public-model.json` is the rebuilt model artifact.
- `data/release/phase3-public-receipt.json` records the cache, model, schema,
  and row count hashes used for the build.

The model's logical hash is reproducible. The command records the model file
hash but does not use it as a rebuild check. The old file contains elapsed time
and peak memory values, which vary by run. The receipt includes both hashes.

The sealed input can be checked without rebuilding:

```sh
poe verify-phase3-release-manifest
poe verify-phase3-release-manifest --database data/phase3-public-qualified.sqlite
```

Serving profile and neighbor rows are immutable. The app hides a row if the
selected model, one of its source inputs, or either related genre is
suppressed. `GET /api/genres/{id}` returns the typed explanation in
`model_explanation`.
