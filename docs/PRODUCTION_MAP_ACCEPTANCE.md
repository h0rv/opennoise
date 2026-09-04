# Production map acceptance

The app has one production map. It is a persistent semantic-zoom graph, not a
choice of layout lenses.

`poe evaluate-production-map <evidence.json> --report <report.json>` accepts
only an evidence bundle that passes every gate below. A failed gate exits nonzero
and blocks publication.

- Every coordinate is normalized, unique, and present in the final zoom level.
- The central 90% of coordinates spans at least 45% of both map axes.
- At least 20% of a 16 by 9 viewport grid is occupied. No grid cell holds more
  than 15% of nodes.
- At most 5% of nodes can be spatial outliers. An outlier has its fifth nearest
  neighbor more than 45% of the normalized map away.
- The full taxonomy remains a DAG. Every node has one explicit rendering-parent
  choice. A taxonomy choice must be a real taxonomy edge. Generated and absent
  parents say so with a reason.
- The artifact declares its layout semantics. A `hierarchy_containment` map
  emits one region per coordinate, each covering exactly its display subtree;
  root regions exactly match display-tree roots and do not overlap. A
  `similarity_first_non_containment` map cannot claim containment polygons. It
  instead emits one exact centroid per umbrella root, derived from its explicit
  display subtree, and the overview zoom level exposes every umbrella root.
- Zoom levels start at zero, are contiguous, retain all earlier visible nodes,
  and end with every node visible.
- Shown label boxes are checked at every zoom level. No more than 2% of desktop
  labels and 3% of mobile labels may touch another shown label.
- One-hop weighted-Jaccard neighbor recall is measured against a hashed source
  model over every mapped genre. The artifact records one hashed, variable
  eligible-candidate set for every query, including zero-source-neighbor rows,
  its source-neighbor count, and the versioned eligibility rule. Candidate and canonical spectral baseline must
  use the same source-model, neighbor, and eligible-set hashes. The random null
  is recomputed from those per-query pools, never supplied as an ungrounded
  global percentage. The candidate retains at least 98% of the baseline's
  null-adjusted top-10 quality and beats random by at least 0.15. Top-25 recall
  is reported for comparison but not substituted for the top-10 gate.
- The harness records screenshots for 1366 by 768 desktop and 390 by 844 mobile
  in system, light, and dark appearances. Each screenshot must exist at its
  recorded path with its recorded byte size and SHA-256.
- The interaction record passes drag/touch pan, wheel/pinch zoom, click detail,
  search state, browser back, keyboard focus, dark mode, and the no-JavaScript
  SVG fallback.

The report is intentionally renderer-neutral. The production model emits its
coordinates, hierarchy choices, LOD label decisions, and similarity evidence.
The renderer adds its screenshots and interaction record without inventing data
or geometry.
