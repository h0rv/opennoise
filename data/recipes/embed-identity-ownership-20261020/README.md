# Reject ambiguous selected catalog ownership

The ordinary public-input loader accepted selected keys shared by multiple catalog
entities, including an independently denied or suppressed sibling owner. Filtering
that sibling's eligibility did not make the join unambiguous. This slice adds raw
ownership and selected-provider consistency vetoes to the shared typed identity
gate. Hidden observations may conservatively block a join; they never supply an
output key, name or provenance claim.

The scope is the exact selected public key, including its entity kind:

- MusicBrainz ownership uses the selected kind's typed ID. Only a selected artist
  also considers legacy `source_id` observations whose namespace is `musicbrainz`
  and whose actual owner is an artist. A nonartist generic legacy observation is
  not assigned artist semantics. Different MusicBrainz entity-kind keys sharing a
  UUID do not collide merely because the UUID text matches.
- Wikidata QIDs are global: generic `wikidata_qid` and every typed
  `wikidata_*_qid` observation of that QID participate. A different owner or
  wrong-kind typed binding vetoes the selected key.
- On the selected entity, contradictory values, wrong namespaces and foreign-kind
  typed IDs within the selected provider family veto the join. Repeated same-value
  observations and complementary MusicBrainz/Wikidata identities remain supported.
  Contradictions in the other provider family are explicitly outside this slice.

Required direct refs, genre identities and hierarchy endpoints fail closed.
Unsupported optional representatives are omitted before grouping and bounds.
Existing raw selection, own permissions/custody, canonical-byte checks, ordered
batched validation and native ListenBrainz pair identities remain unchanged. No
merge, redirect, reconciliation, alternate-key choice, schema, serialized field,
qualification, model algorithm or serving default is added.

## Reproduction

From the repository root:

```sh
.venv/bin/poe sync
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest \
  tests.test_public_model_repository tests.test_embed_source_eligibility \
  tests.test_embed_metadata_labels tests.test_embed_selected_identity \
  tests.test_embed_identity_ownership -q
PYTHONPATH="$PWD/src" .venv/bin/poe check
```

The tests use explicitly synthetic qualified contracts, not source-observed music
qualification or human truth. They cover both loader APIs, denied/suppressed and
wrong-kind owners, selected-provider contradictions, valid repeated/complementary
identities, artist-only legacy behavior, global Wikidata types and optional bounds.
A full migrated-schema `EntityProjector` test first builds allowed synthetic facts,
then introduces a denied duplicate owner. Hiding that owner through suppression
does not restore eligibility. Rolling back only the counterfactual test setup
restores a byte-identical query-only load; no identity-repair API is supplied.

The owner query constrains identifier type before namespace/value, allowing the
existing production lookup index to answer exact ownership checks. A retained
query-plan regression requires indexed owner lookup and rejects `SCAN owner`.
No index or temporary database mutation is added. Independent indexed synthetic
stress runs used 18 SQL statements for 2,001 memberships and 26 for 4,001; measured
executor times were 0.206 and 0.291 seconds. These are descriptive bounded-growth
checks, not universal production latency guarantees. An earlier precommit draft's
correlated full owner scan was replaced before publication.

## Evidence

An independent raw-row Python oracle checked 146 controls, fixing 82 old failures:
64 complete positive payloads are equal, 46 required keys reject and 36 optional
cases change only by omitting the affected representative role. Four active
filesystem/network/subprocess/SQLite-write denial probes passed; actual forbidden
operations, acquisitions, model fits and new cost were zero. Local final receipts:

- `source-observations.json`: `9bb73b7efea10f61b2a88848529b322e0136983276e35051ea5037e5e436f8ca`
- `source-proof.json`: `28a4171047549a7f08dc6db52781f5a413966dd7de0225a76d4b3972b1d9f149`

A separate read-only positive census of the retained CC0 catalog found 3,207
identifier observations, 3,113 recognized typed observations and zero selected-
family ownership/consistency conflicts. The actual identity gate retains the
same 1,790 distinct eligible kind-qualified refs before and after this fix, hash
`09d51c9f5fbc7428c0044b882f4e33bd403ce5ed895a00cc6504fdbe80c39148`.
No qualification is added: this is an actual identity-gate check on a retained
schema 12 catalog, **not** a complete model load or new music-quality evidence.
Its physical input hash is
`e3f5d00d5e73ee347caf2c3b7dc280e51a0d03ecebc321861c8394bd6287e7cf`.
Census receipt `retained-census.json` hash
`7fc5ac32a331d2ed4276acf8afc2e0a8b1b9103778c5fdcfc0aac26619c877eb`;
actual gate receipt `retained-gate-source.json` hash
`edc81232af0721163181dca02df14e74b42fac4fcbc09cf222204f8bb018f272`.

Receipts/scripts are current executor-local evidence under
`/workspace/embed-identity-ownership-20261020/` and its `audit-code/` directory,
not checked-in inputs or future custody promises. `results.json` binds their exact
hashes. The synthetic tests remain reproducible without these local files;
unavailable retained evidence must be reported as unavailable. Prior negative
research findings, the failed fixed style study and reserved Jamendo style fold4
remain unchanged. No source acquisition, research/NC promotion, model fitting,
UI/default change or new cost occurs.

Final full Poe check passed on the frozen source: 2,403 Python tests in 208.018
seconds (36 skips), 122 Node passes (44 skips), formatting, lint and types. All 51
focused tests pass. Log: `/tmp/embed-ownership-full-check.log`. This slice's PR
records final exact-head review, source CI and merged-main verification.
