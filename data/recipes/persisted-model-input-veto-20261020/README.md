# Retract persisted models after recorded-input vetoes

A persisted public model remained servable after an embed-only veto of its recorded
input source, provenance, artifact or snapshot. Recognized claim vetoes also left
its maps, names, representatives, profiles and neighbors available. Filtering a
future model load does not retract an already-published result.

Schema 14 changes the central `servable_public_model_runs` view. It retains the
existing output permissions, derived-output events and suppressions, and adds
`embed` to the existing `all`/`display`/`export` recorded-input vetoes. All dependent
ordinary public views/APIs continue to use that central run gate. Raw runs, input
bindings, current selections, layouts and model outputs remain unchanged.

## Deliberately coarse claim policy

The existing input ledger records `(model_run_id, provenance_id, artifact_id)`,
not exact consumed claim rows. For an active `all` or `embed` event, either exact
reference `artist_genre_evidence:<positive ID>` or `entity_claims:<positive ID>`
retracts a run when that existing row's **own provenance** is a recorded input.
Any row in those namespaces participates: an unused literal, qualification,
hierarchy claim or propagated evidence row may conservatively retract a model
sharing the source batch. There is no claim-type, target, artist or membership
lineage inference, and no fabricated ledger or claim-consumption certificate.
This collateral scope is intentional.

Claim `display`, `export`, `normalize`, `train` and `local_search` events do not
trigger this new embedding-input rule. Bare IDs, unknown namespaces, leading zeros,
nonpositive IDs, malformed/overflow/NUL/newline references, nonexistent rows and
unrelated provenance do not bind a dependency. The query uses a primary-key lookup
plus an exact canonical namespace/positive-ID round trip, so casting a suffix alone
never makes a reference valid. It does not scan the claim catalog or build an
automatic provenance index for each serving request.

Append-only release restores eligibility for the unchanged model. Existing
`active_suppressions` latest timestamp/ID semantics remain unchanged, including
future-timestamp events; this migration adds no wall-clock deferral rule.

## Reproduction and scope

Run from the repository root:

```sh
.venv/bin/poe sync
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest \
  tests.test_db tests.test_public_model_publish tests.test_persisted_model_input_veto \
  tests.test_candidate_public_projection tests.serving.public.test_direct_claim_display -q
PYTHONPATH="$PWD/src" .venv/bin/poe check
```

Tests reuse the existing deterministic synthetic graph/publish fixture and ordinary
`Database` APIs. They are not a research fit, a real-source model publication or a
music-quality evaluation. Coverage includes all four recorded-input targets,
unused literal and propagated same-batch collateral, unrelated provenance, exact
reference parsing, every use boundary, release, immutable stored rows and indexed
claim lookup. A schema 13 published fixture remains stale before migration and
retracts after upgrade, with its ledger/runs unchanged; repeated initialization is
byte-idempotent.

Mutable current databases upgrade to schema 14. Narrow historical readers accept
only supported schemas 12/13/14 and require the physical database, receipt and
binding versions to agree. Defaults for historical serialized bindings remain 12;
new writers record the actual version. Tests restore the actual old view for
synthetic schema 12/13 fixtures and verify sealed database/receipt/binding bytes
are unchanged by reading. No released input is mutated, silently upgraded or
re-certified as schema 14. Source-builder implementation reports include the new
migration dependency.

The initial ordinary-API reproduction retained 1 servable run, 2 public map points,
3 representatives, 2 profile memberships and 4 neighbors after each input embed
veto and both recognized claim all/embed vetoes. Current-executor receipt
`/workspace/persisted-model-veto-20261020/reproduction.json`, SHA256
`2382eec859e021d75f3fd3402837596ca961408fac1342fd05e5f035ff8abb9e`, explicitly distinguishes
source-batch correlation from exact claim lineage.

## Independent evidence

An independent frozen synthetic seed was published through the ordinary publisher
before the migration, without importing the new tests. An independently computed
raw-reference/provenance oracle checked 227 controls. Eleven stale-output controls
are corrected; 216 other complete payloads are unchanged (201 visible, 15 already
blocked). Every release restores the exact payload, and all stored model/source rows
remain unchanged apart from the explicitly appended control events. Four active filesystem/network/subprocess/SQLite-write denial
probes passed; actual forbidden operations, research fits, acquisitions and new
external cost were zero. Query-plan checks confirm primary-key claim/evidence
lookup.

Final local receipts under
`/workspace/persisted-model-veto-20261020/independent-v2/`:

- `before-observations.json`: `eec99304d9dc21b4b6cbf73ed5cfc693cf50b1e06c45b33c0f5ceda4616ad71d`
- `source-observations.json`: `1f1c6e0333e34115bae1fb9dd02ea0e534e6fb3a45588631dcc17a1e3040e147`
- `source-proof.json`: `e4e77899d6619622ca68518a3cd52319cee2a8c228dba04d1e55b22f69bcb462`

`results.json` binds code, migration and evidence hashes. These paths describe
current executor-local custody, not checked-in inputs or guaranteed future files;
reproducible synthetic tests are retained. The retained real CC0 catalog has no
published model runs, so no actual real-source model verification is claimed.

The change cannot identify which particular claims a model consumed, retract
independent static copies, or certify unrecorded legacy dependencies. It preserves
existing permission and missing-ledger behavior; it adds no new rights grant,
model re-fit, precise claim ledger, UI/default change, acquisition or cost. Prior
negative research results, the failed fixed study and reserved Jamendo style fold4
remain unchanged.

## Checks

The first full-check attempt was stopped after identifying four stale schema-13
expectations in `tests/test_db.py`. The explicit expected version is now 14; all
seven database tests pass. Runtime code and the independent audit pins are unchanged.
Focused checks passed 57 publication/migration/compatibility tests and, separately,
7 database tests. The final `poe check` passed: 2,413 Python tests in 203.891 seconds
(36 skipped), 122 Node tests passed (44 skipped), and formatting/lint/type checks
passed. Log: `/tmp/persisted-veto-full-final.log`. Luna independently reviewed the
frozen runtime and passed all 57 focused tests.
