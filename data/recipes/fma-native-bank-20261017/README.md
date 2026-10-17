# Offline native FMA feature bank

This adds a reusable full-statistics input bank, not new recordings or independent
assessment data. The retained official FMA `features.csv` has 518 columns: seven
statistics across 74 acoustic channels. The existing 44-mean projection remains
unchanged and keeps its 20 MB output guard. No source acquisition or audio is needed.

The new `fma-native-feature-bank-v1` protocol separately declares a 240,000,000-byte
complete artifact ceiling, 110,000 rows, 300 CPU seconds, 360 wall seconds, and
1,000,000,000 bytes address space. These larger *new-stage* limits cover the expected
220,821,328-byte float32 matrix and parsing all 55 million native cells; existing
model and projection limits are not lifted. Partial outputs have no completion
receipt and must never be treated as completed or resumed.

After `poe sync`, run the script directly (Poe remains the sole task runner):

```sh
.venv/bin/python scripts/project_fma_native_bank.py \
  --source /path/to/retained/feature-source \
  --output /path/to/new/bank \
  --declaration /path/to/frozen/declaration.json \
  --declaration-sha256 EXPECTED_SHA256
```

The declaration binds `revision`, exact `columns` from module `COLUMNS`,
`max_bank_bytes`, `max_rows`, `stage_limits`, the retained `source_receipt_sha256`,
and `native_observed_sha256` from an already verified native projection. The CLI
checks its externally supplied SHA before execution. Call `verify_native_bank`
before consuming a relocated bank; callers also pin the completion receipt hash
in their run protocol rather than treating self-consistency as authenticity.

`features.float32` is row-major little-endian float32; `track_ids.uint32` has one
little-endian unsigned ID per row. The receipt preserves ordered column triples,
per-column missingness, complete native decompressed SHA and ZIP CRC, exact
full-native cell-string duplicate groups, source bindings, CC BY 4.0 attribution,
and artifact hashes. Empty/nonfinite cells become NaN; there is no imputation or
fitting. Full-native duplicate groups are not an artist or recording identity
bridge. Missingness/scaling/model transforms must be fitted on training components
only. Existing reused folds support exploratory development evidence only.

The new verifier enforces a closed artifact inventory, regular bounded metadata,
exact schema/shape, native declaration bindings and all output hashes. Focused
synthetic tests cover original44 byte equivalence, all518 retention, NaNs,
duplicates, corrupted matrices, source digest mismatch with no completion marker,
frozen budget mismatch, prewrite row-byte guards and extra-file rejection.

## Measured local execution

Implementation `492acd6d5e4912b1fa8e4c05754930fc2bd6fdc5` completed the frozen
`declaration.json` (SHA-256
`a3a3fdec2f0993f15c43f6dd7dcdd267608ef425d7da36787720e99ca4ca3dd8`)
in 175.953 wall seconds, with 65,605,632 bytes peak RSS. The output has 106,574
rows, 518 columns, zero missing cells, and 1,689 full-native duplicate groups.
The 220,821,328-byte matrix SHA-256 is
`00a64ffc7507a5c4ac447d4411a561f242e084d8869591ef8b86059d01ea9d30`;
the 426,296-byte identity array SHA-256 is
`8fb77ce50f3da09b7fb7c04bfc21948ef72e3dd50dbb63cd082291d75b180c07`.
The completed receipt SHA-256 is
`d2c75efb572250c4eabf5c0d19c215ca5d384ec8c89e06d9498fe987b43c6680`.
It verifies all 951,117,185 decompressed source bytes with native ZIP CRC
`e8eb7a19` and SHA-256
`a035d04941e15fc3240aadd6880c519471d218329bbfe0e82c17553ba50e9e16`.

Local artifacts: `/workspace/opennoise-native-bank-run-20261017/bank`;
execution measurements and immutable source-code bindings are alongside the bank.
These paths are local evidence, not promised public downloads. No raw source or
matrix is committed to Git. Broader experimental model results are separate;
this feature-bank change makes no accuracy or independent-test claim.
