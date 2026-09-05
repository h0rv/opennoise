# Genre seed universe report

Build date: 2026-09-04

The name-only bridge was run against the retained H2 compatibility artifact
and the certified public release cache for
`phase3-public-20260831-qualified`. The active MusicBrainz v3 research
database was not opened.

Inputs:

- H2 source ID: `enao_quint_legacy_map_2025`
- H2 source content SHA-256:
  `1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180`
- H2 name-only projection SHA-256:
  `915835e1391b065d41f437159b6bc114e39e341029fe54b133f52c7a464e2e8d`
- Public catalog cache SHA-256:
  `c2f3168d450034ac2ec98c3a0f44c71baa4cba2836995a05eda670ba22d11cc5`

Results:

| Classification | Count |
| --- | ---: |
| `direct_exact` | 307 |
| `alias_exact` | 134 |
| `compositional_candidate` | 2,274 |
| `ambiguous` | 37 |
| `unresolved` | 3,539 |
| Total seeds | 6,291 |

There are 441 canonical memberships with 4,311 direct positive evidence rows.
Compositional candidates carry no evidence or canonical membership. Ambiguous
labels retain every exact identity candidate without fuzzy ranking. The
deterministic logical artifact hash is
`6a8871388552beb66fec0ee0b9a4ef6eb475f3af3bebb0fcb0ed7dc0342ec2a9`.
