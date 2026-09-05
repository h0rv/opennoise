# Public taxonomy expansion

This is a separate, non-replacing expansion of the 6,291 retained legacy genre
names through a CC0 public taxonomy snapshot. It reads only the sealed public
taxonomy artifact and selected catalog rows with row-level CC0, non-local,
export-permitted provenance. It does not read historical geometry, historical
memberships, historical neighbours, MusicBrainz research data, artist evidence,
ListenBrainz edges, audio, or music files.

Exact canonical and alias resolutions become factual identity links to public
catalog genre nodes. Direct public catalog hierarchy rows are factual links.
Compositional suffixes and ambiguous exact names are review-only links. They do
not assert parentage, artist membership, or an Every Noise relationship.

The build on 2026-09-04 used the sealed taxonomy artifact with logical hash
`45eea37c9acd311b3847fe60b5a6f7be111d3f01fc9a23e530c06c18c463b8cc` and
the matching public catalog hash
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`.
It produced logical hash
`e1a7d82a7c15008f5f7f0b0afff62a14d48ed284212b3f2dd0b91ff164133271` and
byte hash `774a7dc7c6705dadf726b9274d764b662cd673f746fd59b2f12b579cad8c4745`.
Two independently written outputs were byte-identical.

| Measure | Existing seed-only graph | Expansion factual-only | Expansion with review links |
| --- | ---: | ---: | ---: |
| Legacy seeds connected | 234 | 441 | 2,418 |
| Legacy seeds isolated | 6,057 | 5,850 | 3,873 |
| Components | 6,086 | 5,893 | 3,908 |

The existing graph’s review-enabled baseline had 1,118 connected and 5,173
isolated legacy seeds. The expansion’s review-enabled view therefore connects
1,300 additional legacy seeds and lowers isolated legacy seeds by 25.1%.

The expansion contains 746 row-level permitted public catalog nodes, 441 exact
identity edges, 853 deduplicated public taxonomy edges, 1,940 compositional
review edges, and 83 ambiguous-candidate review edges. It leaves 3,873 legacy
names as explicit abstentions. It infers zero artist memberships.

This is a navigation and evidence layer, not a completed reproduction of the
private Every Noise model. The next coverage gains need additional public,
provenance-gated signals or new human review, not promotion of review links.
