# Production map QA, 2026-08-31

Status: accepted from the retained final-integration release bundle; not
independently reproducible from this checkout because its sealed source-cache
database is absent.

The accepted artifact has 603 qualified genres, 712 full taxonomy edges, 603
explicit presentation-parent choices, four monotonic LODs, and six hashed
browser screenshots. Its final `production-map-v1.report.json` records no
failures: central 90% spans are `0.96` on both axes, 16-by-9 occupancy is
`0.7777777778`, the densest cell holds `0.1011608624` of nodes, and all checked
desktop and mobile labels are collision-free.

The old absolute `0.30` recall floor was superseded. Current acceptance in
`src/musix/ml/production_map_qa.py` requires (1) null-adjusted top-10 quality
of at least `0.98` against a same-scope canonical spectral baseline and (2) a
top-10 lift of at least `0.15` above its exact per-query random null. The
accepted bundle records top-10 recall `0.1699327437`, random recall
`0.0125397376`, canonical baseline `0.1648194214`, and normalized quality
`1.0335784929`. It evaluates all 603 mapped genres using matching model,
neighbor, and eligible-set hashes.

The first, renderer-neutral seed report is expected to be `accepted: false`:
it is generated before browser evidence and names the missing screenshots and
interactions. The final browser-enriched acceptance report is the release
decision. It records passing drag/touch pan, wheel/pinch zoom, click detail,
search state, browser back, keyboard focus, dark mode, overview-label reveal,
and the no-JavaScript SVG fallback.

The historical reports of failed exploratory layouts remain useful experiment
records, but they are not the status of this accepted bundle. The open release
blocker is source-cache retention: `release-certify` correctly refuses to run
without `data/phase3-public-qualified.sqlite`.
