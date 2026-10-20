# Own eligibility of selected catalog keys

The ordinary public-input loader could retain artist, genre, release-group and
recording keys whose sole identifier observation was vetoed for embedding.
Independently allowed names, qualification and source facts did not authorize that
identifier observation. Both catalog-only and combined catalog/ListenBrainz loads
showed this mismatch in explicitly synthetic qualified contracts.

This fix preserves the existing raw key selection and requires that exact selected
entity/key to have an independently embed-eligible typed observation. The type and
namespace must agree with the catalog entity kind; Wikidata QIDs and lowercase
MusicBrainz UUIDs must be canonical. An explicit embedded-NUL veto precedes
SQLite length/pattern checks, which otherwise truncate at NUL. Own permission, source, provenance, entity and
matching registered snapshot/artifact suppression gates apply. Missing registered
inventory remains supported and no CC0/export-only rule is added.

Required direct memberships, genre identities and hierarchy endpoints fail closed
when their selected key lacks support. Required keys are deduplicated in original
order and validated in read-only batches of at most250 keys through a bound JSON
parameter, preserving the first unavailable key without per-row SQL roundtrips. Optional artist/release-group/recording
representatives are omitted before SQL aggregation and bounds. Those SQL checks
repeat the original explicitly correlated selector expression, preserving selection
and avoiding alias shadowing. An independently allowed observation of the SAME
key can support it; a different public alias cannot rescue a selected private key.
No alternate key is chosen, identity repaired, owner reconciled or name fabricated.
Native ListenBrainz artist IDs remain observations of their allowed pair evidence;
no invented catalog linkage is required.

## Reproduction and evidence

From the repository root:

```sh
.venv/bin/poe sync
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest \
  tests.test_public_model_repository tests.test_embed_source_eligibility \
  tests.test_embed_metadata_labels tests.test_embed_selected_identity -q
PYTHONPATH="$PWD/src" .venv/bin/poe check
```

The fixtures are explicitly synthetic qualified contracts, not real-source music
qualification or human truth. Minimal fixtures now declare their actual catalog
kinds and typed source identifiers. A full migrated-schema `EntityProjector` test
keeps independently allowed names, qualification and P136 evidence while vetoing
the sole selected genre-ID source. Loading rejects the key; append-only release
restores the byte-identical payload on a query-only connection. Additional tests
cover bounded query counts and cross-batch error ordering, hierarchy endpoints, both loader APIs, canonical syntax/type/kind, own rights,
independent exact observations, conflicting aliases, and optional malformed IDs
before limits. No source fact, qualification, model geometry contract or serialized
field changes, and no model is built or fitted.

The local initial four-role reproduction is
`/workspace/embed-identity-eligibility-20261020/reproduction.json`, SHA256
`d527558050c85c735e73f79ad6334603cd9081de503fd28a22e31e5b1324b7dc`.
An independent Python raw-row oracle uses the preceding frozen fixture plus
explicitly typed/kinded observations. It does not import the new tests. Its controls
cover both APIs, four entity roles, source/provenance/snapshot/artifact use vetoes,
permissions, release, missing inventory, exact duplicate observations, conflicting
public aliases, malformed identifiers and wrong types/kinds. A separate canonical-byte audit
checks embedded NUL, whitespace, non-ASCII and other invalid encodings against
Python UUID/full-match rules. The first draft's
optional SELECT-alias comparison failed four alternate-key controls; that draft
was corrected before publication and retained regressions exercise those cases.
The final source-bound independent audit passes all 120 controls, fixing 80 old
failures. All 80 valid source-fact/genre/name/pair/hierarchy/artifact payloads retain
their values; 40 complete JSON model dumps are equal, and 40 unsupported optional
representative cases are omitted as required. Four active filesystem, network,
subprocess and SQLite-write denial probes pass, with zero actual forbidden
operations, fits or new cost. Final receipts are
`/workspace/embed-identity-eligibility-20261020/source-observations.json`, SHA256
`fa2db776c573ab1bd5b1523ed6a3e5f8793747f33dad995f4446241be712e31c`, and
`source-proof.json`, SHA256
`8b0c51de415be5a2f73c9f2df800ace434db3970f41b10c327c29e52d69026ec`.
An additional indexed synthetic stress with 2,000 distinct added artists and
2,001 memberships executed 18 SQL statements in 0.111 seconds on this executor.
This is descriptive, not a universal production latency claim. The retained unit
tests also check deduplication, bounded batch counts and first-error ordering.
Benchmark receipt `benchmark-final.json`, SHA256
`b463aa2645e527ed0548e483e07f16b1cb9afcbf912419ac31f88772953446e0`, is in the same
local evidence directory. The per-row validation draft was replaced before
publication; the final batch source is pinned by these receipts.
All 88 independent canonical-byte controls pass against Python UUID/full-match
rules, including NUL in multiple positions, whitespace, non-ASCII and invalid
case/prefix forms, across both APIs and all four roles. Receipt
`canonical-source.json`, SHA256
`a45e7dc59bf6eb63407c9fed071bfe5705a0979635a67e90c2f10aaf2bb15203`, binds the same final
source. The initial SQL pattern-only draft missed embedded NUL truncation; the
explicit NUL gate and retained regressions correct it before publication.
The oracle checks source-use behavior, not newly qualified real music evidence or
numerical model quality. Additional bindings are in `results.json`.

These evidence paths are current executor-local receipts, not repository inputs
or future custody promises. The synthetic tests remain reproducible without them;
unavailable receipts must be reported as unavailable. No acquisition, research/NC
promotion, model fit, UI/default change or new cost occurs. Prior negative research
results and reserved Jamendo style fold4 remain unchanged.

Final full Poe check passed on the final NUL-safe batch source: 2,394 Python tests
in196.196 seconds (36 skips), 122 Node passes (44 skips), formatting, lint and types.
All42 focused tests pass; Luna accepted the exact final runtime. Log:
`/tmp/embed-selected-id-nul-final-check.log`. Earlier draft runs do not certify the
final source. This slice's PR records subsequent exact-head and merged-main CI.

## Boundary

This gate certifies only the selected observation's local kind/type/canonical form
and own embedding eligibility. It does not reconcile duplicate owners, repair
historical identities, choose another identifier or certify arbitrary catalog
metadata globally. Persisted model invalidation remains a separate boundary.
