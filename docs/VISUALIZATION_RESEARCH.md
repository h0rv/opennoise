# Visualization research

Research date: 2026-08-30

## Decision summary

Musix should treat the current Every Noise coordinates as a historical display artifact and keep them separate from any new representation. The first useful improvement is an exploration system, not a replacement embedding. It should show fewer labels at the overview, give the user stable regions and search results, and reveal points, evidence, and selected relationships as they zoom or focus.

The current server-rendered SVG and htmx interface remain a good no-JavaScript baseline for 6,291 points. It is not a good direct manipulation map at the present markup density. The map template creates one SVG link, circle, and text node for every point. That is at least 18,873 visible SVG elements and 6,291 keyboard stops, before page controls. Every label is drawn at every zoom level. This will become hard to read before it becomes impossible to render.

A small JavaScript map island is justified when Musix adds continuous pan, pointer-centered zoom, pinch zoom, viewport culling, and hit testing. A Canvas island can draw 6,291 points easily on an older laptop if it redraws only the visible viewport and keeps labels sparse. It must not replace ordinary entity URLs, search results, or the server-rendered detail view. The HTML controls and an entity list remain the accessible and no-JavaScript way to explore the catalog.

Do not choose or train a new model in this work. A new representation should be a recorded experiment with its own `layout_key`, never an overwrite of the historical layout.

## What Every Noise and Hackerverse show

