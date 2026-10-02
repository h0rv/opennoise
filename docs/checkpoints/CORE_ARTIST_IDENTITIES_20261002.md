# Independent MusicBrainz core identities

The verified 2026-09-30 core prefix contains the complete `mbdump/artist` table:
2,999,670 rows. A new streaming projection retains only exact MusicBrainz artist
UUIDs and native display names. It consumes no derived tag tables, no research
artist-tag output, and no historical genre-based selection. These identities
are CC0 core metadata, separate from the optional restricted tag research pack.

Reproduce from the preserved official prefix and captured license page:

```sh
.venv/bin/python scripts/build_musicbrainz_core_identities.py \
  --source .cache/musicbrainz-bulk-artist-tags-20260930-v1/source/mbdump-core-prefix-209715200.bz2 \
  --output-directory .cache/musicbrainz-core-artist-identities-new
```

The output directory must be new. The source prefix, complete table size,
table checksum, row count, schema sequence, and captured official license page
checksum are checked before a complete receipt is issued. Existing outputs are
never replaced. A failed run retains incomplete output without a complete receipt.
The source prefix and license page are preserved in the durable Library input
archive; they are not bundled into a clean Git checkout.

The actual verified run is retained at
`.cache/musicbrainz-core-artist-identities-20261002-v1`. Its
`artist-identities.jsonl.zst` is 95,458,405 bytes with SHA-256
`fd8d5d9cc36f1b90a200bf79c6316b5d2410045b31d2559a0d19c3f2ac2b8bbd`.
The checked artist member is 441,457,090 bytes with SHA-256
`6234d354577f0460b56e62c6696b8d47d3b4da8a25c62f8fe27d61b5b25e6d4d`.
This verifies the complete artist member, **not the complete 7.58 GB archive**.
The upstream whole-archive checksum remains published but unverified.

This expands the independent identity denominator. It supplies no genre
memberships, music similarity, musical judgments, or listening availability.
It does not replace the missing sealed public database or layout. Names can
support exact-ID lookup and future independent evidence acquisition; they
must not be counted as classified or playable artists.
