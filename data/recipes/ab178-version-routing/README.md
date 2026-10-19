# Native AB178 exact version routing

This frozen engineering run routes the retained 100 native recording nominations
through the existing verified numeric bank, separate exact-contract frames,
frozen recording inference and exact-credit artist evidence. It consumes no
source tags, names, audio, genre labels or new network data. CC0 native
AcousticBrainz metadata and MusicBrainz core credits remain the source evidence.

The checked `protocol.json` was frozen before these fits. Its SHA256 is
`e918bd2dc23987ef492342aaa165d2de15a23fa2d06bf3243fd18bdf2747b792`.
The complete native co-credit ledger determines components and immutable folds
before contract filtering, including dirty and incompatible rows. Fold 0 is the
heldout fold. Every contract retains the unchanged recording-evaluation policy;
no fallback, mixed normalization, cross-contract candidate or combined score is
allowed. All six declared groups remain visible. Each group's contract pin
binds its recording results and nested artist observations. Unrouted records
retain native credits, component/fold and their original source outcome.

Run from the repository root with a fresh output path:

```sh
.venv/bin/poe sync
.venv/bin/python scripts/run_ab178_version_routing.py build \
  --source data/examples/native-sonic \
  --source-pin 13e21e5296989e148e0efc2f6956675d2d391326552fe4a1a3b67df56e1494cb \
  --plan data/recipes/ab178-version-routing/protocol.json \
  --plan-pin e918bd2dc23987ef492342aaa165d2de15a23fa2d06bf3243fd18bdf2747b792 \
  --output .cache/ab178-version-routing-reproduction
```

The command prints the external manifest pin. Keep that pin separately, then
verify/replay after relocating only the output directory:

```sh
.venv/bin/python scripts/run_ab178_version_routing.py verify \
  --registry .cache/ab178-version-routing-reproduction \
  --manifest-pin PRINTED_MANIFEST_SHA256
```

Offline replay reads neither original sources nor a training path and never
refits moments. It verifies the closed inventory, implementation/runtime pins,
native bank/intake joins, full identity topology, fixed cohort/support, existing
frozen-frame/query validation, and exact regenerated evidence. The bundle
contains the verified bank and both fitted portable frames, preserving old
single-frame compatibility. Only expected structural insufficient-support or
missing cross-component heldout support produces a nonfit group; custody,
version, shape and runtime errors abort publication. Publication is staged and
atomic. The CLI limits wall/CPU to 120 seconds, address space to 1 GB, numerical
threads to one, nominations to 100, contracts to eight, files to 64 and stored
payloads to 10 MB (2 MB per file).

Observed retained-source results on 2026-10-19:

| Contract prefix | Compatible | Train recordings/components | Heldout recordings/components | Fitted-member emits | Heldout emits | Heldout outside support |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 538b3d39 | 9 | 5 / 2 | 4 / 3 | 5 | 3 | 1 |
| 7769bf7c | 7 | 2 / 2 | 5 / 3 | 0 | 0 | 0 |
| 955eda46 | 12 | 4 / 2 | 8 / 4 | 4 | 0 | 8 |
| 9c7a3f53 | 3 | 2 / 1 | 1 / 1 | 0 | 0 | 0 |
| c589fee5 | 1 | 1 / 1 | 0 / 0 | 0 | 0 | 0 |
| ea5982bd | 2 | 0 / 0 | 2 / 1 | 0 | 0 | 0 |

The four unfitted contracts retain all 13 compatible observations with
`insufficient_training_support`. Another 21 dirty extractor observations and
45 missing HTTP-404 source observations remain explicit. This adds an actual
separate numeric frame for nine recordings, with three heldout queries inside
its unchanged support gate. The previous 12-recording contract remains
unchanged. These are compatibility/support counts, not relevance or accuracy.
The source cohort and old pilot were previously inspected; there is no fresh
confirmation, calibration, genre/listener claim or all-data final model.

The local checked artifact `.cache/ab178-version-routing-20261019` has 1,929,914
bytes including its manifest. Manifest SHA256:
`a6d36879c7e5b1a69a7f8e381345830854f080ef73715387678b7a6757b5cb1f`.
Evidence SHA256:
`8b423b2ba46633967174958ec93fdc798ccfce2335b199d7d2b602c343a254c7`.
The successful retained build was followed by offline replay; updating final
implementation pins did not refit either frame. Focused tests additionally
exercise real end-to-end replay, no source/refit access, fixed component and
contract isolation, constant/missing support, resealed nested-file/runtime/
cross-contract tampering and atomic validation failures. New external cost: $0.

An independent parent oracle reconstructed all 100 native ledger entries,
6,052 compatible raw coordinates, both fitted frames' columns/fit identities/
centers/scales, all 21 fitted-contract query rows and all 33 ordered recording
edges; every value matched, with maximum distance error zero. The original
`955eda46` portable bundle is byte-identical to its prior pilot. A relocated
CLI replay under a pretested audit hook denied original source, bank, plan and
artifact paths plus networking; it passed with zero forbidden opens. Local
independent evidence is retained in the root checkout's ignored
`.cache/ab178-version-routing-audit-20261019.json` and
`.cache/ab178-version-routing-relocated-audit-20261019.json`.
Six focused tests passed, including a no-fit subset-plan check proving that
unplanned clean contracts abstain without fallback. Final static format/lint/type
checks passed after the intake-copy correction; the numeric evidence remained
unchanged and final runtime pins were refreshed without refitting.

Final `poe check` passed: format/lint/type checks; 166 Node tests (122 passed,
44 skipped, zero failures); 2,200 Python tests in 132.816 seconds (36 skipped).
Final static checks and all six focused routing tests were repeated after the
intake-copy correction. Independent Luna review found no material issue.
