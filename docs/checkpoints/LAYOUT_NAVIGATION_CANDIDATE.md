# Offline layout navigation candidate

`scripts/build_layout_navigation_candidate.py` is an experiment only. It never
updates the published atlas, browser asset, or site selection.

Construction receives exactly the five sealed open inputs used by the semantic
layout builder: the peer index and peer manifold, hierarchy artifact, and
co-listen artifact and cache. It rejects their existing historical-input flags.
The candidate adds a deterministic, bounded post-placement separation of points
closer than `0.0002` world units. This is display geometry only; it neither reads
historical Every Noise coordinates nor runs a browser-time simulation.

The supplied baseline atlas is deliberately opened only after the candidate has
been built and written. It is comparison data, not construction input. The
report records its byte hash and compares connected near-coordinate groups at
`1e-4`, as requested by the navigation audit. It also records the candidate's
source bindings, settings and output hashes, exact-collision count, and the
existing open-graph neighborhood preservation measures. Both sides are packed
with the same static-label procedure used for the browser asset, so the report
also compares labels above `1e6` and maximum reveal scale. This candidate is
not promotable when those human-reachability measurements do not improve.

Example (write under a separate experiment directory):

```sh
uv run python scripts/build_layout_navigation_candidate.py \
  --peer-index .cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite \
  --peer-manifold-artifact .cache/musicbrainz-full-seed-targets/pipeline/peer-community-layout-v1.json \
  --hierarchy-artifact .cache/hierarchy-fusion-v1/artifact.json \
  --colisten-artifact .cache/genre-colisten-neighborhoods-v1/32017c0a2cff27485671151663dfc9f184e8b2f9e354ba73d712e3ca8140b141/artifact.json \
  --colisten-cache .cache/genre-colisten-neighborhoods-v1/32017c0a2cff27485671151663dfc9f184e8b2f9e354ba73d712e3ca8140b141/genre-neighborhoods.sqlite \
  --output .cache/layout-navigation-candidate-v1/artifact.json \
  --report .cache/layout-navigation-candidate-v1/report.json \
  --baseline-atlas .cache/semantic-map-layout-v2/artifact.json
```

Passing the report's narrow geometry gate is not publication approval. The
browser and focus-route checks in `LAYOUT_NAVIGATION_AUDIT.md` remain required
before any candidate could be selected.

## Measured local run

The sealed local run produced candidate output hash
`bb8febb6b8f27b0f918f5ed580e2101fac37ced8aa436f8da4dcef98a91e20a6`
and report hash
`3bf03d103eac75050285ad241dca1fcf9016a5ba6f9fe08b8947a4de35a74cb5`.
Against the v2 baseline, connected near groups at `1e-4` fell from 262 nodes
in 79 groups to zero. Labels above `1e6` fell from 117 to 8 and the maximum
static reveal scale fell from `1.064e12` to `1.305e6`. Peer KNN preservation
was `0.18239`, within `0.00007` of the v2 measurement (`0.18246`).

This is an offline geometry result, not a publication decision. The remaining
eight labels above `1e6` mean the audit's human-reachability debt is not fully
closed; browser/focus-route evidence is still required.

## Isolated static export and browser evidence

The same artifact was exported only to
`.cache/layout-navigation-candidate-v1/site`, with static-export output hash
`4dedf85973c87045fd209ecbb8a1c9efac1294d0a78feb1ff05ca31daa30fda7`.
No `dist` asset or deployment selection was modified. The existing browser QA
ran successfully against that loopback-only directory and wrote
`.cache/layout-navigation-candidate-v1/browser.json` plus 17 screenshots.
It recorded the required overview shape (23 points, 23 labels, no overview
edges, 87.96% width and 70.68% height), successful focus/artist/mobile/dark
mode paths, and a 6.5 ms renderer p95.

The QA harness now traces renderer-provided node IDs only when the browser
preload opts in. It checks that each visible label has its own visible point and
records every label that exits while its point is still drawn. The strict flag,
`--require-label-point-exit`, turns that ledger into a failing invariant.

The rerun established that this is a renderer behavior, not an aggregate-count
harness error: the strict candidate run fails with still-visible point IDs
`item4806`, `item5`, `item1270`, `item4425`, `item222`, `item1114`, `item122`,
`item59`, and `item53` across the fixed-center trajectory. Static labels are
removed when their viewport/overlay box is ineligible, while the renderer's
separate point path continues to draw their nodes. The regular identity report
is `.cache/layout-navigation-candidate-v1/browser-identity.json`. The initial
all-exits diagnostic failed; the final conditional strict gate records the
allowed edge/overlay reasons and passes. The remaining eight labels above
`1e6` still block promotion.

### Exact exit classification

The identity evidence was rerun with a reconstruction of the renderer's static
label eligibility from the exported candidate atlas. Six exits are
`label_box_viewport_clipping` (`item4806`, `item5`, `item1270`, `item4425`,
`item1114`, and `item122`): the point remains on canvas but its complete fixed
caption would extend beyond an edge. `item222` and `item59` are
`point_edge_tolerance_visible`: their dots are in the renderer's intentional
8px hit-test fringe just outside the strict viewport. `item53` is
`overlay_occlusion`, where its label box intersects a visible search/control
overlay. No failing exit is caused by LOD or reveal-scale filtering.

The final strict report is
`.cache/layout-navigation-candidate-v1/browser-identity-order-strict.json`.
It was run against a fresh isolated export at
`.cache/layout-navigation-candidate-v1/site-order`, not the published `dist`.
Its trace preserves Canvas label draw order, so every label ID is paired with
the corresponding captured `fillText` position before reconstructing its box.

The smallest promotion invariant is therefore conditional rather than a raw
point-count rule: every admitted label must have its own drawn point; an exited
label may remain dotted only when its full static label box crosses the viewport
boundary, overlaps a visible overlay, or its point is in the renderer's 8px
edge fringe. Any exit whose point and complete label box are inside the usable,
overlay-free viewport must fail certification. This preserves the strict rule
for interior labels while allowing captions that cannot safely be drawn at the
edge or beneath UI. The candidate strict flag now enforces this conditional
invariant, retains every exemption reason in its report, and passes this
candidate without selecting or publishing it.
