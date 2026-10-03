# Reproducible foundation

The [end-to-end acceptance contract](ACCEPTANCE.md) and its byte-bound dossier
separately report the twelve full-foundation gates. Input availability in this
inventory establishes stage readiness; it does not establish musical validity
or Every Noise parity.

The checkout contains source code and some small checked-in model artifacts.
It does not contain every source snapshot, research cache, sealed release input,
or a complete Every Noise replacement. Run the direct inventory command to see
what this checkout can run now:

```sh
.venv/bin/python scripts/foundation_manifest.py plan
.venv/bin/python scripts/foundation_manifest.py validate --json
.venv/bin/python scripts/foundation_manifest.py validate --stage portable-examples
```

Pass `--root /path/to/checkout` to inspect another checkout. `plan` shows the
declared stages and missing inputs; `validate` exits 1 when one or more selected
stage dependencies are missing. Use `--stage` to check portable examples without
requiring absent full-corpus or canonical-release inputs. Both commands validate the manifest schema and
refuse symlinked paths. Output hashes bind each declared input file's bytes and
each stage's declaration plus those file hashes. Inputs must be files; a directory
cannot stand in for a missing receipt. Hashing a receipt does not verify every
underlying dataset member: use its source-specific offline replay for that check.
A new independently named [portable CC0 build](OPEN_BUILD.md) replays retained
native source responses into SQLite, an explicitly nonsemantic browsing layout
and a small static explorer. It covers 150 selected exact artists and preserves
missing evidence; it does not reconstruct or impersonate the missing canonical
release or satisfy full Every Noise acceptance.

The versioned inventory lives in
`src/opennoise/pipeline/foundation.py` and is intentionally not a general task
runner.

The newer [full-input reconstruction](FULL_INPUT_RECONSTRUCTION.md) follows a
separately named contract for the retained open source packs. Its independently
replayed v8 export covers 2,999,670 exact identities, complete indexes and
observed genre cohorts, with FMA contexts in a separate namespace. The
[current evidence](CONTINUATION_PROGRESS_20261003_V8.md) records one engineering
reconstruction pass and eleven unmet acceptance gates. The full source packs
must be recovered separately; this is not a fresh-checkout full website or a
musical parity claim.

The [FMA source-membership text recipe](../../data/recipes/fma-source-memberships-v1/README.md)
is self-contained with the existing acoustic baseline. It reconstructs the exact
nine-file model example, including all 13,800 saved queries, into a new directory:

```sh
.venv/bin/python scripts/materialize_fma_membership_example.py \
  --output /tmp/fma-source-memberships-v1
PYTHONPATH=src .venv/bin/python scripts/replay_fma_memberships.py \
  --saved-pack data/examples/fma-acoustic-baseline \
  --memberships /tmp/fma-source-memberships-v1
```

This replays saved source ranks, thresholds and metrics; it does not refit from
native FMA files or establish musical membership. The original binary example
is retained in private recovery storage. The public text recipe preserves its
exact decoded bytes and attribution. Historical evidence copies referring to a
tracked binary pack describe the local example before this publication route.

`poe sync && poe check` is the clean-checkout baseline. `poe build` also needs
`data/public.sqlite` and `.cache/semantic-map-layout-v3/artifact.json`; the
ignored files must be supplied locally. The parity comparison additionally
uses a pinned historical Every Noise snapshot through `poe bootstrap`. That
snapshot is a dated evaluation reference, never a model or serving input.

Research recipes and their measured limits are recorded in
[`EVERYNOISE_PARITY.md`](../EVERYNOISE_PARITY.md) and the linked checkpoints.
For example, the source-only explorer recipe is in
[`SOURCE_MODEL_UI_BATCH_20260930.md`](../checkpoints/SOURCE_MODEL_UI_BATCH_20260930.md).
Those commands require source snapshots and caches that a fresh clone does not
have. Run builders with new `.cache` output paths; completed candidates are not
overwritten.

Two smaller, self-contained projections make source-role examples runnable in
a fresh checkout. The numeric-only acoustic sample contains artist-level
descriptor summaries and source hashes, with no raw tags, audio, or cultural
neighborhoods:

```sh
.venv/bin/python scripts/demo_acoustic_descriptors.py
```

The credited-work sample contains exact artist credits, bounded recording and
release-group examples, and a receipt that hashes the projection. Replay its
transparent ranking into a local output file with:

```sh
.venv/bin/python scripts/rerank_projected_artist_work_examples.py \
  data/examples/representative-music/credited-examples.json \
  --receipt data/examples/representative-music/receipt.json \
  --output .cache/foundation-demo/representative-music.json
```

Both are examples of metadata provenance and local replay. They do not claim
musical similarity or complete Every Noise parity.

The independent CC0 cultural-context example replays retained Wikidata responses
for 110 requested artists, including all ten exact benchmark identities. Its
portable manifest excludes supplementary MusicBrainz genre claims used only to
select the research cohort. The artist-link example separately verifies outbound
listening destinations from exact MusicBrainz URL relationships:

```sh
.venv/bin/python scripts/probe_open_cultural_sources.py \
  --verify-pack --pack-output data/examples/cultural-context
.venv/bin/python scripts/probe_open_cultural_sources.py \
  --demo --pack-output data/examples/cultural-context
.venv/bin/python scripts/verify_artist_outbound_links.py data/examples/artist-links
```

These commands perform no network requests. Raw-response replay distinguishes
receipt presence from verified data custody. Property-specific overlap scores
are source metadata comparisons, and outbound links do not guarantee provider
availability. The inventory exposes `portable-cultural-context` and
`portable-listening-links` as individually checkable stages.

License classes remain explicit. MusicBrainz identity, names, and core
metadata are CC0. MusicBrainz tag and genre-association packs carry
CC-BY-NC-SA-3.0 obligations and are optional, noncommercial research inputs;
they are not needed for the clean-checkout checks or canonical static release.
Treat noncommercial-derived results as a separate rights class from the CC0
core, and preserve applicable attribution and share-alike obligations when
sharing them. Every optional pack must retain its source license capture,
attribution, and receipt alongside derived artifacts. Other providers retain
their own source-specific terms. The repository's static publication gates
remain independently applicable to any proposed release.

A second independently curated Wikidata CC0 example extends the cultural cohort
with 40 cross-scene artists plus exact Aphex Twin and Four Tet identities. Its
curation does not use Every Noise reference observations or supplementary
MusicBrainz genre associations. The discovery crosswalk and raw claim response
are retained; replay pins each artist to a specific Wikidata QID and records
three conflicting duplicate P434 rows as excluded identity conflicts:

```sh
PYTHONPATH=src:scripts python scripts/acquire_independent_cultural_context.py \
  --verify data/examples/independent-cultural-context
```

See the [2026-10-02 checkpoint](../checkpoints/INDEPENDENT_CULTURAL_ENRICHMENT_20261002.md)
for cohort coverage, capture counts, and limits.
