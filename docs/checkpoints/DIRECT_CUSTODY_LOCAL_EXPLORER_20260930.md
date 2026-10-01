# Local source-model explorer

The actual portable-corpus model is now navigable as a static local application.
The completed build is
`.cache/direct-custody-explorer/run-20260930-final/index.html`.
It is separate from `dist`, public manifests, and every release/deployment path.

The explorer contains all 697 directly observed source genres, with exact native
MusicBrainz UUID labels. It retains 683 graph-derived positions and 14 searchable
unplaced genres. It exposes 13,089 bounded directly observed artist examples and
13,642 separately marked inferred proposals, covering 15,902 distinct artists.
Each displayed artist links to all of its exact directly observed source genres
and its MusicBrainz record. The underlying source cohort remains 198,409 artists;
the preview does not claim to expose every artist in its bounded examples.

## Source and model boundaries

The builder verifies the model report and all its byte-bound artifacts, the
candidate catalog receipt/database/quality report, and the native label
supplement's exact retained MusicBrainz response pages. Model and catalog direct
source object and receipt hashes must match. Every retained model observation
matrix pair must then equal the verified catalog's exact artist–seed projection;
matching row counts alone are insufficient.

Direct artist examples are ordered by exact MusicBrainz ID and capped at 20 per
genre. They are source examples rather than representative or relevance-ranked
artists. Canonical artist names join only by exact MBID; missing usable names
display the MBID. A single native genre UUID can supply a genre label, while
ambiguous or missing UUID joins retain an unresolved-label state. All 697 current
source genres have one exact native label.

Each inferred genre neighbor shows its shared source artist count. Artist
proposals retain their contributing direct source genres, are disjoint from the
selected genre's direct observations, and are visibly marked as inferred. The
application states that their genre-to-artist ranking has not been evaluated.
The model's held-out artist-to-genre recovery does not validate these proposals,
artist-to-artist relevance, or visual geometry.

Coordinates use only the model's weighted peer edges. The builder takes the
maximum score over the two directions of each canonical pair, then reuses the
existing deterministic weighted spectral primitive and rectangular atlas fit.
Names are joined after this coordinate calculation. No historical names,
coordinates, memberships, or public atlas geometry are read. Genres without
supported peer edges receive null coordinates and remain accessible through
search. Two real builds reproduced identical coordinates for every genre.

## Interaction and browser evidence

The browser receives only HTML, CSS, JavaScript, and precomputed JSON. There is
no backend API or browser graph-layout calculation. Search, clickable map points
and labels, pan, zoom, fit controls, genre details, direct artist traversal, and
inferred peer/proposal navigation work on desktop and mobile. A local static HTTP
server is sufficient; opening the HTML through `file://` is not the supported
loading path because the data is fetched as a separate asset.

Real Chromium evidence is in
`.cache/direct-custody-explorer/browser-20260930-final/`:

- `desktop.png`: Jazz's source observations and modeled neighborhood.
- `artist.png`: an exact source artist and its directly observed genres.
- `unplaced.png`: an unplaced genre reachable through search.
- `mobile.png`: the responsive map/detail flow at 390 × 844.
- `browser-report.json`: passed traversal, inference separation, all 14 unplaced
  search results, no-result state, zoom and drag canvas changes, no horizontal
  overflow, and zero runtime exceptions.

The desktop and mobile screenshots were inspected. Eight Python tests cover
deterministic graph placement, label independence, null-coordinate abstentions,
direct/inferred separation, replayed proposal explanations, ambiguous native
labels, source hash and exact matrix-pair mismatches, and rejection of public
output destinations. Focused tests, Ruff, type checking, and JavaScript syntax
checks pass.

## Reproduce the local build

With the completed source-model experiment, final candidate catalog, and
retained native label supplement available, run:

```sh
.venv/bin/python scripts/build_local_direct_custody_preview.py \
  --model-directory .cache/direct-custody-neighborhoods/run-20260930-final \
  --catalog-directory .cache/musicbrainz-candidate-catalog-final \
  --label-directory .cache/musicbrainz-native-genre-labels \
  --output .cache/direct-custody-explorer/replay-20260930

.venv/bin/python -m http.server 8876 --bind 127.0.0.1 \
  --directory .cache/direct-custody-explorer/replay-20260930
```

In a separate terminal, reproduce the browser checks with a fresh evidence
directory:

```sh
node scripts/capture_direct_custody_preview.mjs \
  http://127.0.0.1:8876/ .cache/direct-custody-explorer/browser-replay-20260930
```

The builder is create-only and accepts output only under the checkout's `.cache`.
It performs no source acquisition. Native dictionary acquisition and custody
verification belong to the separate enrichment adapter. Chromium is required
for the browser capture, with an optional `CHROMIUM_PATH` override.

The final preview receipt logical SHA-256 is
`9c1fac03f1c39f2b16187905de03b14a60f52578b119a89955b10650fbd328f1`.
Its `data.json` byte SHA-256 is
`8dbdd621beb410f6ff552a531153d70b2a5880fed812f043497c89d47d596a00`.
It binds the final catalog receipt
`43593ab9702da7cc3b2c6837e96cd337cfa924556d1f931a7a383a3a00eed0b0`,
the native-label supplement
`0828cd074c756d2ce4291c6a1d4cf58fdcc28353ba1084481a44c43922bc947a`,
and the [source model checkpoint](DIRECT_CUSTODY_SPARSE_NEIGHBORHOODS_20260930.md).
All local/public policy fields remain explicitly non-authorizing.
