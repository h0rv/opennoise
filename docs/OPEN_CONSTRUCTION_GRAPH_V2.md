# Open construction graph v2

`open-construction-graph-v2` is an Open serving artifact built only from a
verified `public-taxonomy-expansion-v1` artifact. It is not a historical-map
reconstruction, a listening graph, or an artist-membership model. It retains
all 6,291 legacy name seeds plus the explicitly typed public catalog nodes
needed to preserve their factual and review connectivity. It uses an
independent deterministic landscape and hierarchy layout.

The verified 2026-09-04 build contains 7,037 total nodes: 6,291 retained
legacy names and 746 public catalog anchors. Exact hashes and coverage are in
[`OPEN_CONSTRUCTION_GRAPH_V2_20260904.md`](reports/OPEN_CONSTRUCTION_GRAPH_V2_20260904.md).

Direct catalog identity and hierarchy edges remain factual with their distinct
`canonical_catalog_identity` and `public_catalog_taxonomy_parent` kinds.
Compositional and ambiguous links remain respectively
`compositional_review_anchor` and `ambiguous_identity_review_candidate`, both
carrying `factual_relationship: false` and `review_candidate: true`. No review
link is promoted to taxonomy fact or artist membership.

The v2 graph does not read historical coordinates, historical neighbours,
historical memberships, artist evidence, aggregate listening data, audio, or
music files. Its input audit and gate record these exclusions. The gate also
requires all configured legacy seeds, deterministic replay, and a verified
taxonomy expansion before publication.

## Reproducible build

The expansion is an explicit retained input. The command never scans `.cache`
or guesses a source path, so a fresh checkout either builds from an explicitly
provided expansion artifact or fails before writing output.

```sh
uv run poe build-public-taxonomy-expansion
uv run poe build-open-construction-graph-v2
```

The second command writes the graph and an immutable `LocalObjectStore` copy.
Its receipt contains the byte hash, content-addressed object key, logical hash,
and fail-closed gate. Do not commit a full derived v2 graph just to enable the
server; set `MUSIX_OPEN_CONSTRUCTION_GRAPH_V2_PATH` to the retained, verified
artifact path instead.

## Serving and migration

`/api/open-construction-map` and `/api/open-construction-map/neighbors/{id}`
remain v1. The v2 paths are `/api/open-construction-map/v2` and
`/api/open-construction-map/v2/neighbors/{id}`. They are disabled unless
`MUSIX_OPEN_CONSTRUCTION_GRAPH_V2_PATH` is explicitly configured. An absent
configuration returns unavailable. A configured unreadable, malformed, or
failed-gate artifact fails application startup; neither case falls back to v1.
Every response is limited to one of the declared LOD budgets (240, 480, 720,
or 720 nodes), at most 512 edges, and at most 24 edges for a one-hop drill.
