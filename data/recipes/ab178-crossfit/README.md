# Exhaustive native AB178 own-fold evaluation

This engineering diagnostic executes every predeclared exact contract and every
immutable component fold. It reuses the reviewed version-routing module
unchanged. Each final query uses only its own fold-excluded contract frame.
There is no fit-member emission in the final query evidence, fallback to another
frame, distance pooling, or final all-data model. Nested routing artifacts retain
their original diagnostic outputs; final own-fold query rows and artist
observations are selected separately and carry exact contract, fold, bundle and
frame hashes. Own query vectors remain in each cell's `inference_rows`.

The checked `protocol.json` was frozen before computing the remaining folds.
SHA256:
`4fefa8bfc2ac9ac7985b86e4a27db92443188031c3dcab2e455b9b08cb25dda6`.
It contains all three pinned fold plans, each with the same six contracts,
cohort, native credit-component ledger and existing numerical policy. No names,
source tags, genre labels, audio or newly acquired input is consumed. Source
features and exact core credits are CC0 AcousticBrainz/MusicBrainz metadata.

Run from the repository root with a fresh output path:

```sh
.venv/bin/poe sync
.venv/bin/python scripts/run_ab178_crossfit.py build \
  --source data/examples/native-sonic \
  --source-pin 13e21e5296989e148e0efc2f6956675d2d391326552fe4a1a3b67df56e1494cb \
  --protocol data/recipes/ab178-crossfit/protocol.json \
  --protocol-pin 4fefa8bfc2ac9ac7985b86e4a27db92443188031c3dcab2e455b9b08cb25dda6 \
  --output .cache/ab178-crossfit-reproduction
```

The command prints the external manifest pin. Keep that separately. Copy only
the complete output directory to another location and replay without source
paths or refitting:

```sh
.venv/bin/python scripts/run_ab178_crossfit.py verify \
  --registry .cache/ab178-crossfit-reproduction \
  --manifest-pin PRINTED_MANIFEST_SHA256
```

Build stages all three independently verified routing runs before atomic
publication. Verify checks external pins, a closed file/directory inventory,
implementation/runtime pins, every underlying frozen-frame/query contract,
identical global source identity across folds, exact exhaustive query routing,
and regenerated recording/artist evidence. The CLI enforces one numerical
thread, 120-second wall/CPU bounds and 1 GB address space. Stored payloads are
bounded to 32 MB, 256 files and 2 MB per file; underlying routing retains its
100-nomination/eight-contract limits.

The retained run on 2026-10-19 preserved all 100 nominations: 34 clean exact
contract-compatible recordings, 21 dirty extractors and 45 missing HTTP-404
source observations. Seven of the 18 declared contract/fold cells fitted;
all other cells and every zero-query cell remain explicit.

| Heldout fold | Contract prefix | Own-fold queries | State | Emitted | Outside support | Insufficient support |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| 0 | 538b3d39 | 4 | fitted | 3 | 1 | 0 |
| 0 | 7769bf7c | 5 | insufficient | 0 | 0 | 5 |
| 0 | 955eda46 | 8 | fitted | 0 | 8 | 0 |
| 0 | 9c7a3f53 | 1 | insufficient | 0 | 0 | 1 |
| 0 | c589fee5 | 0 | insufficient | 0 | 0 | 0 |
| 0 | ea5982bd | 2 | insufficient | 0 | 0 | 2 |
| 1 | 538b3d39 | 3 | fitted | 0 | 3 | 0 |
| 1 | 7769bf7c | 1 | fitted | 1 | 0 | 0 |
| 1 | 955eda46 | 0 | no cross-component heldout query | 0 | 0 | 0 |
| 1 | 9c7a3f53 | 0 | no cross-component heldout query | 0 | 0 | 0 |
| 1 | c589fee5 | 0 | insufficient | 0 | 0 | 0 |
| 1 | ea5982bd | 0 | insufficient | 0 | 0 | 0 |
| 2 | 538b3d39 | 2 | fitted | 2 | 0 | 0 |
| 2 | 7769bf7c | 1 | fitted | 1 | 0 | 0 |
| 2 | 955eda46 | 4 | fitted | 4 | 0 | 0 |
| 2 | 9c7a3f53 | 2 | insufficient | 0 | 0 | 2 |
| 2 | c589fee5 | 1 | insufficient | 0 | 0 | 1 |
| 2 | ea5982bd | 0 | insufficient | 0 | 0 | 0 |

Final outcomes are 11 emitted, 12 outside training support, 11 insufficient
training support, 21 dirty and 45 missing. The 11 emitted queries yield 55
recording edges and 63 exact-credit artist observations across 28 cell-scoped
artist links. Co-credit observations may repeat across artists; links remain
separate by contract and fold. Emission counts by immutable fold are 3, 1 and 7. These are
historical compatibility/support outcomes. The cohort and fold-0 pilot were
already inspected; this is not fresh confirmation, calibration, genre/listener
accuracy or EveryNoise parity.

The local artifact `.cache/ab178-crossfit-20261019` occupies 6,647,082 bytes.
External manifest SHA256:
`f24b2306e0ab997db68e79483ccae993357bb3b4dc3c66d2b04cd3d5f3b8c6e7`.
Evidence SHA256:
`761c2c859ace7d7a895be493a4a48b9917c406bd6091716ccaffec54460a45e8`.
The nested fold-0 manifest is exactly the prior reviewed artifact:
`a6d36879c7e5b1a69a7f8e381345830854f080ef73715387678b7a6757b5cb1f`.
Six focused tests passed, covering actual exhaustive own-fold isolation,
contract/component exclusions and frame proofs, all unsupported/zero-query
cells, relocated replay without fitting or source projection, unchanged fold-0
query values, resealed inventory/runtime/route/result tampering, and atomic
failure. New external cost: $0; no acquisition attempt.

The independent parent audit matched all 18 cells, all seven fitted frames'
exact moments/fit identities, 23 fitted-frame own-fold query rows, all 55 ordered
recording edges and all 63 exact-credit artist observations against an
independent arithmetic oracle. Maximum numeric/distance error was zero. Fold-0
manifest bytes are identical to the prior slice, and no final query is a fit
member. An actual relocated CLI run passed under independently pretested hooks
denying original sources, fitting and networking, with zero forbidden opens or
refits. Local audit receipts are retained in the root checkout's ignored
`.cache/ab178-crossfit-audit-20261019.json` and
`.cache/ab178-crossfit-relocated-audit-20261019.json`, bound to the manifest above.
Independent Luna static review found no material issue.

Final `poe check` passed: format/lint/type checks; 166 Node tests (122 passed,
44 skipped, zero failures); 2,206 Python tests in 144.585 seconds (36 skipped).
All six focused crossfit tests passed. The reviewed routing module has no diff.
