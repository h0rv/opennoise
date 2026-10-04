# Component-held-out recording comparisons

This workflow consumes the exact-recording feature companion without changing
its 17-column source artifact. It provides a reproducible engineering baseline,
not an evaluation of musical relevance: no recording annotation targets or
listener judgments are available in these inputs. Relevance metrics are null,
and the previously inspected, selected cohort is not fresh confirmation.

First build the companion as described in `RECORDING_FEATURE_COMPANION.md`.
Then freeze the rules and source/code bindings before fitting or ranking:

```sh
.venv/bin/python scripts/evaluate_recording_companion.py freeze \
  --observations data/examples/recording-facts \
  --sonic data/examples/native-sonic --companion .cache/recording-features-v1 \
  --declaration .cache/recording-evaluation-declaration.json
.venv/bin/python scripts/evaluate_recording_companion.py run \
  --observations data/examples/recording-facts \
  --sonic data/examples/native-sonic --companion .cache/recording-features-v1 \
  --declaration .cache/recording-evaluation-declaration.json \
  --output .cache/recording-evaluation-v1
.venv/bin/python scripts/evaluate_recording_companion.py replay \
  --observations data/examples/recording-facts \
  --sonic data/examples/native-sonic --companion .cache/recording-features-v1 \
  --declaration .cache/recording-evaluation-declaration.json \
  --output .cache/recording-evaluation-v1
```

Normalized-catalog inputs additionally require `--native-source` and `--root`.
Every action replays the companion against its original native sources. A
receipt-only substitute is not accepted. The larger recovery inputs remain
unavailable; this workflow does not establish their replay or coverage.

The ledger connects exact recording IDs and every supplied native co-credit
before any feature filtering, including edges through missing-feature rows and
both credit sets in a conflict. Cohort artist associations are not edges. The
component ID is the minimum recording MBID; a fixed SHA256 seed assigns each
component to one of three folds. All observations of a recording remain in one
fold. A recording enters training once, and only if every observation joined
and its vectors and native credit sets agree. Conflicts or partial failed joins
quarantine that training identity; no failed source observation is dropped.

For each held-out fold, column support is computed on unique eligible training
recordings only. A column needs at least three observations and 80% training
coverage. At least three training recordings must be complete in the selected
columns. Their population mean and standard deviation define the frame;
constant columns are omitted. This conservative sequence can exclude incomplete
training rows even when a selected column later proves constant. It performs no
imputation, and held-out values or missingness cannot affect the frame.

Queries and candidates must have every active field and lie within 12 training
standard deviations on each one. The numeric arm ranks standardized Euclidean
distance with recording-ID tie breaks. The comparison arm uses fixed SHA256
ordering. Both arms use the same supported training candidates, exclude the
query component, return at most five recordings, and share abstention rules.

`ledger.json` preserves recording/component/fold assignments and observation
counts. `frames.json` contains portable JSON transforms and their exact training
rosters. `queries.jsonl.gz` retains every observation in original order, with
source provenance, join state, fold, outcome and both rankings. `report.json`
separates observation and unique-recording denominators, preserves every source
artist (including zero-query artists), and reports emission coverage. Coverage
and distances are not accuracy, calibrated confidence or membership probability.

`load_frames` checks the closed artifact set and hashes without pickle. Loading
alone does not authenticate source custody. Replay independently refits from
native inputs and compares every artifact, including loaded JSON frames,
byte-for-byte in the locked runtime. Changed policy, code, inputs or resealed
output mutations fail replay. Limits are 250,000 observations, 128 MB decoded
input, 20 MB output and two million potential distance pairs; failures retain
their partial attempt without a successful report.

Album edges, duplicate-recording edges and unrecorded artist aliases remain
unavailable/unresolved. Equal projected vectors are not treated as proof of a
shared recording. Adding album or duplicate edges later requires independently
verified native evidence, a new explicit ledger/declaration revision, and new
folds and evaluation artifacts; do not retrofit those edges into a completed
run or claim complete leakage isolation now. No website, audio, genre-label,
release-style or public-promotion inference is introduced.
