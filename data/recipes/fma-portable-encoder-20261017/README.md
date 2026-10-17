# Portable frozen encoder inference

This additive backend exports one explicitly selected, already fitted development
encoder and its exact saved candidate pool. It never fits or calibrates a model.
An engineering example may use `linear518 --fold 0`; that choice is not a serving
promotion or a final model trained on the full corpus. The existing Gaussian
inference command remains unchanged.

The portable bundle contains the unchanged model arrays, candidate features,
vectors and observed source tags, and a minimal native identity/component/role
roster. Its external manifest SHA binds the ordered feature schema, original
source/model/stage hashes, numerical environment and inference implementation.
Candidate labels are used only for positive vote transfer. Query labels are never
accepted or consumed. Source-tag ranks are not calibrated probabilities or verified
musical similarity.

## Build once from verified retained inputs

Use the locked Python 3.13 environment and the checkout's `src` import path. No
network, audio acquisition or model fitting is involved:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/run_fma_portable_encoder.py export-bundle \
  --pipeline /retained/completed-backend --inputs /retained/input-root \
  --plan-sha256 PLAN_SHA --checkpoint-sha256 FINAL_CHECKPOINT_SHA \
  --arm linear518 --fold 0 --output /new/encoder
```

Preserve the returned SHA outside the artifact. Export requires the original
verified execution inputs; subsequent inference does not.

For a small exact native-ID query pack:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/run_fma_portable_encoder.py export-queries \
  --bundle /new/encoder --bundle-sha256 BUNDLE_SHA \
  --bank /retained/native518 --track-id 2 --track-id 5 --output /new/native-queries
```

The bank must match the bundle's exact receipt and schema. Missing or unknown IDs
remain explicit rows. This command copies no query source labels.

## Compatible external rows

External rows use a distinct namespace and positive uint32 IDs; an external ID
numerically equal to an FMA ID is not the same identity. The input schema is
`fma-compatible-external-rows-v1`, with the exact ordered 518 native FMA columns,
a named extractor/version, a source-manifest SHA, license and attribution. A
178-column AcousticBrainz vector or another coordinate system is incompatible;
matching dimensions alone do not establish matching extraction semantics.

The following creates an explicitly synthetic request using one retained feature
row under a new identity. It is an API demonstration, not new music or independent
model validation:

```sh
BUNDLE=/new/encoder REQUEST=/new/synthetic.json PYTHONPATH="$PWD/src" .venv/bin/python - <<'PY'
import hashlib, json, os
from pathlib import Path
import numpy as np
bundle = Path(os.environ['BUNDLE'])
manifest = json.loads((bundle / 'manifest.json').read_text())
with np.load(bundle / 'candidates.npz', allow_pickle=False) as saved:
    features = saved['features'][0].tolist()
request = {
    'revision': 'fma-compatible-external-rows-v1',
    'namespace': 'synthetic/portable-api-example',
    'columns': manifest['columns'],
    'extractor': 'Synthetic copy of a retained native FMA feature row; no new extraction',
    'source_manifest_sha256': hashlib.sha256((bundle / 'manifest.json').read_bytes()).hexdigest(),
    'license': manifest['license'], 'attribution': manifest['attribution'],
    'rows': [{'id': 1, 'features': features, 'fma_component_id': None,
              'identity_evidence_sha256': None}],
}
path = Path(os.environ['REQUEST'])
with path.open('x') as stream:
    json.dump(request, stream, allow_nan=False)
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
```

Import with that exact input hash:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/run_fma_portable_encoder.py import-queries \
  --bundle /new/encoder --bundle-sha256 BUNDLE_SHA \
  --source /new/synthetic.json --source-sha256 REQUEST_SHA --output /new/external-queries
```

Each row must have exactly `id`, `features`, `fma_component_id` and
`identity_evidence_sha256`. Missing feature values are JSON `null`. No imputation
is performed. The importer preserves source-file and canonical row hashes.

An optional caller-declared FMA component must name an existing component and
supply an evidence SHA. Such a declaration is explicitly unverified; it is not
proof of identity or independent heldout status. Without a component, a supported
row receives an embedding but no neighbors by default.

## Inference, relocation and replay

Copy only the bundle and query pack to another directory or machine with the same
locked environment and implementation. The following reads neither the original
bank nor the historical run paths:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/run_fma_portable_encoder.py infer \
  --bundle /moved/encoder --bundle-sha256 BUNDLE_SHA \
  --queries /moved/external-queries --query-sha256 QUERY_SHA --output /new/result.json
```

For genuinely new external rows with unknown identity relations, explicitly add
`--allow-unverified-neighbors` to request cosine retrieval without component
exclusion. Results retain `identity_status: unverified`,
`component_exclusion_verified: false`, null fit/fold claims, and the policy flag
in provenance. This option does not override missing/nonfinite/out-of-support
features or native identity guards. Do not use these matches as evidence of
component-independent evaluation. Replay must use the same policy:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/run_fma_portable_encoder.py replay \
  --bundle /moved/encoder --bundle-sha256 BUNDLE_SHA \
  --queries /moved/external-queries --query-sha256 QUERY_SHA \
  --result /new/result.json --result-sha256 RESULT_SHA
```

Native queries exclude their own ID and entire known component. Declared external
components exclude that component but remain caller declarations; numeric ID
collisions across namespaces do not cause self-exclusion. Ties use native candidate
ID, and retrieval returns at most ten candidates. `embedding_reason` and
`neighbor_reason` are separate: a valid embedding survives an unresolved identity
or an empty eligible candidate pool. Known fit-member queries are flagged and
must not be described as out-of-fold evaluation.

Each CLI has 120-second CPU/wall and 1,000,000,000-byte address-space guards with
one BLAS thread. Bundles are at most 10 MB; query packs and result JSON are at most
2 MB, with at most 256 requested rows and 2,048 frozen candidates. NPZ headers
are checked against actual bounded payloads before allocation. Artifacts have
closed inventories and external manifest pins; failed bundle validation leaves a
pending marker rather than a completed manifest. Fresh outputs cannot overlap
input packs or traverse symlink ancestors. These are local research artifacts;
exporting them does not itself grant public redistribution clearance.

## Checked engineering demonstration

The retained `linear518`, fold-0 model was exported without fitting into a
7,408,053-byte bundle containing 1,987 frozen candidates and 109,727 native
identity entries. Six retained rows each produced an eight-dimensional embedding
and ten neighbors. Four explicitly synthetic rows exercised a numeric ID collision
across namespaces, unknown component identity, out-of-support features and null
features. The two supported synthetic rows kept the same embeddings in both
retrieval modes; unknown-identity retrieval occurred only with the explicit opt-in.

All three result variants were byte-identical after relocation. File-access traces
showed no reads of the original experiment, corpus or feature-bank paths. A modified
query payload was rejected without creating a result. A separate implementation
verified candidate data, the whole identity roster, query materialization and all
result variants with zero vector or distance differences; the original model bytes
were unchanged. Aggregate hashes and timings are recorded in `results.json`. The
real batch took 0.379 seconds on this executor; this is an observation, not a latency
guarantee. No model was fitted, calibrated or promoted.
