# Portable native AB178 metadata frame

This offline backend reuses the existing native AcousticBrainz bank and recording
component engine. It projects retained source JSON into versioned 178-coordinate
queries and fits one explicit held-out component fold. It does not extract audio,
use FMA encoder weights, predict genres or establish musical relevance.

## Checked pilot and current limitation

The pre-frozen fold-0 pilot had 12 compatible recordings: four training records
from two known credit components and eight heldout records from four components.
**All eight heldout records exceeded the unchanged support gate.** Only the four
fit-member rows emitted neighbors, with `fit_member: true`. This demonstrates the
source/identity/frozen-inference path and provides no supported heldout retrieval
result. The fold, gate and cohort were not changed after observing this outcome.

The source roster retained 12 compatible analyses, 21 dirty builds, 22 other
extractor versions and 45 explicit 404s. The 16-query check included all 12
compatible rows plus one dirty, version-mismatched, missing and unnominated case.
Independent reconstruction verified 2,136 compatible values, all 100 credit-graph
rows, fitted moments, support states and neighbor distances with zero differences.
Relocated results were byte-identical, and repinned credit tampering and an
incompatible schema were rejected without publishing output.

The actual 432 KB bundle and 82 KB query pack produced the 16 outcomes in 0.221
seconds at 35.5 MB peak RSS on this executor. These are single-run observations,
not latency guarantees. `pilot-contract.json` records the exact clean build and
analysis configuration; `results.json` records aggregate hashes, limits and
resource measurements. No audio was extracted or acquired.

Before fitting, freeze a canonical JSON contract with exactly these fields:

```json
{"analysis":{"analysis_sample_rate":44100,"downmix":"mix","equal_loudness":0},"revision":"native-ab178-feature-contract-v1","schema_sha256":"SHA256_OF_CANONICAL_EXISTING_AB178_COLUMNS","version":{"essentia":"EXACT_SOURCE_VERSION","essentia_build_sha":"EXACT_40_CHARACTER_CLEAN_BUILD_SHA","essentia_git_sha":"EXACT_SOURCE_GIT_VERSION","extractor":"EXACT_SOURCE_EXTRACTOR"}}
```

Canonical JSON means sorted keys, compact separators and one trailing newline,
as produced by `opennoise.ml.ab178_portable.encoded`. The schema digest uses that
encoding of the existing `vector_bank.columns()` list. Record the contract file's
external SHA256 before any fit. Missing or extra contract fields and dirty builds
are rejected. Every selected extractor version field and analysis setting must
match exactly, including JSON value types. This contract describes retained
provider analysis; it is not a reproducible local waveform extractor declaration.

Run the existing locked Python 3.13 environment with explicit worktree
`PYTHONPATH=src`. All outputs must be fresh and outside source custody.

```sh
python scripts/run_ab_portable_frame.py export-bundle \
  --source /path/to/native-sonic --source-receipt-sha256 SOURCE_RECEIPT_SHA256 \
  --bank /path/to/native-ab-bank --bank-receipt-sha256 BANK_RECEIPT_SHA256 \
  --contract /path/to/contract.json --contract-sha256 CONTRACT_SHA256 \
  --fold 0 --output /path/to/bundle

python scripts/run_ab_portable_frame.py export-queries \
  --bundle /path/to/bundle --bundle-sha256 BUNDLE_JSON_SHA256 \
  --source /path/to/native-sonic --source-receipt-sha256 SOURCE_RECEIPT_SHA256 \
  --recording-mbid CANONICAL_NATIVE_RECORDING_MBID --output /path/to/queries

python scripts/run_ab_portable_frame.py infer \
  --bundle /path/to/bundle --bundle-sha256 BUNDLE_JSON_SHA256 \
  --queries /path/to/queries --query-sha256 QUERIES_JSON_SHA256 \
  --output /path/to/result.json
```

`--fold` is required; select it from the source identity/configuration inventory
before examining numeric outcomes. Eligible training recordings must be outside
that fold. The unchanged recording engine fits support, means and scales on
unique compatible training recordings only. It requires three training records,
80% column observation coverage, nonzero variance and the existing 12-standard-
deviation query support limit. No supported training frame or no compatible
cross-component held-out query causes export to fail before publication.

The bundle preserves every nominated native source outcome. Exact recording
MBIDs and independent complete native MusicBrainz core credits establish identity;
selection-associated artist IDs never supply component edges. All known native
credit edges enter the ledger before version filtering. Unknown album, duplicate-
recording and credit-alias edges remain explicitly unresolved in the ledger.
Missing, dirty, unknown, configuration-mismatched and version-mismatched analyses
remain separate outcomes with null features. No imputation occurs.

Query packs preserve requested order, raw capture SHA256, extractor version,
analysis configuration, masks and credit proof. The original source receipt must
match the capture pinned in the bundle. Portable inference validates each row
against the frozen roster, including numeric values and exact identity evidence.
Unnominated IDs remain explicit abstentions. Inference reads only the bundle,
query pack and installed runtime, applies the fixed frame and excludes self and
the entire known credit component. Neighbors are ordered by distance then native
MBID; every result includes `fit_member`. No labels or baseline arm are emitted.

