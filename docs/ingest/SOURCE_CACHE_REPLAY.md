# Raw source cache replay

The release bundle is derived-cache only. This workflow reconstructs a
selected bounded raw-input set on a fresh checkout without reading `.cache`.
It does not yet reconstruct the exact complete Phase 3 source vault or derived
database.

It uses the pinned declarations in `config/data_sources.toml`. Source bytes
are metadata only, checked against the declared byte count and SHA256, then
stored by SHA256. A timestamp-free receipt binds the exact manifest bytes and
the complete selected declaration set. Restoring the receipt makes
`raw/sha256/<digest>` files that the existing ingest pipeline can reuse with
no network request.

Check the policy state before acquiring anything:

```sh
uv run opennoise source-cache-status \
  enao_quint_legacy_map_2025 \
  musicbrainz_postgres_core_20260829 \
  enao_official_public_mirror
```

`network_acquirable` and `portable_object_store_eligible` are separate.
Pinned Every Noise mirrors are network-acquirable only into a local vault.
They have `portable_object_store_eligible: false`, so their raw bytes and
receipt cannot be published to R2, S3, or another shareable store. The
official mirror has no pinned size or SHA256 and is always operator-supplied.

For an exportable source, acquire a bounded local cache. The default is 128
MiB, so large dumps require an intentional limit increase. The following 8 GB
example is illustrative only and was not run as part of this change.

```sh
uv run opennoise acquire-source-cache musicbrainz_postgres_core_20260829 \
  --storage-scope portable_object_store \
  --max-total-bytes 8000000000 \
  --object-store data/source-object-store \
  --work-directory data/source-work \
  --receipt data/source-cache-receipt.json
```

For a local-only source, use `--storage-scope local_vault`. Its receipt stays
local and its ObjectStore must be the local implementation:

```sh
uv run opennoise acquire-source-cache enao_quint_legacy_map_2025 \
  --storage-scope local_vault \
  --object-store data/local-source-vault \
  --work-directory data/source-work \
  --receipt data/local-source-receipt.json
```

Restore from a supplied receipt after cloning. This verifies the current
manifest hash and every selected declaration before copying any bytes:

```sh
uv run opennoise restore-source-cache musicbrainz_postgres_core_20260829 \
  --object-store data/source-object-store \
  --receipt data/source-cache-receipt.json \
  --destination data/source-cache
```

No command downloads, stores, serves, or processes audio, previews, or music
files. The workflow only creates a selected raw cache. Adapting and publishing
derived catalog data remain separate steps and keep their existing source
policies.

## Bounded live verification

On 2026-09-04, the pinned `enao_scottsdale_names_2026` metadata artifact was
reachable from its declared GitHub URL and acquired into a local vault. It was
120,730 bytes with SHA256
`9e9834811bdadfa90f19653a4ad522a4e8b5ac1a3321c1d1ac6b7e2738a73712`.
The local receipt SHA256 was
`0da3929119b3556ebf1facccdc14df42ada66ebfe62213b6589e7ce368bfa064`.
An offline restore and a second acquisition produced the same receipt and
restored artifact checksum. The raw bytes were not published or committed.

## Incremental acquisition with a fresh work directory

`acquire-source-cache` now checks the durable object store before attempting a
source download. For each current declared hash already present, it restores the
object into the work directory and checks its size, SHA256 and metadata-only
content policy. Only absent hashes reach the downloader. This makes a fresh work
directory reusable with an existing store, without a separate restore command.

A changed SHA256 selects a new immutable object; the old object and old receipts
remain available for exact replay. An unchanged hash can be reused across a new
manifest, but the new receipt still binds the current manifest and all current
source declarations. Source limits and local/portable rights checks apply before
any reuse. Corrupt stored bytes fail acquisition with no HTTP fallback or automatic
replacement. Existing downloader resume behavior still applies to absent objects.
Receipt schema, source selection and downstream evaluation gates are unchanged.

For the same pinned manifest and store, run the acquisition command above again
with a different `--work-directory` and `--receipt` path. When every selected hash
is present, it restores the bytes without source HTTP requests and produces the
same deterministic receipt. No new CLI options or task-runner aliases are needed.

Reproduce the bounded regression and end-to-end checks after `poe sync`:

```sh
.venv/bin/python -m unittest tests.test_source_cache -v
```

The mixed-manifest test starts with two objects, then changes one and adds one:
only the changed and added source are fetched. A third fresh work directory makes
zero requests, and the old receipt still restores the old source versions. A
separate checked-in native MusicBrainz core test restores two real metadata
responses with HTTP forbidden. Cached corruption is rejected without contacting
the source. Concurrent source downloads need not start in source-ID order;
receipts and restores remain deterministically sorted.

A local CLI demonstration on 2026-10-18 seeded the object store with two checked-in
native core responses (817 bytes total), then acquired into two distinct empty
work directories with HTTP(S) configured to an unreachable local proxy. Both runs
succeeded with identical receipt SHA256
`3169bfa15c44bda6f33f87a912bbf64bc757cd2f3ef4fbb3dc697b2b88cc7c10`.
The demonstration used a local fixture manifest and made no external requests.
No raw source bytes or local demo artifacts were added to the repository.
