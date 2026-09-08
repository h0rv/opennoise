# Local research evidence layout

`local-research-peer-layout-v1` is a local-only projection of the sealed
MusicBrainz peer-candidate index. It is never an input to the public model,
production map, Open construction map, or serving API.

The adapter reads a compact SQLite index with all 6,291 retained seed identities
and canonical weighted peer-candidate pairs. A seed receives a coordinate only
when it is an endpoint of a positive, receipt-bound peer edge. All other seeds
are emitted as `no_peer_similarity_evidence`. This is a complete partition, so
an absent coordinate is visible rather than replaced by a grid, taxonomy, or
hash position.

The baseline uses the existing deterministic normalized-Laplacian spectral
builder. The separate community artifact uses the existing seeded,
community-packed spectral lens: community-retained edges determine coordinates,
but its quality check still uses every receipt-bound source peer edge. Its edge
scores are interpreted as canonical undirected candidate pairs. The artifact
records the index byte hash, sealed peer artifact hash, settings, a
same-SciPy-runtime rerun hash, and same-edge k-nearest-neighbor preservation. Symmetric graphs
can have degenerate spectral eigenspaces, so this is not a cross-runtime byte
determinism claim. It does not read historical
coordinates, historical neighbors, audio, or music files.

Current local-research measurement at k=10: the normalized spectral baseline
preserves `0.033364225437` of the original 28,508-edge peer neighborhoods;
the seeded community-packed variant preserves `0.186309523810`. The latter
uses 20,214 intra-community edges for placement but is evaluated against all
28,508 source edges. This is a projection-fidelity comparison, not a quality
threshold, ground-truth semantic claim, or public-model promotion.

The current exportable 603-node production map is a different contract. Its
source public lens has 468 evidence-placed genres and 135 explicit
`no_direct_membership` entries. `production-map-v1` nevertheless gives all 603
nodes display positions by seeding those 135 unresolved IDs in a deterministic
grid before global repulsion. Those 135 positions are navigation/readability
placement, not evidence-derived similarity, and must not be reused as support
for an own-numbers similarity claim.

Run the local artifact only with an explicit retained index:

```sh
uv run python scripts/build_local_research_peer_layout.py \
  --index .cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite \
  --output .cache/musicbrainz-full-seed-targets/pipeline/peer-spectral-layout-v1.json
```
