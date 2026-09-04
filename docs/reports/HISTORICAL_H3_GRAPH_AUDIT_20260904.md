# Historical H3 graph audit

## Verified facts

- The retained H3 graph receipt binds raw H3 SHA-256
  `863a513a6da89735a69373a46ba58f6975eddb5d065964c577dfcacf18fffe20`,
  derived SQLite SHA-256 `098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df`,
  and H2 manifest SHA-256
  `1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180`.
- The sealed SQLite has 306,136 displayable H3 memberships for 6,289 of
  6,291 H2 genres and 240,007 artists. `kumaoni pop` and
  `talentkonkurrence` have no H3 membership.
- The graph uses IDF-weighted Jaccard for directed top-20 nearest neighbors.
  It has 65,343 directed edges: 27,826 reciprocal pairs, 9,691 one-way edges,
  and an 85.169% reciprocal-directed-edge fraction.
- Symmetrizing directed edges with their maximum weight produces 167 connected
  components: one 6,099-node component, 18 components of two to four nodes,
  and 148 isolates.
- The configured artist hub cutoff of 32 has no effect: the observed maximum
  artist genre-degree is 13. Cutoffs of 8, 4, and 2 exclude 655, 11,734, and
  48,168 memberships respectively; cutoff 2 raises fragmentation to 233
  components and 204 isolates.
- Local nearest-neighbor checks are plausible: pop to dance pop, rock to
  permanent wave, hip hop to pop rap, jazz to bebop, EDM to pop dance, and
  black metal to death metal.
- The displayable artist reverse index works without audio and labels its
  result `derived_partial`. The published map has no artist ID/name, preview,
  sample, or track fields.
- H2 coordinates are excluded from candidate generation and layout fitting.
  H2 names map the retained genre identities, and H2 coordinates remain in the
  post-fit evaluation payload and therefore affect the enclosing artifact hash.

## Release blockers

### P0: deterministic rebuild and artifact replacement

The old published graph was not reproducible across independent processes.
Hash-random iteration of artist membership sets changed floating-point
reduction order and near-tied top-20 boundaries. The deterministic ordering fix
is covered by subprocess tests using distinct `PYTHONHASHSEED` values. Two full
independent local rebuilds now have identical bytes
(`5a8cbe45d94b81ed1a4b27102fec946e6fd9077682f8a7df75924a9f0616a508`) and
internal artifact hash
`752b60ccb11adb6961eda3b0e70dd338d06bcbf72966aced22524c0e5289be88`.

Rebuild and reseal the published map with the fixed code. Do not overwrite the
old artifact or claim its exact reproduction.

### P0: retained-input custody

The raw H3 JSON and derived SQLite currently exist only under
`.worktrees/final-integration/.cache`. Store each through `LocalObjectStore`
under content-addressed keys and bind their hashes, H2 manifest hash, policy
key, settings, and rebuild command in a receipt. Do not commit either blob.

### P1: overview community claims

The 24 overview communities are not a graph hierarchy or weighted label
propagation result. The implementation chooses high-degree seeds and assigns
nodes by embedding distance; `label_propagation_iterations` is unused, despite
the model documentation saying weighted label propagation. Seventeen of 24
groups have less than 80% of their nodes in the largest internal component,
including album rock (21/76), sertanejo universitario (40/179), and mande pop
(77/216). Rename or qualify these as viewport overview groups until a coherent
community method and fragmentation gate exist.

### P1: identity normalization contract

Ingestion uses casefold only, the signal model uses casefold plus whitespace
folding, and historical compatibility uses NFKC plus casefold and whitespace
folding. Current retained names have no collisions under either tested form,
but the contract is inconsistent. Use one Unicode normalization function for
ingest and model identity matching and add Unicode-variant regression cases.