Every Noise disclosed an algorithmically generated scatter plot that received readability adjustments. It used internal dimensions and two similarity measures, including artist overlap and audio similarity for related-genre maps. The public coordinates and color are display results, rather than a disclosed feature space or reproducible layout algorithm. [Glenn McDonald's presentation](https://furia.com/everynoise_public/EverynoiseIntro.pdf) and [technical notes](https://furia.com/page.cgi?skip=90&tag=tech&type=log) are the primary public descriptions. Musix should not infer semantic axes from the historical map.

[Hackerverse](https://blog.wilsonl.in/hackerverse/) is useful product research, but it addresses a far larger problem. It reduces embeddings with UMAP, saves the fitted model for later transforms, builds a multi-level tiled map, selects a stable subset at lower levels of detail, and redraws a Canvas for each viewport update. Its author reports that thousands of DOM point elements performed poorly. The open [map builder](https://github.com/wilsonzlin/hackerverse/blob/master/build-map/main.py) stores point IDs, `float32` coordinates, and scores in binary tiles. The [label worker](https://github.com/wilsonzlin/hackerverse/blob/master/app/worker.PointLabels.ts) prioritizes high-score labels, reserves collision boxes in an R-tree, and carries selected labels into later zoom levels. The public [dataset release](https://github.com/wilsonzlin/hackerverse/releases/tag/dataset-39996091) also documents its raw and embedding artifacts.

Hackerverse should not be copied as an architecture. It needs edge data, tiles, workers, binary formats, and a full Canvas application because it maps millions of records. Musix can borrow five small ideas: a distinct representation from map rendering, stable level-of-detail inclusion, sparse collision-free labels, map landmarks, and a spatial index for pointer queries.

## Representation and rendering are separate

Representation answers what two music entities are related, why, and how strongly. Rendering answers which of those facts to show in a viewport. A better renderer cannot make an untrustworthy representation meaningful, and a better representation does not require a complex renderer.

| Area | Record and version | Examples | Recommendation for Musix |
| --- | --- | --- | --- |
| Evidence graph | Source snapshot, normalization rule, edge type, weight, threshold | Artist to genre claims, shared artists, hierarchy claims, approved listening cooccurrence | Keep this source-backed and explainable. It is the basis for all later graph, community, and layout work. |
| Similarity | Metric definition and input graph hash | Weighted Jaccard, cosine on a sparse cooccurrence matrix | Start with a deterministic, inspectable baseline. Return shared artists, tags, or relation types with a similarity result. |
| Communities | Algorithm, resolution, seed, graph hash | Leiden on the same sparse graph | Use for optional region names and filters. Do not call a community a genre family without evidence and human review. |
| Coordinates | Algorithm, package version, parameters, seed, threads, input hash, orientation rule | Historical Every Noise display layout, later UMAP or graph layout experiment | Publish immutable layout revisions. Historical coordinates remain one `layout_key`; a candidate does not replace it. |
| Rendering | Viewport, zoom, visual priority, device size, chosen labels, style version | Overview density, visible points, selected point, labels | Compute this from a published layout. It must be safe to change without changing the semantic graph. |

The schema already supports the central boundary. `layout_runs` stores an algorithm version, input hash, parameters, status, and policy. `layout_points` stores derived coordinates, and `current_layouts` selects only a completed run. The `displayable_map_points` view already provides stable entity ID, kind, name, coordinates, display weight, and color. This is a strong base for experimentation.

## Layout methods

All nonlinear two-dimensional layouts can change distances, density, cluster area, and apparent gaps. The map should say that nearby points are candidates for exploration, while the entity detail page shows the source evidence. Neighbor-quality measurements should decide whether a candidate layout is published.

| Method | What it lays out | Strengths | Limits for a durable music map | Incremental placement and repeatability | Fit on an older laptop and 6,291 points |
| --- | --- | --- | --- | --- | --- |
| UMAP | Feature vectors or a supplied k-nearest-neighbor graph | Good practical local neighborhoods. Its official implementation accepts precomputed neighbors and can transform new records after fitting. | Two-dimensional distance and cluster area are not literal. A full refit can move old points. | Keep a frozen reference model for additions. Save the fitted model and use `transform` for newcomers. Exact repeatability requires the same k-nearest-neighbor graph, seed, versions, and single-threaded optimization. UMAP documents that seeded multi-threaded optimization is not exactly repeatable. [Transform](https://umap-learn.readthedocs.io/en/latest/transform.html), [precomputed neighbors](https://umap-learn.readthedocs.io/en/latest/precomputed_k-nn.html), and [reproducibility](https://umap-learn.readthedocs.io/en/latest/reproducibility.html). | Good experiment candidate. Small enough for CPU use, although deterministic builds trade speed for repeatability. |
| PaCMAP | Feature vectors or a supplied neighbor graph | The method uses neighbor, mid-near, and farther pairs to preserve local and more global structure. Its maintained implementation offers `fit`, `fit_transform`, and `transform`. [Implementation](https://github.com/YingfanWang/PaCMAP) and [paper](https://www.jmlr.org/beta/papers/v22/20-1061.html). | The paper warns that two-dimensional reduction can mislead. Parameters and approximate neighbor backend affect the result. | Test `transform` only after proving that placements remain stable enough. Save the supplied graph, initialization, package version, and random state if exposed by the selected release. | Good comparison candidate, but not a default before an evidence graph and evaluation fixture exist. |
| t-SNE | Feature vectors or affinities | A strong local visualization baseline. Barnes-Hut variants scale better than the original method. [Original paper](https://www.jmlr.org/beta/papers/v9/vandermaaten08a.html). | It is poor as a stable world map because global distances and empty space are easy to overread, and full refits can move points. | openTSNE has partial embeddings for placing new samples into a fixed reference layout, but its own API says those are not a general way to add samples to an existing embedding. [openTSNE API](https://opentsne.readthedocs.io/en/latest/api/index.html). | Feasible at this size, but use only as a quality comparison. Do not make it the main navigable coordinate system. |
| ForceAtlas2 | Weighted graph | Directly displays graph structure. Edge weights, gravity, Barnes-Hut approximation, and worker execution are exposed by the maintained Graphology implementation. [Graphology documentation](https://graphology.github.io/standard-library/layout-forceatlas2.html) and [original paper](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0098679). | Coordinates are sensitive to parameters and graph components. The layout does not make non-edge distance semantic. | For a candidate update, initialize from old coordinates, fix a deterministic node and edge ordering, bound the iterations, and record all settings. New nodes can begin at a neighbor weighted barycenter. A later full relaxation is a new revision. | Very feasible at 6,291 nodes after graph pruning. It is the best graph-only comparison if Musix has no approved vector representation. |
| OpenOrd | Large weighted graph | Parallel, multistage layout with edge cutting and multilevel clustering. Its original paper describes these choices, and Gephi exposes edge cutting and parallel execution. [Paper record](https://doi.org/10.1117/12.871402) and [Gephi documentation](https://gephi.org/desktop/plugins/openord-layout/). | Aggressive edge cutting changes visible graph structure. Its goal is cluster separation at large scale, not stable incremental placement. | Treat it as an offline benchmark. It is not a good source of placements for individual new artists or albums. | It is unnecessary at 6,291 points unless a later graph grows by orders of magnitude. |

Use UMAP, PaCMAP, and t-SNE only after Musix has a user-approved feature representation. Use ForceAtlas2 only after it has a pruned, weighted, source-backed graph. None of these methods recovers the original Every Noise model.

## Landmark placement and incremental updates

A map must distinguish a published revision from a live update. Recomputing every coordinate whenever one entity arrives makes bookmarks, screenshots, and learned spatial memory unreliable.

First, keep the published coordinates and layout manifest immutable. Second, create a reference set of high-confidence genres or artists, selected by a documented rule rather than visual preference. Third, place a newcomer against that fixed reference. UMAP and PaCMAP provide transform methods. A graph-only layout can start a new node at the weighted barycenter of its known neighbors. Fourth, calculate and expose placement confidence, such as the count and total weight of known neighbors, and do not place records with too little evidence. Fifth, run a full candidate layout only on a schedule or when a declared coverage threshold is crossed. Publish it as a new revision after evaluation.

There is an important orientation issue. Translation, reflection, rotation, and scale are display choices. A candidate layout can be aligned to a documented landmark set so returning users retain orientation. This alignment does not make the candidate layout equivalent to Every Noise. Store the raw layout coordinate system and the display transform separately.

For deterministic builds, sort node IDs and edges canonically, use exact neighbors for this scale when practical, use fixed seeds, pin library versions, record thread count, and hash all inputs and parameters. Keep a small frozen fixture that checks byte-identical output for a deterministic runner. If a fast approximate or multi-threaded build is intentionally used, publish the seed, tolerances, and a stability result rather than falsely calling it exact.

## Communities, landmarks, labels, and edges

Communities help exploration when they are shown as a second view of a graph rather than as an imposed taxonomy. Leiden supports weighted partitions, a resolution parameter, and a random seed. Its implementation documents `set_rng_seed` and resolution profiles. [Leiden documentation](https://leidenalg.readthedocs.io/en/latest/reference.html). Run a small resolution sweep, measure community stability, and name only the largest stable regions after reviewing their evidence. A community color should be optional, because color already has historical meaning in the imported Every Noise display.

At the overview, add a small number of region labels that identify a reviewed topic or a stable community. Hackerverse calls these cities, but its author found manual labels more useful than automatic K-means or generated labels. Use plain terms such as "Japanese rock" only when data supports them. Region labels are navigation aids, not generated facts.

Point labels need a priority rule. Favor a selected entity, direct search hits, high-confidence genres, and high-weight artists. Add a label only when it does not collide with an already accepted label in screen space. An R-tree supports collision and viewport queries. [RBush](https://github.com/mourner/rbush) is a maintained browser implementation. A static packed index such as [Flatbush](https://github.com/mourner/flatbush) is smaller and faster when the published layout does not change in a browser session. Keep parent level labels when zooming in, then add more labels. Do not make labels disappear merely because a new level loads.

Do not draw all graph edges by default. At this density, edges will hide the map more than they explain it. Show a selected point's strongest few evidence-backed relations on demand, with a clear relation type and weight. Edge bundling can reduce clutter and reveal high-level patterns in a dedicated overview, but bundled paths also make individual links harder to follow. The original force-directed edge bundling paper describes it as a summary technique for high-level patterns. [Holten and van Wijk](https://doi.org/10.1111/j.1467-8659.2009.01450.x). It is not recommended for the default Musix map.

## Rendering choices

| Technique | Use at 6,291 points | Benefits | Limits and required fallback |
| --- | --- | --- | --- |
| Server-rendered SVG plus htmx | Keep as the initial and no-JavaScript view. Render overview regions and a bounded set of labels, or render a focused neighborhood. | Text, links, print output, browser zoom, and familiar server templates. It fits the existing app. | Do not expose thousands of focusable SVG links at once. Provide a summary, search, filters, and an entity page. SVG `title` and `desc` need explicit accessible naming and support varies. [W3C SVG guidance](https://www.w3.org/WAI/tutorials/images/tips/) and [ACT rule](https://www.w3.org/WAI/standards-guidelines/act/rules/7d6734). |
| Canvas 2D island | Add only for continuous pan, pinch, cursor-centered zoom, hover, and click selection. Send all 6,291 compact points initially, then cull and draw by viewport. | Fewer DOM nodes and smooth redraws. This is enough for the catalog size, so WebGL and tiles are not required. | Canvas pixels have no per-point accessibility tree. Mirror focus and selection into an HTML result list, use ordinary URLs, support keyboard search and result navigation, and retain the SVG or list view. |
| WebGL | Defer. | Useful for hundreds of thousands of dynamic points, complex marks, or animated edges. | Adds GPU, shader, context-loss, text, picking, and accessibility work without a need at this scale. |
| Tiles and multi-level binary data | Defer. | Useful when initial transfer or draw cost becomes material at much larger scale. Hackerverse uses this for millions of records, targeting small tiles and level-of-detail sampling. | More build artifacts, cache rules, and client code. For 6,291 points, a compressed JSON or compact binary response is simpler. |
| Density contours or a heat layer | Add as an optional overview background. Precompute from published coordinates, using an explicitly named measure such as entity count or confidence-weighted count. | Gives orientation when points are too dense to label. SVG contour paths remain sharp. Hackerverse used gridded, log-scaled density and vector contours. | Density is not similarity and must be labeled. Avoid color choices that imply a semantic axis. |

The old-laptop budget should be based on measured time, not a renderer brand. A Canvas loop that draws six thousand circles and tens of labels per frame is feasible. A Canvas loop that measures thousands of strings, allocates objects every frame, or redraws thousands of edges is not. Build static arrays and a static spatial index once. Use `requestAnimationFrame`, device-pixel-ratio scaling, a maximum label count, and pointer hit testing from the index. Move a costly label-collision pass to a worker only if profiling shows it blocks interaction. Hackerverse did this at its much larger scale; Musix should measure first.

Mobile needs direct behavior rather than a smaller desktop map. Keep the search field usable above the map, make the selected result a bottom sheet or ordinary section, use pinch and one-finger pan only inside the island, and include zoom controls that do not depend on a wheel. Do not rely on hover. Keep text sized for the device, and do not require a user to hit a three-pixel point to discover an entity.

## Proposed map contract

The existing JSON endpoint already has the right basic point fields: stable ID, kind, name, x, y, weight, and color. Before a map island is added, extend the published response or a parallel metadata endpoint with a layout manifest and bounds. These are a contract proposal, not an instruction to change the current route immediately.

| Field or route | Why it is needed |
| --- | --- |
| `layout_key`, immutable `layout_revision`, `input_hash`, and `coordinate_transform_version` | Keeps client caches and URLs tied to a published spatial artifact. |
| `bounds: {min_x, min_y, max_x, max_y}` and `point_count` | Lets any renderer initialize a viewport without scanning all points. |
| Existing point fields plus optional `community_id`, `label_priority`, and `placement_confidence` | Supports rendering choices without inventing semantic facts in the browser. |
| `GET /api/map?layout=...&detail=overview|points&bbox=...&zoom=...` | Allows future culling and semantic zoom while retaining a simple full-points response now. Validate and bound every value. |
| `GET /entities/{id}` or equivalent ordinary document URL | Gives selection a shareable, accessible destination that does not require Canvas hit testing. |
| `GET /fragments/map?layout=...&focus=...` | Keeps the current htmx fallback. Add a bounded viewport or detail level only after a server rendering policy exists. |

The interface should keep `layout` and `focus` in URLs. It should never treat a Canvas coordinate as identity. Stable entities and published layout revisions are the durable references.

## Ranked recommendations

1. Keep the historical layout unchanged, and create an overview rendering policy. At the global view, show points, a capped collision-free label set, a small number of reviewed landmarks, and an optional density contour. Show all details only after search or focus. This is a rendering change and needs no model choice.

2. Add evidence-backed selected relations and region filters. Return the strongest few relationships with type, source, and weight after an entity is selected. Evaluate Leiden communities as a separate, seed-recorded graph analysis. This improves exploration without pretending the historical coordinates have new meaning.

3. Add a small Canvas map island only after the overview policy is measured. Keep server SVG, keyboard search, ordinary links, and an HTML selection pane. Send the whole point set initially and use a static spatial index. Do not add WebGL, tiles, or edge bundling at this size.

4. Run a user-approved representation experiment in a new layout key. Compare a graph-only ForceAtlas2 layout with UMAP and PaCMAP only if an approved feature representation exists. Freeze the historical layout and publish only a candidate that meets the evaluation criteria below.

5. Add landmark and incremental placement only after a candidate representation is trusted. Use a frozen reference layout for additions, surface low-confidence placement, and schedule full re-layouts as distinct revisions. Do not silently move the world map.

## Evaluation criteria

Publish an experiment report next to each candidate layout. The report should include the exact source snapshots, policy decision, graph or feature hash, algorithm and package versions, parameters, seed, threads, coordinate transform, machine class, and output hash.

| Measure | Minimum comparison |
| --- | --- |
| Data coverage | Count mapped genres, artists, albums, and unplaced records. Report why each record is absent or low confidence. |
| Local faithfulness | At `k = 10`, measure k-nearest-neighbor overlap and trustworthiness against the source graph or approved feature distance. Scikit-learn defines trustworthiness on a 0 to 1 scale and penalizes unexpected map neighbors. [API documentation](https://scikit-learn.org/stable/modules/generated/sklearn.manifold.trustworthiness.html). |
| Evidence review | Blind-review 100 stratified neighbor pairs. A reviewer should see source evidence, not coordinates alone, and label each pair as useful, uncertain, or wrong. Compare candidate layouts to the current historical display separately. |
| Stability | Rebuild from the same inputs and require byte identity for the deterministic path. For planned incremental additions, measure median and 95th percentile movement of existing landmarks after alignment. Set a product threshold before publishing. |
| Community stability | Repeat a seeded Leiden resolution sweep and report adjusted agreement between partitions and the fraction of small or unstable communities. Human names require evidence review. |
| Exploration task success | Test at least 10 people or structured internal sessions. Measure time and success for finding a known genre, finding a related artist, returning to a saved entity, and explaining why two records are related. Include keyboard and touch tasks. |
| Performance | On the stated old-laptop browser, measure initial response bytes, first usable map, 95th percentile pan and zoom frame time, pointer selection latency, memory, and keyboard navigation. Set budgets before implementation, for example 1 second local first usable map, 16.7 ms median interaction frame, 50 ms 95th percentile selection after data is loaded, and no long task above 50 ms during a normal pan. |
| Accessibility | Test keyboard-only navigation, visible focus, screen reader access to search and selected details, text scaling to 200 percent, touch target size, reduced-motion behavior, and no-JavaScript entity discovery. |

## Experiments

### Experiment 1: Overview rendering without a new representation

Use the existing pinned 6,291-point historical layout. Produce three server-rendered variants: every label, priority labels with collision avoidance, and priority labels plus reviewed landmarks and an optional density contour. Keep every point and coordinate unchanged. Compare payload size, rendered SVG node count, first usable map time, number of visible labels, keyboard stops, and task success for finding a searched and an unsearched genre. Keep the best variant as the non-JavaScript baseline.

### Experiment 2: Canvas island versus the improved SVG baseline

Use the same layout and data as Experiment 1. Build a bounded prototype that loads all compact points once, draws only the viewport on Canvas, uses a static spatial index for hit testing, and mirrors selection into ordinary HTML. Do not add tiles, WebGL, or graph edges. Compare desktop and touch tasks on the old laptop, including 95th percentile frame time, memory, keyboard access, screen reader selection flow, and no-JavaScript fallback success. Keep Canvas only if direct manipulation materially improves tasks without losing the fallback.

### Experiment 3: Candidate representation and incremental placement

After the user approves the input representation, build the same canonical sparse graph or feature matrix once. Compare one graph layout, such as ForceAtlas2, with UMAP and PaCMAP. Use fixed input ordering, recorded seeds, and a held-out set of later records. First, score local faithfulness and evidence review. Second, fit a frozen reference and place held-out records with the method's transform or a graph barycenter. Third, compare those placements with the later full candidate layout and report movement and neighbor agreement. Publish no candidate that fails the agreed stability and evidence thresholds.

## Sources

This document uses primary papers, maintainer documentation, and implementation source where possible. The main current implementation references are the [Hackerverse article](https://blog.wilsonl.in/hackerverse/), its [open repository](https://github.com/wilsonzlin/hackerverse), the [UMAP documentation](https://umap-learn.readthedocs.io/en/latest/), the [PaCMAP implementation](https://github.com/YingfanWang/PaCMAP), [t-SNE paper](https://www.jmlr.org/beta/papers/v9/vandermaaten08a.html), [ForceAtlas2 paper](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0098679), [Gephi OpenOrd documentation](https://gephi.org/desktop/plugins/openord-layout/), [Leiden documentation](https://leidenalg.readthedocs.io/en/latest/), [RBush](https://github.com/mourner/rbush), and [W3C SVG accessibility guidance](https://www.w3.org/WAI/tutorials/images/tips/).
