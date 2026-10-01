# Source model, enrichment, and UI checkpoint

The 2026-09-30 batch runs on real retained inputs and produces two distinct local
browser surfaces: the revised UI over hash-verified public presentation data,
and a source-only model explorer over portable MusicBrainz observations. Neither
is a production release or a certified reconstruction of the sealed database.

## Modeling

The portable source contains 387,435 unique proper-genre observations across
198,409 artist MBIDs and 697 seeds. A nested deterministic split selects the
specificity-transfer model on validation before evaluating the untouched test.
Test Recall@10 rises from 42.2441% to 42.6586%, recovering 320 additional positives
among 77,206 held-out observations. Macro seed recall rises from 31.0880% to
33.2107%. These are descriptive source-reconstruction results, not significance,
precision, independent gold, or ranked artist relevance claims.

The final fit has 10,868 directed genre edges, 683 supported genres, and 14
overlap abstentions. Its separate artist-neighbor query abstains for 115,838
artists, including 115,512 singletons. Small genres and cold artists remain the
main coverage weakness. Artist-to-artist rankings, genre-to-artist proposals,
and map geometry have not been validated by artist-to-genre recovery.

See [the modeling checkpoint](DIRECT_CUSTODY_SPARSE_NEIGHBORHOODS_20260930.md)
for formulas, split isolation, support strata, all compared arms, and hashes.

## Data quality and native label enrichment

The exact-ID catalog preserves every source observation and joins canonical
names for 164,404 artists (82.86%). It retains 34,005 unresolved artist names;
338,327 direct pairs have names (87.33%). The 4,845 colliding display labels
remain distinct MusicBrainz identities. Two display labels require normalization;
their canonical source strings are retained unchanged.

The rate-limited official MusicBrainz genre dictionary acquisition retained
23 JSON metadata pages and 2,209 unique genre UUIDs. Offline replay checks every
page's bytes, source URL, pagination, identities, and name projection. Exact
UUID joins resolve all 697 source genre labels with no ambiguity or missing
labels. This adds display metadata, not memberships, taxonomy, or placements.
The dictionary logical hash is
`0828cd074c756d2ce4291c6a1d4cf58fdcc28353ba1084481a44c43922bc947a`.

The final catalog is `.cache/musicbrainz-candidate-catalog-final/`; its receipt
hash is `43593ab9702da7cc3b2c6837e96cd337cfa924556d1f931a7a383a3a00eed0b0`.
Its logical database hash is
`6f5c1117be40ba95a8a0c389504b7d837b4172dc87c7eb093a0cfd9b436bc4e6`.
The source genre dictionary and separate seed-label join are retained under
`.cache/musicbrainz-native-genre-labels/`.

## Local source explorer

The explorer verifies the model, catalog, and native label receipts, then checks
all 387,435 model matrix pairs against the catalog. Only model peer edges enter
the spectral layout; native labels and artist names join after coordinates are
computed. All 14 zero-peer genres remain searchable without fictitious positions.

The static UI supports genre search, pan and zoom, source artist selection,
direct genre links, and explicitly inferred neighbors and proposals. Bounded
artist examples are exact-MBID ordered, not curated representatives. The browser
receives precomputed coordinates and metadata only.

See [the explorer checkpoint](DIRECT_CUSTODY_LOCAL_EXPLORER_20260930.md) for the
final receipt, source bindings, artifact counts, and Chromium evidence.

Reproduce from a synchronized checkout using new destinations:

```sh
poe sync
.venv/bin/python scripts/build_local_musicbrainz_candidate_catalog.py \
  --output-directory .cache/research-catalog
.venv/bin/python scripts/enrich_local_musicbrainz_genre_labels.py \
  --output-directory .cache/research-labels --catalog-directory .cache/research-catalog
.venv/bin/python scripts/build_direct_custody_neighborhoods.py \
  --output .cache/research-model
.venv/bin/python scripts/build_local_direct_custody_preview.py \
  --model-directory .cache/research-model --catalog-directory .cache/research-catalog \
  --label-directory .cache/research-labels --output .cache/research-explorer
.venv/bin/python -m http.server 8876 --bind 127.0.0.1 --directory .cache/research-explorer
```

Only dictionary acquisition needs network access; a verified dictionary cache
replays offline. Builders refuse to replace completed outputs and confine local
candidates to `.cache`. Open the last server in a browser from the workspace.

## Public-data UI reproduction

The public replay verifies the deployed manifest's logical hash and every served
asset's exact byte count and SHA-256. Hosting controls are excluded explicitly.
The retained public presentation is not the sealed source database or model.

The revised UI adds a grounded overview guide, eight supplied browse groups with
mapped-label counts, clearer genre and artist panels, collapse and close actions,
mobile focus positioning, and keyboard navigation. It fixes failed-discovery
URLs, asynchronous search reopening, Escape restoration, and a collapsed panel
reopening when a slow discovery load settles. Shared-genre artist links state
their evidence instead of implying sonic similarity. The existing atlas remains
sparse at overview; the UI does not invent genre data to fill it.

```sh
.venv/bin/python scripts/restore_public_static_preview.py \
  --output-dir .cache/observed-public
.venv/bin/python scripts/build_local_ui_preview.py \
  --replay-dir .cache/observed-public --output-dir .cache/revised-ui
.venv/bin/python -m http.server 3002 --bind 127.0.0.1 --directory .cache/revised-ui
```

The local UI builder rechecks all recovered assets and preserves the two public
JSON assets exactly while fingerprinting current UI code. Its separate receipt
declares a modified local presentation and no source certification. It writes
no release manifest or hosting controls and cannot choose `dist` as output.

Desktop/mobile before-and-after captures are under `artifacts/ui-qa/`. Real
Chromium tests exercise ready and unavailable discovery, direct navigation,
search and Escape, collapse and close, delayed loading, and source browse counts.
The source explorer has separate desktop/mobile screenshots and interaction
evidence under `.cache/direct-custody-explorer/browser-20260930-final/`.

## Acceptance and remaining boundary

`poe check` passes formatting, lint, types, 33 JavaScript tests, and 1,203 Python
tests with 36 explicit skips for unavailable integration inputs. Independent
reviews reproduced the model's metrics, replayed source labels, reconciled
catalog counts and identity collisions, verified saved public asset hashes, and
checked desktop/mobile views.

The canonical `poe build` still needs the ignored sealed catalog and layout.
Public presentation replay does not satisfy that gate. Independent relevance
evidence and a separately reviewed source-role/promotion decision remain
necessary before research model or catalog data can enter a public release.
