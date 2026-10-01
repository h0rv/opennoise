# Bounded MusicBrainz aggregate artist-tag source, 2026-09-30

This experiment establishes a current exact-ID MusicBrainz aggregate-tag source
for the 198,409 artists in the primary Every Noise feature selection. It avoids
the proposed 1,400 additional Web Service requests. The projection is local
research evidence only; it is not a proper-genre dictionary, a direct genre
claim, a membership decision, or independent validation of a microgenre.

The official snapshot is `20260930-002222`:

| File | Official size | Official SHA-256 | Local verification |
|---|---:|---|---|
| [`mbdump-derived.tar.bz2`](https://data.metabrainz.org/pub/musicbrainz/data/fullexport/20260930-002222/mbdump-derived.tar.bz2) | 520,485,348 bytes (496.37 MiB) | `e1fb2f376e5d45c5d5a0be8cbe9f978218c4be14c0304fb0ffc10316f8c641ab` | Full byte length and SHA-256 verified before parsing |
| [`mbdump.tar.bz2`](https://data.metabrainz.org/pub/musicbrainz/data/fullexport/20260930-002222/mbdump.tar.bz2) | 7,577,615,628 bytes | `4342c77212a8807e351e619b49162bc796e19419628bad3c9e791dbdd8e5f587` | Published hash recorded, whole archive not downloaded or verified |

The core archive was accessed as a 209,715,200-byte HTTP range prefix with SHA-256
`bcbc97886d8226c12d7a6f2f28246498fdd961840be516b85f14dc6a6a0cc7a0`. That
prefix contains the complete `mbdump/artist` tar member before the next member
boundary. Its declared uncompressed size is 441,457,090 bytes; the extracted
member SHA-256 is
`6234d354577f0460b56e62c6696b8d47d3b4da8a25c62f8fe27d61b5b25e6d4d`, with
2,999,670 newline-terminated PostgreSQL COPY rows and 19 columns. Column 0 is
the numeric artist ID, column 1 is the canonical artist UUID, and column 2 is
the source name. The prefix's exact size and hash, plus the member's exact size,
hash, and row count, are checked by the producer. The receipt explicitly keeps
`core_archive_sha256_verified: false`; its published whole-archive SHA is not
misrepresented as locally checked.

The join is only `artist.gid` UUID to the numeric `artist.id`; no artist-name
matching, aliases, or identity merging occurs. The derived archive parser reads
`mbdump/artist_tag` and `mbdump/tag`, joins tag IDs to their native tag names,
and never reads user-specific `mbdump/artist_tag_raw`. The official snapshot
`SHA256SUMS`, snapshot listing, and license page are retained and hash-bound in
the v2 receipt. Source artifacts and the earlier immutable raw projection are
under `.cache/musicbrainz-bulk-artist-tags-20260930-v1/source/`; the complete
model-facing projection is
`.cache/musicbrainz-bulk-artist-tags-20260930-v2/artist-tags.jsonl`.

The verified v2 projection contains all 198,409 selected UUIDs: 198,381 are in
the current artist table and 28 are explicitly marked
`absent_from_current_artist_dump`. Of the matched UUIDs, 198,362 have at least
one aggregate tag row, 19 have none, and the 28 absent UUIDs carry empty tags.
The JSONL is 208,210,053 bytes with SHA-256
`98fd42b141d021a6fc0eba69451e3aaaeca787ec4c93997d3a317ebdfc6d8305`; the
receipt's `output_sha256` is
`a3cf2e7c43afff18a5942b79c507e83a171e6662242d1271a0c6d371d25a989e`. The
selection input SHA-256 is
`cca2fb2595b7e38f0c19f14c44acbcf51767f7134c998a540d0efff2d0a7d526`, and the
canonical sorted UUID selection hash is
`627145ab6f44f161c4e68e6b561cf9fb679a0933b981d65407ca3accc23b1eab`.

For selected artists, the raw projection preserves 616,440 positive-count,
21,477 zero-count, and 3,873 negative-count aggregate rows. Only positive counts
are model-facing observations; zero and negative values remain available as
raw source evidence and must be excluded by feature normalizers. The JSONL sets
`genres: []` for every row and assigns the explicit role
`bulk_musicbrainz_aggregate_artist_tag`, so aggregate tags cannot be promoted
to native genre IDs. All rows retain exact source table/row references or an
explicit absent status. The final iterator validates these boundaries, the
complete UUID partition, receipt digest, source bindings, and archive/prefix
hashes before a consumer uses the data.

MusicBrainz's retained license page states CC0 for core metadata and
Attribution-NonCommercial-ShareAlike 3.0 for tag associations. Local
noncommercial research model input is authorized with attribution and
share-alike obligations; public export is not authorized. The artifacts must
remain local and noncommercial. There is no deployment or audio use in this
experiment.

To replay from the retained sources without downloading the derived archive
again, choose a new output directory:

```sh
.venv/bin/python scripts/build_musicbrainz_bulk_artist_tag_evidence.py \
  --source-directory .cache/musicbrainz-bulk-artist-tags-20260930-v1/source \
  --selection .cache/microgenre-features-primary-v1/artist-features.jsonl \
  --output-directory .cache/musicbrainz-bulk-artist-tags-20260930-replay
```

The builder checks both source snapshots, re-verifies the complete derived
archive against its published size and SHA-256, extracts and checks the full
artist member from the bounded core prefix, builds the exact UUID join, writes
the complete JSONL, and independently replays the raw tables to verify both
output and receipt. A consumer can validate the sealed v2 output without
repeating the expensive table replay:

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
from opennoise.ingest.musicbrainz.bulk_artist_tag_evidence import (
    verify_bulk_artist_tag_artifact_receipt,
)

receipt = verify_bulk_artist_tag_artifact_receipt(
    directory=Path(".cache/musicbrainz-bulk-artist-tags-20260930-v2")
)
print(receipt["output_sha256"])
PY
```

The raw v1 projection is retained as provenance and is not the complete
model-facing artifact. The v2 reader and raw-source replay were verified; an
independent audit confirmed the complete UUID coverage and source semantics.
