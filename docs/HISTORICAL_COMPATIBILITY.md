# Historical compatibility

`historical-compatibility-v1` is a local-only, dated lens over one verified Every Noise map
artifact. It is not a new embedding, a current Spotify catalog, or a claim to recover private
Every Noise weights.

```sh
poe build-historical-compatibility --source data/raw/sha256/1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180
poe evaluate-historical-compatibility data/historical/historical-compatibility-v1.json data/model/production-map-v1.json --report data/historical/comparison-report-v1.json
```

The publisher verifies the pinned source before parsing, writes one immutable JSON artifact to the
configured object store, and writes an append-only coverage record to SQLite. It retains no audio
or preview URL. A legacy preview is represented only by `absent` or `disabled_legacy` and, when
present in source markup, a SHA-256 hash of the URL.

## Current bounded coverage

| Stage | State | Retained | Explicit gap |
| --- | --- | --- | --- |
| H1 source manifest | complete | pinned URL, snapshot, SHA-256, byte size | none for this artifact |
| H2 map | complete | 6,291 names, item IDs, source order, coordinates, colors, font sizes | none for retained map rows |
| H3 genre pages | partial | 6,226 parsable map-row artist/track representatives; 65 quarantined representative rows | genre-page memberships, page positions, related blocks, capture dates |
| H4 artist pages | missing | none | artist genre and recording pages |
| H5 lists/playlists | missing | none | historical ranks, playlist IDs, track order |
| H6 compatibility view | partial | retained map geometry, labels, dated representatives | paths requiring H3-H5 pages |

H3-H6 each have an explicit disabled resumable adapter contract. Enabling one needs a separately
verified local/archive source manifest with capture information, hash, and rights decision. The
contracts do not fetch, scrape, or infer data.

## Independent comparison

The evaluator accepts a typed `public-graph-v2` or `production-map-v1` artifact. It joins only
unique Unicode-normalized exact names, aligns the resulting coordinate pairs for a diagnostic RMS,
and never calls that a recovery of historical geometry. It compares relationships only when the
historical source actually retained them. With the current map-only artifact, relationship status is
`unavailable`, not zero similarity.
