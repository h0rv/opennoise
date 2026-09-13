# Semantic map layout

`semantic-map-layout-v1` is a renderer-neutral, local research artifact for a
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
Focused navigation uses the exact edge ledger, not inferred screen distance.

`communities` are bounded renderer LOD regions, not taxonomic claims. Each has
a real `anchor_seed_id`; only `overview_visible` anchors are labelled at LOD 0.
The coordinate parent/root/depth chain remains the taxonomy navigation model.

Run it against the currently sealed inputs:

```sh
uv run python scripts/build_semantic_map_layout.py \
  --peer-index .cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite \
  --peer-manifold-artifact .cache/musicbrainz-full-seed-targets/pipeline/peer-community-layout-v1.json \
  --hierarchy-artifact .cache/hierarchy-fusion-v1/artifact.json \
  --colisten-artifact .cache/genre-colisten-neighborhoods-v1/32017c0a2cff27485671151663dfc9f184e8b2f9e354ba73d712e3ca8140b141/artifact.json \
  --colisten-cache .cache/genre-colisten-neighborhoods-v1/32017c0a2cff27485671151663dfc9f184e8b2f9e354ba73d712e3ca8140b141/genre-neighborhoods.sqlite \
  --output .cache/semantic-map-layout-v1/artifact.json
```

The static renderer should fit the declared landscape world rather than raw
point extrema, draw only overview labels at first, and reveal genre and peer
detail as the camera zooms. It must not treat a coordinate as proof of a
taxonomy edge or manufacture a coordinate for an unplaced seed.
