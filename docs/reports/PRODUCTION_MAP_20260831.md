# Production map v1

## Result

`production-map-v1` is a single Cytoscape-ready public graph, not a set of
product lenses. It uses qualified Wikidata genre identities and direct `P279`
taxonomy claims, direct artist membership, and the already privacy-safe public
one-hop weighted-Jaccard co-listen graph. It contains no audio inputs, Every
Noise observations, or inferred/fuzzy genre labels.

The implementation keeps the full qualified taxonomy DAG as `taxonomy` edges.
`display_parent_id` is a separately marked, versioned presentation subset and
must never be treated as canonical taxonomy. A deterministic rule considers
every direct `P279` candidate in order of: one-hop similarity, shared artists,
the candidate's direct artist coverage, and ID. It rejects the first candidate
that would close a display-tree cycle. The explanation payload records every
candidate, its evidence, the selected parent, the root path, community, LOD
reason, and placement method.

## Qualified-run evidence and current decision

The builder was run against the ignored but audit-inspected qualified Phase 3
SQLite database and the matching public model artifact:

- Source model input SHA-256: `70c5c40f6206eb3895203e61864b62cf361532d02c1c61535281f22ce5fced6e`
- Source model output SHA-256: `e327045074fc6bb4e3b2e1c14410b3f337b6822e048c6038aa18703a11d2108b`
- Exploratory top-10 output SHA-256: `8ea856d8f9d01b3c74e542f50248955a24dd193f2f1d029f9bf4fa52ac1a0ef0`
- Exploratory top-10 coordinate SHA-256: `6f32a0ea57cb42d68eb82aa28cb6a56bf0b993bb079825b004b44d830cb40f0c`
- Exploratory top-25 output SHA-256: `68c660cc98fdf532b1b5b8cdb9a911407e26f66bcc7eacaed9356afcfc328b6e`
- Exploratory top-25 coordinate SHA-256: `1cf26496e68df70ea36b51a7cec9ff0f3ed4407f0a41bd96b8e9303eb93b0c15`

The hierarchy source has 603 nodes, 712 direct DAG edges, and 107 display-tree
roots. The local force variant improves the sibling-seriation candidate but is
still a Pareto measurement, not a release: it has central-90% spans of
`0.862225610792` x and `0.652353269313` y, 57.5% occupied 20 by 20 cells,
zero root overlap, exact hierarchy containment, 64.58% occupied cells in the
QA 16 by 9 desktop grid, and a 3.48% densest-cell fraction. Its exact
603-node/reference-hash top-10 neighbor preservation is only
`0.158785391387`; top-25 is `0.168732605067`. The independently validated
one-hop spectral baseline is `0.5173`.

The production setting therefore requires at least `0.30` top-10 neighbor
preservation before export. Both exploratory hierarchy-packed artifacts fail
closed, are deliberately not published, and require a local similarity-aware
layout/packing revision plus product review. The exact rerun hash is still
recorded in every artifact. There is no prior production baseline, so temporal
comparison remains explicitly `not_supplied`, not silently reported as
stability.

## Layout and LOD contract

The map packs actual display-tree roots, then recursively packs their children
inside the parent rectangle. It is therefore component-safe and hierarchy-safe,
without global spectral coordinate min/max normalization. Similarity communities
are seeded deterministic weighted-label-propagation groups used to order and
explain root packing; they cannot create taxonomy edges.

Nodes have a normalized `region`, normalized centre (`x`, `y`),
`position_region`, `display_parent_id`, `root_id`, `depth`, `community_id`,
and `lod_min`. `region` is the nested taxonomy compound rectangle;
`position_region` is the stable umbrella bound for local force placement.
The renderer shows a node at `active_lod >= lod_min`, preserving every prior
selection as zoom increases. The qualified run has 116 overview, 134 middle,
210 near, and 603 close labels. It renders umbrella genres first, genres next,
then subgenres and deeper descendants.

The artifact additionally emits all four ordered LOD node sets and predicted
desktop (1440 by 900) and mobile (390 by 844) label boxes. Each label has an
exportable `shown`, `collision`, or `budget` decision, so QA and the renderer
can derive exactly the same collision-free shown-label list without heuristic
inference. The LOD validator makes node inclusion monotonic.

The selection policy adapts the relevant part of Hackerverse's map builder:
each level doubles the axis grid (2, 4, 8, 16), retains previously selected
nodes, and admits candidates round-robin across occupied cells before a dense
cell receives another node. That prevents electronic or hip-hop density from
hiding sparse regions. This project does **not** copy Hackerverse's embedding
or terrain pipeline. Reference: [Hackerverse build-map main.py](https://github.com/wilsonzlin/hackerverse/blob/master/build-map/main.py).

Electronic music is explicitly audited: the direct taxonomy DAG at Wikidata
`Q9778` has 61 nodes and 62 edges; the current deterministic display tree has
56 placed descendants, six direct display children, and a maximum depth of
four.
The builder fails closed if an Electronic music umbrella is missing or is not
multi-level.

## Completion-audit blocker status

| Prior blocker | Production-map status |
| --- | --- |
| Old release task omitted Phase 3 inputs | The builder verifies the source model input hash and can run from the sealed Phase 3 release database; release orchestration remains an integration task. |
| Profiles/neighbors not persisted or served | The artifact now emits profiles, ranked public neighbors, direct/propagated coverage, and evidence references. Database/API persistence remains with the serving integration. |
| Four layout lenses were exposed as product UI | This artifact is exactly one map; the renderer contract has no lens switcher. |
| Search/lens state defect | Out of scope for the data artifact; the renderer receives one stable map state. |
| Application test hang and connections | Not changed here; remains a release blocker. |
| Historical reproduction coexisting with successor | Deliberately out of this successor artifact; no historical data is mixed in. |

## Reproduction

```bash
PYTHONPATH=src python scripts/build_production_map.py \
  --database data/phase3-public-qualified.sqlite \
  --source-model data/model/phase3-public-qualified-model.json \
  --output data/model/production-map-v1.json
```

The source-model hash equality check is intentional: a map cannot be built
from a database whose qualified inputs differ from the evidence used to make
the supplied public model.
