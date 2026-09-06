# MusicBrainz artist genre coverage

The coverage evaluator compares one pinned MusicBrainz artist snapshot with the
6,291 retained Every Noise seed names. It reads only seed IDs and names.
Historical Every Noise coordinates, memberships, representatives, and ordering
are not evaluator or reconstruction inputs.

Run it with explicit paths after the research import. The example uses the
current v4 research run; another snapshot only needs different values:

```bash
export MUSIX_MB_RESEARCH_DATABASE=.cache/musicbrainz-v4-research/musicbrainz-v4.sqlite
export MUSIX_MB_SOURCE_KEY=musicbrainz_json_artist_research_20260829
export MUSIX_SEED_DATABASE=data/musix.sqlite
export MUSIX_MB_COVERAGE=.cache/musicbrainz-v4-research/coverage.json
export MUSIX_RECONSTRUCTION_INPUTS=.cache/musicbrainz-v4-research/reconstruction-inputs.json
export MUSIX_MB_BASELINE_REPORT=.cache/musicbrainz-v4-research/baseline.json
uv run poe evaluate-musicbrainz-coverage
```

`MUSIX_H2_SEED_ARTIFACT` is required by the identity and reconciliation
stages. Set it to the path of an immutable retained Every Noise seed artifact
before running those stages. No seed artifact is checked into this checkout,
so the Poe tasks fail immediately when that value is empty.

The task writes ignored JSON artifacts under the paths supplied above.
`coverage.json` records exact and
normalized label matches, positive direct artist evidence, evidence weights,
unmatched seed names, and runtime. Normalized matching applies NFKD,
casefolding, combining-mark removal, punctuation-to-space conversion, and
space collapsing. Coverage JSON retains separate `genre` and `tag` facet metrics
and marks each match with its facet; aggregate fields remain available for
backward-compatible summaries.

The next stages are explicit and can be run independently:

```bash
export MUSIX_GENRE_SEED_PUBLIC_TAXONOMY_OUTPUT=.worktrees/open-construction-graph/data/model/genre-seed-public-taxonomy-v1.json
export MUSIX_MB_SEED_IDENTITIES=.cache/musicbrainz-v4-research/seed-identities.json
export MUSIX_SEED_RECONCILIATION_OUTPUT=.cache/musicbrainz-v4-research/seed-reconciliation.json
export MUSIX_RECONSTRUCTION_OBJECT_STORE=.cache/musicbrainz-v4-research/objects
uv run poe build-musicbrainz-seed-identities
uv run poe reconcile-genre-seeds
```

`reconcile-genre-seeds` emits one disposition for every seed. Review,
ambiguous, and unresolved names remain visible and are never silently promoted.
Reconciliation v3 treats one exact MusicBrainz genre UUID and one exact
MusicBrainz tag name as corroborating facets for the same stable seed, not as
two competing candidates. Multiple identifiers in the same source facet, or
one exact source identity claimed by multiple stable seeds, remain ambiguous.
Use `bridge-reconstruction-input` only after reviewing that artifact. Then run
`build-genre-peer-similarity` for symmetric candidates plus directional top-k,
and `evaluate-genre-peer-similarity-historical` as an H3-only evaluation.
Those commands take artifact and database paths from environment variables, so
v3 and v4 outputs can coexist.

The prefix reconnaissance reconciliation and a full artist-dump extraction
answer different questions. Reconciliation records which stable seed identities
were found in its smaller input. The full dump records direct artist evidence
for every matching seed name. The all-seed frontier v3 preserves both counts:
`reconciliation_musicbrainz_identity_seed_count` is the reconnaissance count;
`observed_musicbrainz_seed_count` is the full-corpus direct-evidence count.
Neither count is substituted for the other. The sealed full run measured the
second value as 2,377. Its adapter report is
`b14214bbca792a9cb877d0b6760c886d5f01d3783ac93ce667e0b4a4eb53a79b`.
That report binds the full target artifact, reconciliation artifact, both
original seed-wrapper hashes, H2 source ID and content hash, and canonical
stable seed identity fingerprint.
For a high-volume seed, the model keeps a bounded genre-level provenance
reference that commits to the complete direct-evidence set by hash. Individual
membership rows remain linked to their own source evidence; the complete set is
not discarded to satisfy a display-field size limit.

