# Cross-source artist--genre corroboration audit

This is a bounded, local-only overlap and coverage audit of two retained
artifacts: MusicBrainz direct proper-genre portable custody and the Last.fm
ArtistTags2007 literal seed candidate. It does not create, change, read, or
compare a public/static artifact.

The only permitted join is byte-for-byte equality of the exact MusicBrainz
artist MBID and the canonical seed ID. Before joining, the audit requires the
Last.fm candidate's pinned seed-vocabulary byte SHA-256 to equal the
MusicBrainz custody receipt's reconciliation byte SHA-256. It rejects
noncanonical UUID spellings, an unmatched vocabulary, repeated Last.fm exact
pairs, oversized Last.fm candidate artifacts, and an overlap exceeding 250,000
pairs.

The report keeps the sources separate. It records MusicBrainz custody counts;
Last.fm candidate counts and full parse coverage, including abstentions; and
the exact-pair overlap count plus a hash of a canonically ordered pair stream.
It intentionally omits a precision/recall estimate and any factual
artist--genre membership output. Matching observations do not convert Last.fm
tags into facts, independent gold, construction input, model input, release
input, or public output.

Run it locally with the already pinned inputs:

```sh
.venv/bin/python scripts/audit_cross_source_artist_genre_corroboration.py \
  --musicbrainz-receipt config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json \
  --musicbrainz-object-store data/release/musicbrainz-direct-proper-genre-custody-v1/objects \
  --lastfm-candidate-artifact .cache/lastfm-artisttags2007/literal-seed-candidates-v1.json \
  --output .cache/cross-source-artist-genre-corroboration-audit-v1.json
```

The output is create-only. Keep it under `.cache`; it is not a public/static
artifact. This complements, rather than replaces, the source boundaries in
[the source signal inventory](SOURCE_SIGNAL_INVENTORY.md): MusicBrainz proper
genres remain custody-only and Last.fm ArtistTags2007 remains a literal
candidate source.

## Recorded local run

The pinned inputs above completed in 12.114 seconds on 2026-09-23. The
report's embedded logical output SHA-256 is
`9356dea99c887390832338fd7eae8fede0fc305436e30c6117f318fb0181ec18`; the
pretty-printed local file's byte SHA-256 is
`d7cf3feec76db005b0ef446ed47d981deebfafa4ccb09b742c593820dc7687e7`.

- MusicBrainz: 387,435 custody observations, 198,409 exact artist MBIDs, and
  697 canonical seed IDs.
- Last.fm: 192,614 literal candidate rows, 19,908 exact artist MBIDs, 1,317
  canonical seed IDs, and 952,810 physical rows. Of those physical rows,
  760,093 had no exact seed-name match and 103 duplicate artist/tag rows were
  excluded; 711,819 abstention rows are summarized rather than retained.
- Exact overlap: 20,498 artist-MBID/canonical-seed-ID pairs. The canonical
  ordered pair stream has SHA-256
  `106df5e3980a8284cd9ec97cc7b9629152c14186e29523b1c690dfb54be447a4`.

These are source-coverage and candidate-overlap counts only. They imply no
quality result, factual membership, independent gold, or promotion decision.
