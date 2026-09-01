# Production map QA, 2026-08-31

Status: blocked. The primary map is not ready to publish.

The current production-layout candidate uses 603 qualified genres. Its model
reports top-10 one-hop neighbor recall of `0.158785391387` and top-25 recall of
`0.168732605067`. The acceptance floor for top-10 is `0.30`, so this candidate
is rejected even though its central spans (`0.8622`, `0.6524`), 16 by 9
occupancy (`0.575`), region containment (`1.0`), and root-region overlap (`0`)
are promising.

A historical one-hop spectral number of `0.5173` was reported, but it does not
yet have a matching input/reference hash and node scope. It is not evidence of
acceptance. Re-run it against the qualified 603-node model and publish the
Pareto table before selecting a production layout.

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
