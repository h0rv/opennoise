# Local waveform pipeline for the reviewed 55-recording sample

This recipe connects verified local MP3 bytes to 52 deterministic descriptors, a
training-only two-axis PCA map, raw-descriptor neighbors and source-tag diagnostics.
There is no classifier, new acquisition or model selection using heldout results.
The saved historical FMA44-feature Gaussian model is separate evidence and is not
used as this model's training data or claimed to describe these new 52 features.

The input is the reviewed, selected 55 sample, not a random representative sample.
Original component folds are preserved: 47 training, 2 validation and 6 test clips.
These folds were previously inspected, so results are not fresh confirmation.
Observed tags are incomplete; neither agreement nor geometry establishes musical
relevance or genre truth. All per-query outcomes and unsupported cases are retained.

`protocol.json` is the independently reviewed v3 scientific protocol. It records
exact extraction, fitting, pool, abstention, covariance, metric and resource rules.
The producer freezes code, decoder executable/version, Python/NumPy versions, all
55 MP3 hashes, manifest, and the minimized saved component roster before extraction.
The stage is offline and serial, with 120-second CPU/wall, 1 GB memory and 100 MB output
limits. Decoder stdout/stderr are streamed with hard caps and 20-second timeout;
full successful completion is required. No silent truncation or cap increase occurs.
Actual extraction requires an already-installed local FFmpeg executable. Source
tests always exercise bounded pipes and child-process failures using explicit
synthetic processes; the separate codec integration test skips when FFmpeg is
absent. The recorded real-audio run and independent replay both used FFmpeg.

Use the locked repository environment (`poe sync` first). Only the reviewed
55-recording candidate and minimized component ledger are input data; archived
44-feature arrays and the historical 133-recording website are not needed.
Choose a fresh output directory and substitute your retained input paths:

```sh
PRIOR55=/path/to/reviewed-55-candidate
MINIMIZED=/path/to/minimized-model-inputs
FRESH=/path/to/new-waveform-run
mkdir "$FRESH"
PYTHONPATH=src .venv/bin/python scripts/rebuild_fma_public_candidate.py \
  --prior "$PRIOR55" --output "$FRESH/candidate" \
  --manifest-sha256 242505b6c393185bdca4925b3ee97eb579fac93746091e8b0675809c8c0286cf
SITE55="$FRESH/candidate"
PYTHONPATH=src .venv/bin/python scripts/run_fma_waveform_pipeline.py freeze \
  --site "$SITE55" --folds "$MINIMIZED/saved-replay/native-folds.jsonl.zst" \
  --protocol data/recipes/fma-waveform55-20261016/protocol.json \
  --declaration "$FRESH/declaration.json"
PYTHONPATH=src .venv/bin/python scripts/run_fma_waveform_pipeline.py run \
  --declaration "$FRESH/declaration.json" --output "$FRESH/pack"
PYTHONPATH=src .venv/bin/python scripts/run_fma_waveform_pipeline.py verify \
  --site "$SITE55" --output "$FRESH/pack"
```

`features.npz` contains sorted native IDs and 55 × 52 float64 values. `model.npz`
contains training center, population scale, active columns, eigenvalues, signed
axes and projection availability. `evaluation.json` preserves all 55 query rows
and separate validation/test aggregates. `layout.json` supplies all 55 track rows
and all 93 source genre definitions, including unplaced/unsupported cases and
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
candidate validation gate or import historical 133-site content. Public deployment
is not authorized by this local recipe.

## What the stages mean

| Stage | Source of the result |
| --- | --- |
| Names, credits, licenses and direct genre tags | Supplied source metadata, retained under the reviewed candidate gate |
| 52 acoustic descriptors | Fixed signal processing of the actual local audio |
| Center, scale and two PCA axes | Fitted on the 47 original training clips only |
| Suggested excerpts | Fixed cosine ranking after training normalization; component exclusions and diversity are deterministic |
| Genre positions | Centroids of eligible training clips with supplied tags and at least three distinct training components |
| Display and selection rules | Explicit design choices, not learned genre facts |

PCA supplies the required two-dimensional geometry. A classifier is not justified
by this tiny sample with 93 sparse source tags. The map does not determine the
suggestion ranking, and no setting was selected using the held-out results.

## Recorded bounded run, 2026-10-16

All 55 clips produced finite 52-column feature rows. The run took 7.97 seconds and
78,913,536 bytes peak RSS, within the unchanged limits. It produced 55 track
positions, 13 supported genre centroids and 330 suggested links. All other source
genres remain available in the directory without a centroid.

| Diagnostic | Raw descriptors | PCA projection | Native-ID baseline |
| --- | --- | --- | --- |
| Test queries with any source-tag match in top 1 | 0 / 6 | 0 / 6 | 0 / 6 |
| Test queries with any source-tag match in top 3 | 0 / 6 | 0 / 6 | 0 / 6 |
| Validation queries with any source-tag match in top 3 | 1 / 2 | 1 / 2 | 0 / 2 |

One test query and one validation query have no training-observed source tags.
They remain in the reported totals; their known-tag recall denominator is null.
All-observed-tag recall is zero for all three test arms. These results do not
support a claim of useful musical recommendations. No tuning followed them.

An independent implementation re-decoded every clip, recomputed the descriptors,
used a separate SVD calculation for PCA, and checked all 165 full rankings and all
metrics/coordinates/centroids. It passed in 18.58 seconds with maximum feature
absolute error below 1e-13 and no ranking mismatch. A second producer run made all
eight pack files byte-identical, including the inventory.

The reviewed run inventory SHA-256 is
`829f3f80308149fe03adfd582c45a50168b67eb61fe5ce82e2556e5ce208f729`.
Use that pin only for these exact pack bytes. A new run must be independently
reviewed and use its own expected inventory hash; reading a pack's own hash is
not an authenticity check. The standalone independent replay harness and its
reports are retained with the run evidence, separately from the producer code.

The executable pipeline is a small technical reproduction: verified input,
waveform extraction, train-fitted representation, evaluated deterministic
retrieval, reproducible map and playable static discovery. It is not a parity
percentage, production deployment, representative benchmark or musical-quality
validation. Scaling, better evidence and listener evaluation remain future work.
