# Consensus semantic projection

This local-only artifact places only the 958 eligible genres from the sealed
consensus micro-neighborhood audit. It uses the 2,490 stable peer pairs and
only accepted exact-QID factual taxonomy relations whose endpoints are both
eligible. It does not read historical coordinates, historical memberships,
historical neighbors, artists, listening data, or audio.

It reuses the existing deterministic weighted community spectral layout with
stable-pair frequencies as weights and a weight of one for eligible factual
taxonomy links. The layout packs its deterministic layout communities,
but preserves weighted local distances within each component. Input edges stay
in the artifact even when a community-packing cut places their endpoints in
separate layout components. Its artifact
records community convergence, top-10 neighbor retention, mutual-neighbor
fraction, and weighted mean edge distance. Singleton fallbacks are not used:
every placed node has consensus evidence.

The artifact carries all 5,333 consensus abstentions as explicit unplaced rows.
An abstention is not a negative semantic assertion and never receives a fake
coordinate. The fixed LOD budgets of 48, 240, 480, and 958 rank only placed
eligible nodes.

With the currently sealed inputs, the replay covers all 6,291 names as 958
placed eligible rows and 5,333 explicit unplaced abstentions. It retains 2,490
stable peer edges and 151 eligible factual taxonomy edges in 220 layout
components. The consensus input binds bytes/logical hashes
`0dadb65459588c3e756337ef2c3a78fd47c7f21ef60ff1e7f6fc85c83280bd92` /
`bee052532e10d903c97bf847c78222e0a4fa6e1efc1096032491222fda068c02`; the
taxonomy input binds
`26184620c20be59c1617840ddcec9377aa86951d54f91d6ecbd41c78618d3f68` /
`21126aae5cf8b849edd132e9125ad12f1037474fecc1f89f6b8c1f8254efbd15`.
The replay artifact is byte-hash
`990ac3a801e8e393e2c100c776e7df4758e4d0b23055f476b2b6f64970fa1601` and
logical-hash `6a749060988b7ced05199db28c6b122fe69e0ca9c8fcdf441b3a1857aa6b59ca`.
Its 2,607 weighted input edges yield 2,458 packed layout edges, KNN@10
preservation 0.834725950227, mutual-neighbor fraction 0.865714285714, mean
weighted edge distance 0.037367460714, and four converged iterations. This is
coverage accounting, not a claim of historical-map parity.

```bash
uv run python scripts/build_consensus_semantic_projection.py \
  --consensus .cache/release-group-support-peer-v3/consensus-micro-neighborhoods-v2.json \
  --exact-qid-taxonomy .cache/taxonomy-relation-expansion-v3-replay-candidate/artifact.json \
  --output .cache/consensus-semantic-projection-v1.json
```
