# Production map QA, 2026-08-31

Status: blocked. The primary map is not ready to publish.

The current production-layout candidate uses 603 qualified genres. The latest
similarity-first run reports top-10 one-hop neighbor recall of `0.22144` and
top-25 recall of `0.24318`. The acceptance floor for top-10 is `0.30`, so the
candidate is rejected. An independent rebuild also failed central-span and
16-by-9 densest-cell gates. It does not produce a publishable artifact.

A historical one-hop spectral number of `0.5173` was reported, but it does not
have a matching input/reference hash and node scope. It is not evidence of
acceptance. The comparable sealed 468-node source result is `0.223221508446`.
Re-run any stronger baseline against the qualified 603-node model and publish
the Pareto table before selecting a production layout.

The acceptance harness is in `src/musix/ml/production_map_qa.py`. It is
renderer-neutral so the data model owns coordinates, graph choices, semantic
zoom levels, label decisions, and similarity evidence. The UI owns screenshots
and interaction evidence. Both are needed for a passing report.

The harness rejects the collapsed-map failure in the earlier screenshots with
central-span, occupancy, duplicate-position, label-collision, and outlier
checks. It also rejects a visual layout that looks spacious but destroys local
similarity.

Required renderer evidence is six generated images: 1366 by 768 desktop and
390 by 844 mobile in system, light, and dark modes. It must also record passing
drag/touch pan, wheel/pinch zoom, click detail, retained search state, browser
back, keyboard focus, dark mode, and no-JavaScript SVG fallback checks.
