# Last.fm 1K streaming feasibility adapter

## Status

The repository has a local parser and receipt writer for a possible future
Last.fm 1K archive audit. No Last.fm 1K archive was acquired, opened, or added
to this repository while creating this adapter.

The adapter is not an ingestion path. It is not allowed to provide graph,
model, evaluation, serving, or public data. It does not create an aggregate
and it does not establish a track to recording bridge.

## Input and checks

The command accepts only an explicitly supplied local archive path. It does not
download a file. Before reading the archive member, it verifies the fixed
published Zenodo MD5 `a79a6808f54f73354789a9fb02cb1e41` and compares the
calculated SHA-256 with a required, independently recorded `--archive-sha256`
value. The command rejects a missing, malformed, or mismatched pin.

The archive member path has not been verified because this repository has not
acquired the archive. The parser therefore accepts exactly one regular member
whose basename is `userid-timestamp-artid-artname-traid-traname.tsv`. It rejects
no match and more than one match. It reads that member once without extraction
and parses no other member.

## Command

Run this only after terms review and only with a separately recorded SHA-256.

```sh
.venv/bin/python scripts/run_lastfm_1k_feasibility_scan.py \
  --archive /path/to/lastfm-dataset-1K.tar.gz \
  --archive-sha256 <independently-recorded-lowercase-sha256> \
  --catalog .cache/musicbrainz-20-catalog/public.sqlite \
  --output .cache/lastfm-1k-feasibility/receipt.json
```

`--catalog` is optional. If supplied, it is opened read-only and used only for
an exact MusicBrainz artist-ID overlap count. The command records the catalog
SHA-256 and never writes to the catalog.

The output must be below this repository's `.cache` directory. The command
refuses an existing or symbolic-link output path and creates the receipt with
exclusive file creation, so it cannot replace an existing receipt.

## Receipt contents

The receipt includes source and catalog hashes, input sizes, fixed settings,
the selected member path, and counts for raw rows, well-formed TSV rows,
malformed rows, abstentions, canonical artist and track MBID coverage,
timestamp coverage, complete exact artist, track, and timestamp rows, unique
artist MBID count, and optional exact catalog overlap.

The receipt also includes `output_sha256`, a logical SHA-256 over every other
receipt field in canonical JSON order. A later reviewer can recompute this
field from the local receipt without reading the archive.

It does not include user IDs, artist names, track titles, individual listens,
per-user histories, source row order, raw lines, artist IDs, or track IDs.
Artist IDs exist only in memory while the scan forms the two aggregate unique
counts. The archive and receipt remain local custody material.

## Source role

Last.fm 1K is timestamped listening evidence with an exact artist-ID bridge.
Its track field is a MusicBrainz track ID, not a recording ID. A separately
pinned exact track to recording bridge is required before any recording work.
Neither this adapter nor a future receipt can make the source genre truth,
artist membership, evaluation gold, or public data.

Last.fm 1K and Last.fm 360K both come from Last.fm. Their populations may
overlap, so agreement between their results is not independent corroboration.
Do not combine their counts or compare them as population evidence without a
separate study that defines overlap, time, and user handling.
