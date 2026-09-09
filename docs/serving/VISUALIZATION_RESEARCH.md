# Visualization research

Musix uses a map as navigation, not as proof that two genres are equivalent.
The data artifact explains every displayed relation.

## Chosen pattern

Use one semantic zoom graph. The overview presents a small number of stable
map communities or broad genres. Zooming progressively reveals child genres,
nearby related genres, and the evidence graph. A selected genre shows its
evidence, nearby genres, artists, albums, and tracks.

Hackerverse is the useful reference for this interaction model. It uses a map
camera, persistent context through levels of detail, sparse labels, and stable
spatial sampling. Musix adapts those interaction ideas, not its terrain
renderer, embedding, tile format, or data pipeline. The view must reveal finer
neighborhood structure as the camera moves. It must not replace one flat batch
with a denser flat batch.

## Renderer decision

Cytoscape.js 3.34 is the graph island. It supports preset positions, pointer
and touch pan, wheel and pinch zoom, selection, and graph level interaction.
HTMX 4 stays responsible for search, detail fragments, browser history, and
ordinary HTML links. This keeps direct manipulation local and keeps navigation
inspectable.

The server rendered SVG is a no script fallback. It is not expected to provide
production pan or semantic zoom. Canvas, WebGL, workers, binary tiles, and edge
bundling are deferred until measured need proves that Cytoscape cannot meet the
target interaction budget.

## Required map evidence

- Stable public node ID, display name, and ordinary detail URL.
- Taxonomy DAG and separately marked display parent decisions.
- Direct and one hop profile membership facets.
- Ranked similarity rows and shared support counts.
- Immutable coordinate, LOD, label, and geometry decisions.
- Desktop and mobile label, interaction, accessibility, and dark mode checks.

## Later experiments

Compare graph and hierarchy aware coordinate methods only against the same
sealed public evidence graph. Historical Every Noise output is an evaluation
reference, never hidden training data. Do not add audio inputs to make a map
look more like a proprietary historical one.

Sources: [Hackerverse map design](https://blog.wilsonl.in/hackerverse/),
[Hackerverse map builder](https://github.com/wilsonzlin/hackerverse/blob/master/build-map/main.py),
and [Cytoscape.js](https://js.cytoscape.org/).
