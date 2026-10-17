# Full-catalog direct co-tag evidence

The existing FMA catalog already exposes 109,727 tracks, 16,916 source artist
records and 164 genre definitions. Its six-link overlap previews expose 652
unique genre pairs. This increment adds lazy complete connection lists and exact
shared-recording pages for all 3,409 observed pairs across 161 genres, making
2,757 previously omitted pairs reachable. Existing six-link rankings are unchanged.

Complete lists are ordered by shared recording count, then native genre ID;
the interface states this ordering. Pair pages use the intersection of direct
tags on the same recording, sorted by native track ID, paginated at 200 rows.
Known-artist counts use distinct IDs present in the source artist table.
Unresolved-artist counts are recordings, not guessed artists. No parent tags,
artist-union relationships, cross-catalog identities or sonic similarities are
inferred. Of the observed pairs, 405 have only one supporting recording and 267
include recordings with unresolved artist identities.

## Inputs and rights

Only the retained October 13 official FMA capture is used. Metadata is CC BY 4.0;
dataset-author attribution, license link, source snapshot date and a derivation
notice remain in Sources. Recording licenses are separate and no audio is
included. Raw tables, biographies, contact fields and lyrics are not served.
New relationship files contain only IDs, counts and page metadata; existing
display allowlists supply names and titles. No new acquisition, model fitting,
credentials, paid service or public deployment is part of this increment.

Source receipt SHA256:
`cd46d53488e6892eed78b742814ef95e6531b18b6d69c8eb95688da075e6df99`.
Projected corpus receipt SHA256:
`088588f58ca80662f47e809d054de88eb320b402f110d6637d318f00edbff1ed`.
The original acquisition verified selected ZIP members and CRCs, not the full
archive hash. These are 2017 raw-source records, not a current catalog or the
106,574-track cleaned audio-feature cohort.

## Reproduction

After `poe sync`, run the existing builder into a fresh local directory:

```sh
.venv/bin/python scripts/build_fma_static_catalog.py \
  --source /workspace/opennoise-rebuild-20261013/metadata-source \
  --projected /workspace/opennoise-rebuild-20261013/metadata \
  --output /path/to/fresh/catalog
```

The builder replays every projected row against the retained native capture.
The observed build used explicit 120-second CPU/wall and 1 GiB address-space
limits: 14.51 seconds, 367,075,328 bytes peak RSS. Its final receipt accounts for
35,422,368 bytes and 6,970 manifest entries, within the existing 40 MB export
and 200 KB JSON-shard caps. No limits were increased.

New routes are `#connections=GENRE_ID` and `#pair=LOW_ID,HIGH_ID&page=0`.
Older exports keep their existing navigation and explicitly report that complete
connection evidence is unavailable. Audio remains an optional, independently
verified attachment; the measured export uses none.

This measures accessible source evidence, not musical relevance or independent
artist support. The retained catalog still has 974 tracks referencing 250 artist
IDs without source artist records, and 2,609 tracks without genre annotations.
Source identity repair and human assessment of musical usefulness remain separate
gaps; this change neither resolves nor relabels them.
