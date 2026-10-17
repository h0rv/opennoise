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
