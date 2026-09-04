# Semantic renderer delivery notes

Status: accepted in the retained final-integration release bundle. The bundle
contains passing browser evidence and six hashed screenshots, but the sealed
source-cache database needed to regenerate it is not retained in this checkout.

## Product boundary

The default product map is semantic. Independently versioned public layouts and a clearly labelled
local-only historical compatibility view remain required switchable visualizations once each has
its own accepted artifact. The renderer consumes the versioned `production-map-v1` graph contract.
It does not infer a
taxonomy parent: all P279 DAG edges remain separately available. An optional
`display_parent_id` is a model-supplied, explicitly non-canonical presentation grouping only.

## Renderer boundary

The renderer vendors Cytoscape.js 3.34.0 locally. Its distribution SHA-256 is
`9c2a3bf2592e0b14a1f7bec07c03a54f16dedf32af9cd0af155c716aa6c87bc3`; the included MIT license
SHA-256 is `eb319c6e6f233607f71e8e2f450391751883cfc0eeb3ca7ef574c13d1d9c2203`. There is no CDN or
npm runtime dependency.

Cytoscape owns preset-coordinate rendering, pan, wheel and pinch zoom, optional compound display
groups, selection, and semantic label/node level of detail. HTMX owns server search, detail
fragments, history, and link fallback. The SVG map remains usable without JavaScript.

## Verification status

The retained final integration passed the required desktop and mobile system/light/dark screenshots
and interaction checks for the qualified 603-genre map. It is evidence for the default public
renderer, not evidence that the historical full-map switch is eligible or implemented.
