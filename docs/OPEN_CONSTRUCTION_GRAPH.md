# Open construction graph

`open-construction-graph-v1` retains every one of the 6,291 legacy genre name
seeds as a node. It is a separately built public navigation graph, not a
reconstruction of the historical map and not an artist-membership model.

The builder projects the seed source to source ID, source hash, source item ID,
external ID, and name. It then accepts only the typed CC0 public taxonomy-anchor
artifact and the CC0 catalog's taxonomy identity and direct hierarchy tables.
It never reads coordinates, neighbours, artist assignments, H3, or supplementary
MusicBrainz genre data. The artifact's input audit records that boundary and the
publication gate verifies it again.

Direct public catalog parent relations produce `public_taxonomy_parent` edges
only when both catalog identities resolve to exactly one seed. They are the only
factual hierarchy edges. A unique compositional anchor can produce a
`lexical_review_anchor`, which is confidence-scored but carries
`factual_relationship: false` and `review_candidate: true`; it never becomes a
membership or a hierarchy parent. Ambiguity and isolation are intentional
outcomes. Generic morphology (`music`, `genre`, `sound`, and `style`) is not
used, and review-anchor fan-out is capped deterministically.

Each edge contains source hashes, public catalog IDs, relation IDs or lexical
modifier, and a human-readable note. The artifact also contains components,
coverage/ambiguity diagnostics, and a deterministic landscape plus an
independent DAG hierarchy layout. Neither layout uses historical coordinates.

```sh
uv run poe build-genre-seed-public-taxonomy
uv run poe build-open-construction-graph
```

The second command writes an immutable object-store copy, a receipt, and a
fail-closed gate report. Re-running with byte-identical inputs must reproduce
the logical output hash and layout exactly.
