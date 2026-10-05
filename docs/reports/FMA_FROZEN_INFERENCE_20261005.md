# Frozen FMA track-ID inference

The reviewed training-only model can now answer explicit native FMA track-ID
requests without running the fitting/calibration pipeline. This is a practical
local export path, not a new experiment or a model-quality improvement.

```sh
.venv/bin/python scripts/infer_fma_tracks.py \
  --pack /path/to/portable/pack \
  --features /path/to/portable/features \
  --track-id 2 --track-id 999999 --track-id 2 > suggestions.jsonl
```

Each input produces one JSONL record, in requested order; duplicate IDs produce
identical records. Each record includes the existing source-model namespace,
bounded memberships, rank-based sensitivity flags, abstention, original query
role and provenance hashes. No query source labels are consumed or emitted as
facts. Musical probabilities and musical calibration remain explicitly unavailable.
Outputs for original fitting queries are not held-out performance evidence.

The small API is `opennoise.ml.fma_inference.infer_tracks(pack, features, track_ids)`;
`encode_jsonl(records)` produces deterministic, size-checked JSONL. The CLI writes
stdout after validation and reports failures to stderr with exit code 2. It has
no managed output-file option; ordinary shell redirection has normal overwrite
semantics, so choose a new output path when preserving an earlier export.

Required portable files, all retained from the previously reviewed artifacts:

- `pack/`: `evaluation.json`, `model.npz`, `thresholds.json`,
  `native-roles.jsonl.zst`, `declaration.json`, `pre-diagnostic-seal.json`.
- `features/`: `projection-receipt.json`, `features.float32`, `track_ids.uint32`.

Paths are caller-supplied. No raw captures, target labels, rank exports, native
metadata corpus or audio are needed. The model evaluation receipt is pinned to
`67228714920a686a2893e778c01406c8f5ee01344d389b1e4a00e414a32b8781`;
the feature projection receipt is pinned to
`8462edb5aab5642c92b3b5734fc01f09c3bf919fe22d5b5e3b87440bc0720eab`.
Those trusted receipts bind every consumed payload and the three live scoring
modules. Source snapshots are never executed. Changed receipts, payloads or
scoring code fail closed; this command intentionally supports this frozen pack.

Requests accept 1–100 positive uint32 IDs, counting duplicates. Unknown native
IDs abstain, followed in precedence by unresolved artist, missing feature row,
and numerical missingness/out-of-support. A valid score with no supported
membership also abstains. The 32 calibrated-label thresholds, unsupported-label
abstentions and 20-membership cap remain unchanged.

Limits are 25 MB total bound input, 2 MB output, 1 GB address space, 30 seconds
CPU/wall time and one numerical worker thread. The API enforces request/input/
output caps and cooperative wall checks; the CLI additionally applies OS memory,
CPU and alarm limits. The exported bytes are constructed before stdout is touched;
input/validation failures emit no JSONL records.

Tests cover ordering, duplicates and rank ties; all abstention paths; strict ID
and 100/101-query boundaries; every consumed file's hash; scoring-code drift;
symlink rejection; portable loading without target/rank/capture files; prohibited
fit/calibration calls; resource limits; and CLI output/error behavior. Native
saved-output equivalence is checked separately against immutable retained records,
without selecting parameters or recomputing performance metrics.

Independent native verification checked 942 of the 25,095 retained scored queries:
100 evenly spaced records per cohort plus all 648 saved abstentions (636 missing
feature rows and 12 outside fitted support). All selected membership records match
exactly; their complete ranks were independently recomputed. Another 22 requests
cover original-fit, unresolved-artist and unknown IDs. This is sampled agreement,
not a claim that the CLI replayed every retained query. Portable loading, ordered
duplicates, determinism, and rejection of all nine corrupted input files passed.
Runtime guards prohibited fitting, threshold fitting and raw-source loaders.
