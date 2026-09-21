# Public release custody

This is archived custody guidance; `public-release-custody` is not a current Poe task. It verifies and seals the qualified Phase 3 public
release without downloading or rebuilding any source. The command is
cache-only: it opens the SQLite cache read-only, checks its declared SHA-256,
size, schema, SQLite integrity, manifest boundary, and expected source-table
counts, then streams the cache into a content-addressed `LocalObjectStore`.

When the recorded raw source vault is present, the command also handles the 62
manifest-bound source objects under `raw/sha256/<artifact-sha256>`. Copy mode
streams each object into the custody store and checks its recorded `vault_key`,
size, and digest. Reference mode performs the same bounded hash and size
verification but records the already content-addressed vault path instead of
copying the bytes. Reference mode is safe only for the trusted local vault
layout and is explicit in both the command and receipt. Missing raw inputs do
not make the qualified cache unusable: the receipt records their exact paths
and marks the run `source_completeness: "cache_only"` instead of claiming
source-complete custody.

The release model, production map, acceptance, seed, browser, and report JSON
files are likewise streamed and bound by content hash. If
`.cache/objective-gates/public-model-gate-v1.json` and
`metadata-representatives-v1.json` are present, both are required, parsed, and
bound to the same model hashes. A partial pair fails closed. A single Pydantic
`public-release-custody-receipt.json` is written atomically after all checks and
contains the exact command, Python version, code revision, cache identity,
source custody state, evidence identities, and checked counts. Large inputs are
copied in bounded chunks and are never loaded into memory as byte strings.

The CLI and Poe task resolve defaults from the repository root, so running from
the project root uses `.worktrees/phase3-public-evidence` and
`.worktrees/final-integration` correctly. Set `OPENNOISE_PUBLIC_RELEASE_ROOT` or
the per-path `OPENNOISE_PUBLIC_RELEASE_*` variables to use another layout. For
another checkout, pass `--cache-database`, `--source-vault`,
`--evidence-directory`, and `--output-directory` explicitly.
The default run writes objects and the receipt below the ignored project cache:

```
.cache/public-release-custody/
├── objects/cache/sha256/<cache-sha256>.sqlite
├── objects/raw/sha256/<source-sha256>  # copy mode only
├── objects/evidence/<name>/<evidence-sha256>.json
└── public-release-custody-receipt.json
```

The source-object key scheme also cleanly references any retained
content-addressed MusicBrainz artist object: its recorded SHA-256 is the final
path component. Copy mode streams it without parsing or loading it into memory;
reference mode verifies the existing content-addressed path without duplicating
the object.

## Portable cache-only bundle

The retired bundle workflow moves the **sealed derived cache**, release
configuration, original custody receipt, public model, map, acceptance and
browser evidence, final report, and the paired objective-gate reports between
object stores. It is deliberately not a raw-source archive: the bundle receipt
states `raw_source_reingestion: "not-included"`, and it never copies `raw/` or
any local research/history material.

All paths below are explicit. The current known-good source is the retained
`public-release-custody-hardening` store; the similarly named `integrated`
store must not be used because its cache bytes no longer match its receipt.

```sh
python scripts/public_release_bundle.py export \
  --custody-receipt .cache/public-release-custody-hardening/public-release-custody-receipt.json \
  --release-directory config/releases/phase3-public-20260831 \
  --custody-store .cache/public-release-custody-hardening/objects \
  --bundle-store /portable/public-release-objects

python scripts/public_release_bundle.py verify \
  --bundle-store /portable/public-release-objects \
  --receipt-key bundles/public-release/v1/<custody-receipt-sha256>/receipt.json

python scripts/public_release_bundle.py restore \
  --bundle-store /portable/public-release-objects \
  --receipt-key bundles/public-release/v1/<custody-receipt-sha256>/receipt.json \
  --cache-database data/phase3-public-qualified.sqlite \
  --release-directory config/releases/phase3-public-20260831 \
  --evidence-directory data/release-evidence \
  --objective-gates-directory data/objective-gates \
  --custody-receipt data/release/public-release-custody-receipt.json
```

The receipt key is printed by `export`. `verify` parses the Pydantic receipt at
the boundary, rejects traversal and omitted required members, checks every
object digest and size, validates the nested custody receipt bindings, and
loads the restored release configuration. `restore` verifies before pulling and
uses the atomic object-store pull for every named destination. Running it again
is a byte-for-byte idempotent replacement. After restore, the cache-only model
and map builder can verify the exact local release boundary without starting a
runtime service. The public web release is certified separately with
`poe build`, which verifies the sealed semantic layout,
exports Pages assets, and runs the loopback browser gate. Neither command
re-ingests the original sources.
