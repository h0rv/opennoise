# Historical compatibility

`historical-compatibility-v1` is a local-only, dated lens over one verified Every Noise map
artifact. It is not a new embedding, a current Spotify catalog, or a claim to recover private
Every Noise weights.

```sh
poe build-historical-compatibility --source data/raw/sha256/1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180
poe evaluate-historical-compatibility data/historical/historical-compatibility-v1.json data/model/production-map-v1.json --report data/historical/comparison-report-v1.json
```

An H3 projection is opt-in, local-only, and needs both the exact pinned JSON and an explicit
display switch. It writes the 306,136 source-scoped memberships to SQLite, then records only
their sealed hashes and measured aggregate coverage in the compatibility artifact.

```sh
poe build-historical-compatibility --source data/raw/sha256/1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180 --h3-source /local/spotify_genres_artists_map.json --enable-local-display
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
| H3 genre pages | partial by measurement when enabled | 306,136 exact local-display genre-to-artist memberships across 6,289 H2 names; 5,445 source rows quarantined | complete H2 name coverage, page positions, related blocks, capture dates |
| H4 artist pages | derived_partial when H3 is enabled | reverse index of the retained H3 memberships | artist-page capture, page ordering, recordings, related links |
| H5 lists/playlists | missing | none | historical ranks, playlist IDs, track order |
| H6 compatibility view | partial | retained map geometry, labels, dated representatives | paths requiring H3-H5 pages |

H3-H6 each have an explicit disabled resumable adapter contract. Enabling one needs a separately
verified local/archive source manifest with capture information, hash, and rights decision. The
contracts do not fetch, scrape, or infer data.

The H3 source never enters the object store or public model. The SQLite policy allows local display
only when explicitly enabled and denies export. The publication receipt links the compatibility
artifact, object key, SQLite run, and the sealed H3 projection. See [the H4/H5 source audit](H4_H5_SOURCE_AUDIT.md).

When H3 is enabled, that receipt also carries a `historical-full-map-production-input-v1` handoff:
6,291 stable H2 genre IDs, representatives, provenance hashes, and LOD-first viewport-tile
delivery. H2 coordinates, color, and font remain an evaluation oracle and optional legacy-reference
view only. An independent model produces its own landscape coordinates from safe graph inputs.
Its 306,136 membership edges remain behind the export-denied SQLite display view; a browser payload
must build tiles from that contract rather than receive raw rows.

## Historical full-map switch: integration gates

The historical option is not currently eligible for the product switcher. It
may be integrated only when every gate below passes and its result is recorded
in a release receipt.

| Gate | Required evidence | Current status |
| --- | --- | --- |
| Rights and scope | A sealed policy explicitly permits the requested local display; export remains denied unless separately authorized. | Blocked: the current H3 source-data licence is unspecified; default mode is discovery-only. |
| Exact input | 6,291 unique H2 IDs, source hash `1ac0…fe180`, source date/status, and an explicit H3 coverage receipt. | Partial: H2 passes; H3 has 306,136 observations over 6,289 matching H2 names, with 145 unmatched source genres. |
| Data boundary | H3 rows and historical coordinates have no derivation edge into `public-graph`; the browser payload contains only local-display, tiled data. | Designed and tested in isolation; not integrated into the public serving release. |
| Independent visualization | A versioned full-map artifact declares its own coordinates, LOD/tile membership, labels, and input hashes. It must not call archived coordinates a public embedding. | Partial handoff contract only; no certified switch artifact. |
| Usable switching | A visible, keyboard-accessible switch names `Public semantic map` and `Historical compatibility`; it preserves normal links and makes local-only status clear. | Missing. |
| Browser and content QA | Desktop/mobile light/dark/system screenshots plus selection, back, zoom, focus, switch-state, and no-script checks pass. No media URL or audio byte may be fetched, embedded, or exposed. | Missing. |
| Rebuildability | The exact local source/cache and every derived artifact are retained or separately delivered with hashes; a fresh authorized environment can rerun certification offline. | Missing: the source is not distributable through this checkout and must be operator-supplied. |

### Browser and performance acceptance contract

After the eligibility gates pass, certification of the 6,291-node switch must
measure the following contract in the raw-CDP browser harness. These are
release gates, not aspirational design notes.

| Area | Required acceptance |
| --- | --- |
| Addressable switch | `?view=public` and `?view=historical` are normal, shareable URLs. A switch never silently substitutes one view for the other. It preserves the query and, where the selected stable ID exists in both views, the selection; otherwise it announces that the selected item is unavailable in the new view. |
| Initial payload | The historical initial response contains at most 24 overview-community records and is at most 256 KiB of uncompressed JSON. It contains no raw H3 membership rows, preview URLs, track identifiers, or audio/media URLs. The 6,291 nodes are requested only through the declared LOD/tile contract. |
| LOD and tiles | LOD 0 renders at most 24 overview communities. LOD 1 may expose at most 240 genre nodes, LOD 2 at most 1,200, and LOD 3 all 6,291. LOD 3 obtains visible nodes in declared 16-by-16 viewport tiles, with no response exceeding 512 node records. Earlier selected context remains visible while zooming. |
| Labels | The historical renderer uses the same maximum shown-label budgets as the public map: desktop `48/80/128/180`, mobile `24/40/64/80`, with no label below 12 px and overlap no greater than 2% desktop or 3% mobile at every LOD. At LOD 0, at least 18 desktop and 6 mobile overview labels are visible or revealed on keyboard focus. |
| Local performance | On the certification host, five cold-cache runs must record p95 overview-ready time of at most 2.5 s at 1366 by 768 and 3.5 s at 390 by 844. Five warm-cache tile requests must have p95 response-to-render time of at most 300 ms, and five genre-detail clicks at most 250 ms. Each measurement records host, browser revision, viewport, cache state, and all samples. |
| Interaction and mobile | In both views, browser QA passes switch click and keyboard activation, drag/touch pan, wheel/pinch zoom, LOD transition, tile loading, genre-detail click, search, browser back, retained theme, and visible focus. The historical view must be checked in system, light, and dark modes at 1366 by 768 and 390 by 844. |
| No-script fallback | With JavaScript disabled, the URL renders a labelled historical compatibility notice, source/provenance link, search or paginated genre navigation, and ordinary detail links. It must not emit a 6,291-label SVG, request tiles, or reveal local-only data when the local-display policy is not enabled. |
| Evidence bundle | The final receipt includes the public and historical artifact hashes, source/policy hashes, 12 screenshot hashes (two views by desktop/mobile and system/light/dark), raw-CDP interaction results, payload sizes, timing samples, and a negative network/content check showing no audio or media request. |

## Independent comparison

The evaluator accepts a typed `public-graph-v2` or `production-map-v1` artifact. It joins only
unique Unicode-normalized exact names, aligns the resulting coordinate pairs for a diagnostic RMS,
and never calls that a recovery of historical geometry. It compares relationships only when the
historical source actually retained them. With the current map-only artifact, relationship status is
`unavailable`, not zero similarity.
