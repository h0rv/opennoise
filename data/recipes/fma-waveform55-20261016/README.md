# Local waveform pipeline for the reviewed 55-recording sample

This recipe connects verified local MP3 bytes to 52 deterministic descriptors, a
training-only two-axis PCA map, raw-descriptor neighbors and source-tag diagnostics.
There is no classifier, new acquisition or model selection using heldout results.
The saved historical FMA44-feature Gaussian model is separate evidence and is not
used as this model's training data or claimed to describe these new52 features.

The input is the reviewed, selected55 sample, not a random representative sample.
Original component folds are preserved:47 training,2 validation and6 test clips.
These folds were previously inspected, so results are not fresh confirmation.
Observed tags are incomplete; neither agreement nor geometry establishes musical
relevance or genre truth. All per-query outcomes and unsupported cases are retained.

`protocol.json` is the independently reviewed v3 scientific protocol. It records
exact extraction, fitting, pool, abstention, covariance, metric and resource rules.
The producer freezes code, decoder executable/version, Python/NumPy versions, all
55 MP3 hashes, manifest, and the minimized saved component roster before extraction.
The stage is offline and serial, with120-second CPU/wall,1GB memory and100MB output
limits. Decoder stdout/stderr are streamed with hard caps and20-second timeout;
full successful completion is required. No silent truncation or cap increase occurs.

Run from the repository with its locked environment (explicit paths abbreviated):

```sh
PYTHONPATH=src .venv/bin/python scripts/run_fma_waveform_pipeline.py freeze \
  --site "$SITE55" --folds "$MINIMIZED/saved-replay/native-folds.jsonl.zst" \
  --protocol data/recipes/fma-waveform55-20261016/protocol.json \
  --declaration "$FRESH/declaration.json"
PYTHONPATH=src .venv/bin/python scripts/run_fma_waveform_pipeline.py run \
  --declaration "$FRESH/declaration.json" --output "$FRESH/pack"
PYTHONPATH=src .venv/bin/python scripts/run_fma_waveform_pipeline.py verify \
  --site "$SITE55" --output "$FRESH/pack"
```

`features.npz` contains sorted native IDs and55x52 float64 values. `model.npz`
contains training center, population scale, active columns, eigenvalues, signed
axes and projection availability. `evaluation.json` preserves all55 query rows
and separate validation/test aggregates. `layout.json` supplies all55 track rows
and all93 source genre definitions, including unplaced/unsupported cases and
explicit reasons. Genre centroids require three eligible training components;
all-training and eligible-training support counts are distinct. Raw cosine ranking
uses training candidates only, excludes the full query component and keeps one
candidate per component; PCA2 never supplies serving neighbors.

`receipt.json` binds the declaration, feature/model/evaluation and protocol files.
The layout binds that receipt, and the closed inventory hashes every artifact.
Portable validation replays saved numerical results and source scope. It cannot
alone prove waveform extraction happened: an independent numerical replay and an
explicitly reviewed inventory hash establish the actual run before site export.

After independent replay, the separately implemented static exporter accepts the
reviewed inventory hash; it preserves candidate credits and audio unchanged:

```sh
PYTHONPATH=src .venv/bin/python scripts/build_fma_waveform_site.py build \
  --candidate "$SITE55" --pack "$FRESH/pack" --output "$FRESH/site" \
  --pack-inventory-sha256 "$REVIEWED_INVENTORY_SHA256"
PYTHONPATH=src .venv/bin/python scripts/build_fma_waveform_site.py verify \
  --site "$FRESH/site" --pack-inventory-sha256 "$REVIEWED_INVENTORY_SHA256"
```

The static exporter is a separate integration; it does not broaden the original
candidate validation gate or import historical133-site content. Public deployment
is not authorized by this local recipe.
