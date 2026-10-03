# FMA native metadata corpus

The FMA adapter captures three original CSV members from the official metadata
ZIP: `raw_genres.csv`, `raw_artists.csv`, and `raw_tracks.csv`. Its native IDs form
an independent namespace. Track genre declarations remain track metadata; they
do not establish artist memberships or MusicBrainz identities.

The official FMA README declares metadata CC BY 4.0. The captured README is
preserved in `data/examples/fma-source/README.md`, pinned by SHA256
`54148723ff06c19374c368499f1e97afb3d10f58646d20a221e4d9c7ab63fac9`.
Attribute Michaël Defferrard, Kirell Benzi, Pierre Vandergheynst, and Xavier Bresson,
*FMA: A Dataset For Music Analysis*, ISMIR 2017, <https://github.com/mdeff/fma>.
Audio has separate artist-selected licenses, including noncommercial licenses;
the metadata license grants no rights to those recordings. Audio URLs and media
are excluded. EchoNest tables, pickle files, and feature tables are excluded
from this adapter.

## Capture and offline replay

Use the existing Python 3.13 environment; no additional dependencies are needed.
Both destinations must be new. The explicit capture flag makes eight native HTTP
requests, with a total transfer limit of 15 MB. Without that flag the command
only replays local compressed captures.

```sh
PYTHONPATH=src .venv/bin/python scripts/acquire_fma_native_metadata.py \
  --capture --source .cache/fma-source-new --output .cache/fma-corpus-new

PYTHONPATH=src .venv/bin/python scripts/acquire_fma_native_metadata.py \
  --source .cache/fma-source-new --output .cache/fma-replay-new
```

The source directory preserves the official README, ZIP directory tail, exact
local headers, compressed member ranges, and a source receipt. Capture requires
206 responses with exact Content-Range, Content-Length, and a pinned archive ETag;
it rejects redirects, encoded responses, silent full downloads, truncation, and
oversized bodies. Local ZIP facts must agree with the central directory. Replay
checks observed SHA256 bindings, native compressed and uncompressed byte counts,
and every native ZIP CRC. It streams CSV decoding into `JSONL.zst`; the 122 MB raw
track table never becomes a disk file. A full archive SHA1 is explicitly unverified.

The projected tables preserve source track, artist, album, and genre IDs; titles;
source track-artist associations; track genre lists; native taxonomy parent IDs;
and source-declared audio license metadata. Absent or malformed fields become
null with typed `missing_fields`. Tracks whose artist IDs are absent from the
artist table remain present with `source_unresolved`. Duplicate entity IDs fail
the projection. Names never merge identities. Exported metadata URLs are source
declarations; current playback availability is unverified.

## Observed raw snapshot

The 2026-10-02 capture transferred 11,598,241 bytes. The final projected tables
occupy 3,876,689 bytes:

| Native table | Rows | Missingness |
| --- | ---: | --- |
| Artists | 16,916 | No missing native ID or name |
| Genres | 164 | 15 absent parent IDs; no invented parent |
| Tracks | 109,727 | 974 unresolved artist IDs; 2,609 absent genre lists; 1,041 absent album IDs |

These are raw API snapshot denominators. They differ from the README's cleaned
106,574-track audio dataset and its artist/genre counts. A feature/audio join must
account for missing raw tracks explicitly rather than substitute cleaned counts.
The [source receipt](evidence/fma-native-source-20261002.json) and
[final corpus receipt](evidence/fma-native-corpus-20261002.json) are preserved. Large
compressed captures and projected tables remain external workspace artifacts;
the receipts are custody evidence and do not make those missing files available
in a fresh checkout.
