# Semantic map layout

`semantic-map-layout-v3` is the selected renderer-neutral, local research artifact for a
16:9 landscape map. Its coordinates mean public structural proximity from
genre-peer evidence, privacy-safe aggregate co-listens, and the factual plus
review hierarchy. They are not bounciness or organism axes, and they do not
reuse historical coordinates, neighbors, or memberships.

The immutable 6,291 seed IDs remain the boundary. A seed is positioned only
when it participates in at least one positive structural relation. Every other
seed is present in `unplaced` with `no_supported_structural_relation`; there is
no grid, hash, random, or taxonomy-only fallback position.

The builder verifies the peer index, sealed peer-only manifold, hierarchy
artifact, co-listen artifact, and co-listen SQLite cache before use. It keeps
peer structure as the 2D source of truth, then applies a deterministic monotone
readability transform so one dense source component cannot consume the screen.
Hierarchy and co-listen-only names attach at deeper LOD near evidenced parents.
After that placement, a bounded deterministic pass pulls each positioned node
toward only its observed confidence-weighted edges while anchoring it to the
peer atlas. This improves local edge readability without inventing relations.
Focused navigation uses the exact edge ledger, not inferred screen distance.

`raw_confidence_weighted_structural_edge_distance` and
`raw_structural_edge_distance_p95` are raw 16:9 world-coordinate distances and
are useful only for comparing layouts with the same world policy.
`mean_hierarchy_endpoint_distance` instead normalizes horizontal distance by
world width, so its numeric values are intentionally not comparable to the raw
structural metrics.

`communities` are bounded renderer LOD regions, not taxonomic claims. Each has
a real `anchor_seed_id`; only `overview_visible` anchors are labelled at LOD 0.
The coordinate parent/root/depth chain remains the taxonomy navigation model.

Run it against the currently sealed inputs:

```sh
uv run poe rebuild-semantic-map-layout
```

Earlier artifacts are deliberately not migrated: they encode older coordinates and
settings digests. Rebuild v3 from its sealed inputs, then run
`uv run poe rebuild-certify-semantic-pages` to rebuild and browser-certify the
static Pages directory in one sequence.

The static renderer should fit the declared landscape world rather than raw
point extrema, draw only overview labels at first, and reveal genre and peer
detail as the camera zooms. It must not treat a coordinate as proof of a
taxonomy edge or manufacture a coordinate for an unplaced seed.