`verify` requires the bundle and its pin. `replay` uses the same bundle/query
arguments as inference plus `--result` and `--result-sha256`; it compares the
complete pinned result. Relocation needs no original native bank, source pack or
contract path. Runtime code and Python/NumPy versions remain pinned.

Every CLI stage has 120 CPU seconds, 120 wall seconds and 1 GB address space.
The source and query caps are 100 rows each, with 178 coordinates, at most 10,000
query/candidate pairs and five neighbors. Each JSON file is capped at 2 MB and
each pack at 4 MB. This is a selected small-cohort metadata comparison; it adds
no recording coverage, audio rights, listening validation or product promotion.

## Native source through artist evidence export

`export-artists` closes the recording-to-artist output gap in the existing CLI.
It takes the approved retained native source and an already frozen AB178 bundle,
verifies the complete source custody, exact core credits, extractor contract and
frozen roster, then runs the existing query exporter and inference implementation
for **every nominated recording**. It aggregates the result into one consumable
`artists.json` without hand-built queries or an intermediate-file handoff.
The command does not fit or select a model. Existing bundle/runtime pins remain
compatible because neither the portable inference implementation nor the model
engine changed.

```sh
.venv/bin/python scripts/run_ab_portable_frame.py export-artists \
  --source data/examples/native-sonic \
  --source-receipt-sha256 13e21e5296989e148e0efc2f6956675d2d391326552fe4a1a3b67df56e1494cb \
  --bundle /path/to/frozen-ab178-bundle \
  --bundle-sha256 EXTERNALLY_RECORDED_BUNDLE_SHA256 \
  --output /path/to/fresh-artist-export
```

If the frozen bundle is absent on a fresh executor, construct the bank with
`scripts/build_native_ab_vector_bank.py build`, then use the documented
`export-bundle` command above with the checked-in pilot contract and its external
SHA256 `955eda463b35d35530924e195837d95ad7ba00c010005bd0be6af42381c378d4`.
The retained pilot's fold is **0**; preserve it rather than trying folds for a
better result. Bank creation projects retained bytes; export-bundle fits the
explicit fixed frame once. These are model preparation, separate from the
single-command source-to-artist inference/export path.

The JSON contains `recordings`, `artists`, `counts` and `scope`, plus source,
bundle, query, inference and producer hashes. Each recording retains its outcome,
exact credited artist IDs, component/fold, fit-member flag, query role and recording
neighbors. Numeric vectors are omitted from the consumer export. Each artist lists
its credited nominated recordings and outcome counts. `neighbor_evidence` groups
recording-pair observations by candidate artist and query role: `heldout`,
`fit_member`, `training_not_fitted` or `unresolved_identity`. Each edge retains all
query/candidate recording IDs and source-frame distances, along with distinct query
and pair counts. Entries sort by native IDs, not an invented artist-level score.

Only independently verified MusicBrainz core credits establish artist joins.
All co-credits participate, so an observation may appear under multiple artists;
counts across artists are not additive. Selection-associated artist IDs, names,
uploader descriptions and genre tags never supply joins. Missing credits remain
unassigned and in the global recording denominator. A recording with multiple
credits is not evidence that every credited performer has the same musical style.
No genre classifier exists in this AB178 model: `scope.genre_state` is explicitly
`unsupported_by_ab178_model` and `genre_memberships` is empty. No high-level
classifier predictions are substituted for genres or human listening judgments.

The existing 100-recording/178-coordinate, five-neighbor, 120-second CPU/wall and
1 GB process bounds remain. Artist export additionally caps exact credits at 16
per recording and artist identities at 1,000; oversized cases fail without silent
truncation. The final canonical JSON is capped at 2 MB and published only after
all stages succeed. Temporary queries are discarded. Outputs must be fresh and
outside source/bundle custody. No data acquisition or UI build occurs.

A fresh bounded run on 2026-10-18 replayed all 100 retained nominations into
17 verified credited artists, with 45 recordings lacking verified credits. Its
recording outcomes were 4 emitted fit members, 8 outside-training-support queries,
21 dirty extractors, 22 mismatched versions and 45 HTTP 404s. The only two directed
artist edges are explicitly **fit-member evidence**. There are **zero heldout
artist edges**. This completes a usable artist evidence export; it does not improve
supported heldout coverage or establish EveryNoise parity. The dominant barrier
remains the 12-recording compatible cohort and lack of listener-quality validation.
Genre annotation recovery would require a separately evaluated genre model in a
compatible feature family. FMA518 weights and AB high-level predictions cannot
fill that gap by relabeling the current output.

The checked output is 36,456 bytes with SHA256
`7188ae617b39b86d34d34f664272dae1be78e0c4dee776b8b0bcc96d2e263d91`.
The freshly prepared runtime-pinned bundle SHA256 is
`6c20f1f2786ea6d4fa58bbcf23a3ef8888adee9e62d5f64a722ab3e5eeffc5e2`.
A separate existing `export_queries`/`infer` run matched every exported recording
outcome, role input and neighbor observation across all 100 rows. Query roles are
45 unresolved identities, 4 fit members, 31 heldout-fold records and 20 non-fitted
training-fold records; the latter two counts include incompatible analyses and
must not be read as compatible query counts. The export's inference hash binds
the complete original recording result, including vectors omitted for consumers.
