# Semantic renderer delivery notes

Status: active isolated renderer work. This note does not claim that the live preview is fixed.

## Product boundary

The primary product has one semantic map. The prior related, direct, communities, and taxonomy
layouts are evaluation artifacts and are not controls in the primary workspace. The renderer will
consume the versioned `production-map-v1` graph contract once published. It does not infer a
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

The focused template tests pass. Full app-browser and production-data screenshots remain pending
the graph contract and a repaired local test-client lifecycle; they must cover the qualified
603-genre map on desktop, mobile, mouse, touch, keyboard, dark mode, accessibility, and
performance before this work is reviewed for integration.
