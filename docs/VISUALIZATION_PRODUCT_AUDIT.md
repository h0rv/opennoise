# Visualization product audit

Audit date: 2026-08-31

## Layout inventory

| Layout or experiment | Current state | Product decision |
| --- | --- | --- |
| Historical source coordinates | Stored as a published `layout_run` with `algorithm_key = source_coordinates`. The metadata API returns a `historic_source` coordinate space. | Selectable when the run is current, displayable, and nonempty. Coordinates remain unchanged. |
| Other published layout runs | Stored through the same `layout_runs`, `layout_points`, and `current_layouts` tables. The metadata API returns a `derived` coordinate space. | Selectable through the same UI. The template does not know the algorithm. |
| Weighted Jaccard and cosine reconstruction | Implemented as bounded evaluation code in `reconstruction.py`. It produces candidate neighbors and comparison metrics. | Not presented as a map layout because it does not publish layout points. |
| Sparse labels, landmarks, density, and evidence edges | Typed presentation contracts exist in `map_presentation.py`. | Not presented as a selectable lens because no published presentation artifact exists. |
| PCA, multidimensional scaling, UMAP, PaCMAP, ForceAtlas2, OpenOrd, and hyperbolic layouts | Research candidates only. | Not shown. A candidate becomes selectable only after it writes a current, complete layout run. |
| Historical artist overlap and audio similarity neighbors | Imported as dated relation observations. | Kept as genre metadata. They are not treated as generated layout coordinates. |

The selector reads nonempty rows from `current_layouts`. It never copies point data and does not maintain a list of algorithms in HTML. Adding a new published layout requires no template change.

## Click flow audit

Before this change, the API accepted a layout key but the page, workspace fragment, search results, genre links, neighbor links, and close action returned to `default`. A click could replace the complete map, mark a point, and show only a detached close control when no discovery metadata existed. Artist and track links pointed at an entity route that did not exist. The template also had a generic listen section for playable links.

The current flow preserves one validated layout key through normal links and HTMX requests. Clicking a genre opens its stable URL and always displays a panel headed by the genre name. The panel shows available artist, album, track, and neighbor metadata. External destinations remain ordinary links. Closing the panel keeps the selected layout. Unknown layouts return an error instead of silently changing the representation.

The UI does not render audio elements, preview controls, players, waveform elements, or audio placeholders. It uses the self-hosted HTMX 4 script and no application JavaScript.
