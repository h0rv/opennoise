# Visualization research

OpenNoise uses a map as navigation, not as proof that two genres are equivalent.
The data artifact explains every displayed relation.

## Chosen pattern

Use one semantic zoom graph. The overview presents a small number of stable
map communities or broad genres. Zooming progressively reveals child genres,
nearby related genres, and the evidence graph. A selected genre shows its
evidence, nearby genres, artists, albums, and tracks.

Hackerverse is the useful reference for this interaction model. It uses a map
camera, persistent context through levels of detail, sparse labels, and stable
spatial sampling. OpenNoise adapts those interaction ideas, not its terrain
renderer, embedding, tile format, or data pipeline. The view must reveal finer
neighborhood structure as the camera moves. It must not replace one flat batch
with a denser flat batch.

## Renderer decision

Use one small viewport renderer and one versioned map-data contract for local
and static Pages. All coordinates, communities, LOD membership, aliases, and
peer evidence are computed and receipt-bound offline. The browser only fits the
actual rectangular bounds, culls labels by viewport collision and importance,
and handles pointer/touch pan, zoom, focus, and history. It never runs physics
or derives a relationship or coordinate.

SVG is suitable while the visible point budget remains small; use Canvas only
when measurement shows that DOM updates no longer meet the interaction budget.
If full-scale delivery needs it, the same contract can be spatially tiled with
coarser levels retaining landmarks from each previous level. Server-rendered
markup remains the no-script overview, not a competing scroll-zoom renderer.

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
