# Static public map

The default OpenNoise map renders the sealed, source-neutral
`data/model/production-map-v1.json` receipt. It does not load historical
coordinates, Cytoscape, a canvas, or a client layout engine.

The default URL is `/?level=0&zoom=0`: 116 persisted L0 nodes and 68 persisted
desktop label decisions. `+` and `-` are ordinary URLs that increase or reduce
both receipt LOD and the pre-sized SVG canvas. `Fit` returns to that default.
At zoomed levels the fixed `#static-map-viewport` is native-scrollable; no
pointer, wheel, simulation, or collision JavaScript runs. Genre anchors use
ordinary `/genres/key/...` URLs, with HTMX only as progressive enhancement.
The full 6,291-name Open v2 corpus remains search/focused-fact navigation, not
a semantic overview.

The renderer consumes stored coordinates and stored label decisions only.
Its request path is template composition and cached artifact lookup, while Open
v2 focused SVG presentation is lazy and memoized. The LOD sequence persists
previously visible nodes: 116/134/210/603 nodes, with 68/77/102/163 desktop
labels.

The static browser QA harness captures desktop and mobile light/dark/system
views and checks Fit, URL LOD, native/programmatic scroll, ordinary genre
links, graph-asset absence, and browser errors. On the local `poe dev` cold
navigation used for this checkpoint it observed 4 requests, 122,862 transferred
bytes, and 1,482 ms navigation duration (FCP/LCP unavailable from this headless
trace). Runtime graph assets removed: 435,328 bytes of Cytoscape plus 87,516
bytes of controller, 522,844 bytes uncompressed. The remaining graph-related
runtime script is only 36,717-byte HTMX.
