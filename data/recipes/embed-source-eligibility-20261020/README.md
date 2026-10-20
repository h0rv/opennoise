# Embed source eligibility across public model inputs

The ordinary public-input loader retained source-backed facts and the affected
artifact declaration after an embed-only snapshot/artifact veto. Separately, exact
claim-reference vetoes left matching direct memberships, genre nominations and
artist metadata candidates present. The normalization view correctly keeps a
distinct use policy, so it cannot supply the missing embed gate. This fix
applies embed eligibility inside the loader before grouping, window/support
aggregation and row limits. It does not fit, tune or publish a model.

A shared read-only provenance CTE excludes observations vetoed through matching
registered snapshots/artifacts for `all` or `embed`. It covers direct memberships,
album/recording evidence, hierarchy edges/endpoints, their genre nominations and
metadata candidates, pair windows and both catalog/ListenBrainz artifact lists.
Pairs additionally honor their native run artifact/snapshot IDs, preserving allowed
sibling windows and v1/v2/v3 evidence-reference contracts. Qualification support
must also have an allowed source observation and retain the original qualification,
permission, entity, source and provenance rules. A cached modelable genre ID cannot
rescue a sole vetoed qualification observation.

Direct evidence also honors `artist_genre_evidence:<id>` and matching generic
`entity_claims:<id>` references for `all`/`embed`, reused across its three input
branches. Generic links require the same artist/provenance/policy, Wikidata relation
and genre key, and exact typed Wikidata target. Default unresolved target kinds
remain supported; bare/unknown references and names are not guessed as identity.
Other evidence families gain no invented claim-reference namespaces.

Existing permissions and absent-inventory behavior remain unchanged. These loader
gates do not grant any new right or license, change source values, or alter the
normalization/display rules. No schema14, temporary view, UDF, database mutation,
acquisition, UI/default change, model build, fitting or new cost participates.

## Evidence and reproduction

The reproduction and verification use **explicitly synthetic qualified contract
fixtures**, not real-source qualification assertions or human labels. The existing
repository fixture was extended with ordinary snapshot/artifact, typed identity,
generic claim and qualification-observation fields. A separate regression applies
all ordinary migrations and uses `EntityProjector` for two explicitly synthetic
qualified genres/artists, then append-only suppression/release. Its read-only loader
runs with `query_only=ON` and preserves the underlying normalization-eligible facts.
These tests establish source-use behavior, not music quality or real-data coverage.

The initial four-case ordinary `load_catalog_only` mismatch is recorded locally at
`/workspace/embed-direct-input-20261020/reproduction.json`, SHA256
`6a097cb83447278a8ec4ed0252c9dd352bcba607372973964b57c9336759efa1`.
Each control retained1 direct/1 genre/1 artist candidate/1 artifact before the fix.
Claim refs affect only matching direct branches; an independently allowed source
artifact may remain declared. Source snapshot/artifact vetoes cover the affected
source facts and declarations together. A wholly
unsupported input still follows `PublicModelInput` minimum-support validation;
tests keep a clearly independent allowed anchor when checking partial filtering.
No support requirement is relaxed to produce an empty model input.

Run from the repository root:

```sh
.venv/bin/poe sync
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest \
  tests.test_public_model_repository tests.test_embed_source_eligibility -q
```

Twenty focused tests pass. They cover every input family, use-specific source
vetoes, exact claim bindings, sibling artifacts/qualification, pair support/windows
and reference formats before bounds, missing inventory, full migrated-schema
projection/release, query-only connections and no-event byte equivalence.

The original loader and new loader produce byte-identical no-event payloads for
catalog-only and all three pair-reference formats on the same expanded fixture.
Local comparison receipt `no-event-final.json` SHA256
`119da1e6ffec4ff461bd9c54b7eb857ba44af087d9a34b0e99644f86bef009de`;
individual payload hashes and sizes are in `results.json`. This retains existing
serialization and defaults; it is not a new quality evaluation.

An independent **physical row-filter counterfactual using the same serializer**
checked128 controls, including sole forbidden qualification and allowed sibling
support, all facet outputs and pair support/window thresholds. The actual loader
ran with SQLite writes and filesystem/network/subprocess operations denied;
four active denial probes passed, with zero actual forbidden operations and zero model fits. Local guarded proof
`/workspace/embed-direct-input-20261020/source-proof.json` SHA256
`60ecff401b39df77f8f486d0016dee98c66a90f758b7ca1d22b9fb5aa42dd8cf`,
auditor-script SHA256
`4ef55c1d3ee73870c2e000b36fa04955b532d4ff18bbb90c5910077921e5faf7`.
This is a synthetic eligibility counterfactual, not an independently collected
cohort or an independent numerical model implementation.

These absolute paths describe current executor-local evidence, not repository
inputs or promised future custody. All synthetic fixtures and regression commands
are retained in code; unavailable local proofs must be reported as unavailable,
not silently substituted. Final full Poe check passed:2,372 Python tests in204.477 seconds (36 skips),
122 Node passes (44 skips), formatting, lint and types. Luna accepted the final
source and qualification/fixture scope. Log: `/tmp/embed-source-full-check.log`.
`results.json` and this slice’s PR record subsequent exact-head/main CI and
source-bound guard verification.

## Limits

The fix gates source observations, qualification support and artifact declarations.
The generic repository's existing raw identifier/name selectors do not become an
own-metadata provenance certificate here; metadata identity ambiguity/label policy
needs a separately demonstrated bounded fix. Persisted model invalidation is also
separate. No recommendation relevance, new source qualification, or human-truth
claim is made. Previous negative research results and the reserved Jamendo style
fold4 remain unchanged and are never used by this slice.
