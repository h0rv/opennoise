# Open construction graph build, 2026-09-04

The retained `open-construction-graph-v1` artifact contains every 6,291 legacy
name seed. Its logical SHA-256 is
`9c080faae48db9270b4d8546bec003a90b62cd764ee6e233ed2b3a47f10d1957`; the
canonical written JSON SHA-256 is
`94c7a5b3374e17e78aed8c7390e547235e06c041c9d51d803a77cb5d1e4a1d6f`
(5,855,841 bytes). The committed retained copy is
`data/model/open-construction-graph-v1.json`, with a receipt and gate report
alongside it.

Construction projected the retained source to name, source item ID, external
ID, source ID, and source hash. It used the newly built CC0 taxonomy-anchor
artifact (`45eea37c9acd311b3847fe60b5a6f7be111d3f01fc9a23e530c06c18c463b8cc`)
and the matching CC0 public catalog. It did not read historical geometry,
neighbours, artists, H3, or supplementary MusicBrainz genre data.

| Measure | Count |
| --- | ---: |
| Nodes / seeds | 6,291 |
| Edges | 1,059 |
| Direct public taxonomy edges | 216 |
| Lexical review-anchor edges | 843 |
| Components | 5,243 |
| Isolated nodes | 5,173 |
| Nodes in factual taxonomy hierarchy | 234 |
| Review-anchored nodes | 843 |
| Abstained nodes | 3,539 |
| Ambiguous nodes | 371 |
| Generic-token rejections | 1 |
| Review hub-cap rejections | 794 |
| Inferred memberships | 0 |

A deterministic replay produced the same logical hash and reused the immutable
object-store key. This graph is deliberately sparse: the public catalog only
resolved 441 canonical/alias seed identities, and most compositional anchors
either have no uniquely resolved in-vocabulary target or exceed the cap. Those
nodes remain isolated rather than receiving guessed edges. Review anchors are
not factual parentage, memberships, similarity, or evidence about artists.
