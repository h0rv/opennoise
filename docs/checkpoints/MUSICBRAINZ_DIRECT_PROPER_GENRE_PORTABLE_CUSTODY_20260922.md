# MusicBrainz direct proper-genre portable custody

The checked-in `musicbrainz-direct-proper-genre-custody-v1` object is a
compact, immutable *filtered projection* of the local MusicBrainz
seed-target archive. It is custody-only evidence for review. It does not
authorize memberships, static export, discovery changes, deployment, or any
public claim.

The source is 387,435 reconciliation-safe literal proper-genre observations:
697 retained seed IDs, 198,409 exact artist MBIDs, and 198,409 distinct
source-record SHA-256 values. Each canonical JSONL row includes the seed ID,
exact MBID, MusicBrainz genre ID, exact `musicbrainz:artist:<MBID>` source
record ID, source-record SHA-256, and source evidence reference. Tags,
release evidence, peer evidence, inferred rows, and historical assignments
are excluded by construction.

The compressed object is bounded to 50 MiB and uses the locked Python
`zstandard` package at deterministic single-threaded level 6. Its receipt
also bounds claims to one million, line length to 4 KiB, and decompressed
bytes to 256 MiB before typed-stream verification. The actual object is
26,951,221 bytes at its tracked final path, with compressed SHA-256
`b1fc1ac9428832cb4543710b716e2d47eb8cc62dc052ed4d768ffb27dd1dcc3e` and
uncompressed canonical-stream SHA-256
`a21efee82b3ff436c51208ae2519d1cae67b9d14d3b07b8dc977c74da6ec50f6`.

The receipt pins the original 682 MiB archive byte SHA-256 and its artifact
output SHA-256, plus the reconciliation hashes. A fresh checkout can replay
and verify the compact projection itself without that ignored archive. It
cannot independently prove that the original 682 MiB archive was replayed:
that stronger check remains available only on a machine retaining the pinned
archive.

Verify the tracked compact object only:

```sh
uv run python scripts/verify_musicbrainz_direct_proper_genre_custody.py \
  --receipt config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json \
  --object-store data/release/musicbrainz-direct-proper-genre-custody-v1/objects
```

Add `--seed-target` and `--reconciliation` with the retained local paths to
perform the stronger path-based source replay. Both modes leave serving and
deployment unchanged.

Rebuilding requires the pinned source artifact's declared output SHA-256 as
`--seed-target-output-sha256`; the builder records it alongside the full
archive byte hash, while the path-based verifier checks it against the source.
