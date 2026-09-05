# Public release custody

`poe public-release-custody` verifies and seals the qualified Phase 3 public
release without downloading or rebuilding any source. The command is
cache-only: it opens the SQLite cache read-only, checks its declared SHA-256,
size, schema, SQLite integrity, manifest boundary, and expected source-table
counts, then streams the cache into a content-addressed `LocalObjectStore`.

When the recorded raw source vault is present, the command also streams the 62
manifest-bound source objects under `raw/sha256/<artifact-sha256>`. It checks
each recorded `vault_key`, size, and digest. Missing raw inputs do not make the
qualified cache unusable: the receipt records their exact paths and marks the
run `source_completeness: "cache_only"` instead of claiming source-complete
custody.

The release model, production map, acceptance, seed, browser, and report JSON
files are likewise streamed and bound by content hash. A single Pydantic
`public-release-custody-receipt.json` is written atomically after all checks and
contains the exact command, Python version, code revision, cache identity,
source custody state, evidence identities, and checked counts. Large inputs are
copied in bounded chunks and are never loaded into memory as byte strings.

The default task paths assume the sibling evidence worktrees used for the
qualified release. For another checkout, pass `--cache-database`,
`--source-vault`, `--evidence-directory`, and `--output-directory` explicitly.
The default run writes objects and the receipt below the ignored project cache:

```
.cache/public-release-custody/
├── objects/cache/sha256/<cache-sha256>.sqlite
├── objects/raw/sha256/<source-sha256>
├── objects/evidence/<name>/<evidence-sha256>.json
└── public-release-custody-receipt.json
```

The source-object key scheme also cleanly references any retained
content-addressed MusicBrainz artist object: its recorded SHA-256 is the final
path component, and the store copies it as a stream without parsing or loading
the object into memory.
