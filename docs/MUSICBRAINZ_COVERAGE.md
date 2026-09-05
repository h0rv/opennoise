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
Use `bridge-reconstruction-input` only after reviewing that artifact. Then run
`build-genre-peer-similarity` for symmetric candidates plus directional top-k,
and `evaluate-genre-peer-similarity-historical` as an H3-only evaluation.
Those commands take artifact and database paths from environment variables, so
v3 and v4 outputs can coexist.

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
