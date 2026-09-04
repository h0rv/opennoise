# Visualization product audit

## Product surface

The default workspace has one public semantic map, search, a selected-genre
detail region, simple zoom controls, and system, light, or dark appearance.
It also needs a minimal visualization switcher for accepted independent views;
the selector must state whether a view is public or local-only historical.

At overview, the map shows named public umbrellas or communities. Zooming adds
genres and descendants without removing the prior context. A click opens the
genre detail. It does not merely refocus an unlabeled point.

## Responsibilities

- The production-map artifact owns graph structure, coordinates, display-parent
  choices, LOD, labels, and map evidence.
- Cytoscape.js 3.34 owns viewport interaction and rendering from those preset
  coordinates.
- HTMX 4 owns server search and detail fragments.
- Normal genre URLs, search links, and server-rendered detail remain the
  accessible HTML path.
- The server-rendered SVG is a no-script fallback only. It is not a competing
  primary renderer.

## Non-goals

- No audio, preview, player, waveform, or media placeholder.
- No browser-inferred taxonomy parent, geometry, label choice, or score.
- No historical Every Noise coordinates mixed into the public graph.
- No unqualified, unversioned, or silent layout switcher. A switch must name
  the visualization, source/model boundary, and local-only status where applicable.

## Release evidence

The release checks drag or touch pan, wheel or pinch zoom, click detail, search
state, browser history, keyboard focus, dark mode, overview label reveal, and
the no-script fallback. It captures desktop and mobile screenshots in system,
light, and dark appearances.