## Full-corpus graph checkpoint

The full-corpus checkpoint sealed a public hierarchy-candidate artifact from
the current reconciliation (`842a2b…`), taxonomy (`45eea…`), and model input
(`ddc5…`). Its logical hash is
`fc224da42842cdd0a4a9b5628d015cf83d60266b609857dcdff96abe01f7f02a`; the
publication receipt and content-addressed object agree on the byte hash
`b702d6e78d5f94c04dd4adfef4314ed02538b92a6042140ee8a35768ae712a8a` for
683,580,146 bytes. It retains 6,291 seed coverage rows and 66,132 directed
candidates: 160 accepted, 59,911 review, and 6,061 abstained. The hierarchy is
a public evidence candidate layer; it does not inherit parent artist
memberships into children and does not use historical data in construction.

The all-seed evidence frontier is now published from the exact CC0 public
catalog snapshot bound into taxonomy `45eea…`: database byte hash
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`.
It has logical hash
`8b17de7f4ad31ee8f49b1e36b006ff5f35e32510ab26533943d751ff5f775194` and
byte hash `274cd2ac29cd44609dfdf571014eac97da7a904dc0a422036f8b0a754d48b46d`.
The restored snapshot is at
`.cache/catalog-snapshots/sha256/240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc.sqlite`.
Its receipt binds the retained local source path, both byte hashes, size, and
the expected taxonomy hash. The current hydrated descendant remains separate
at `.cache/musicbrainz-20-catalog/public.sqlite` with hash
`31b342e11a03fcfabca6a8e639f96e9250ef7cfb06b4e615608a6445e9b15b7c`.
The restore command refuses a source hash mismatch before replacing a
destination, so no provenance gate is weakened.

## Historical H3 peer evaluation

The sealed full peer component is evaluated only after construction against
the immutable H3 snapshot. The evaluation report file hash is
`5ea0ccdf2f795e2ce66d2058abbe5eebee9650e4fbfd9d7ea6efd4434f9b8c91`;
its logical report hash is
`91c2f2dedc6d83ba7423eb8e401ba749b97c21a19e4ade5ace1ba0911b848724`.
It binds candidate logical hash `15ce7a…`, public catalog hash `31b342e…`,
and historical database hash `098dc878…`.

The evaluator records `historical_inputs_used_for_construction=false` and
`absence_is_negative=false`. H3 supplies 306,136 unranked positive
observations; only 3,630 have a unique public artist-name crosswalk, so this
is a neighborhood-compatibility check rather than membership recall. At 25
neighbors it matches 1,684 historical directed links: micro precision is
0.08604 and recall is 0.25358, versus null precision 0.000804 and recall
0.002370. It covers 1,580 candidate-neighborhood genres and preserves 4,709
matched genres without candidates as abstentions. It is not a claim of a
complete Every Noise reconstruction or ranked historical ground truth.

The optional reconstruction artifact contains only direct positive
MusicBrainz artist-to-genre evidence for matched seed names. It is a typed
`ReconstructionInputs` document with a content hash. The baseline report runs
weighted Jaccard and weighted cosine similarity with ten neighbors and records
genre, pair, edge, and artist counts. No historical points or neighbors are
attached.

The imported archive is local noncommercial research data. MusicBrainz core
identity fields are CC0, while genre associations are supplementary
CC-BY-NC-SA-3.0 data. The stored policy permits local normalization, search,
display, embedding, and training, but denies metadata export, raw export, and
redistribution. Coverage and baseline outputs remain local and are not
public-exportable without a separate rights review, attribution, and
ShareAlike decision.
