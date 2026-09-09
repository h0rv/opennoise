# Reviewed alias context model

This local research output adds approved retained tag context to the sealed
MusicBrainz model input. It does not change the baseline seed target artifact,
the baseline model input, or any public serving input.

The source receipt is
`.cache/reviewed-alias-combined-model-v1/receipt.json`. Its logical hash is
`7628ea63478ad454c88c53714ac9b24e84ab0599cdc4fda46c2215bfe2859b5f`.
It binds the following inputs and output.

- Baseline model input logical hash: `ddc5d06c26ca79efa2fe038eea758200bff1528d21db5f2d8927b8aed55f24de`.
- Baseline adapter report: `b14214bbca792a9cb877d0b6760c886d5f01d3783ac93ce667e0b4a4eb53a79b`.
- Sealed seed target artifact: `1cfe14b7dfce41c5f1b45c423407c7c1ad528abbafa3b3b859770e49c8debe46`.
- Reviewed alias context artifact: `9768dee0a7eb25bd951d538f4a1e6e923dbaf0956692961f3950ae9267f42049`.
- Combined model input logical hash: `aed9ac4e8f62a1f34fe5288a569ea9c592df9b7abf662db233687896390dc36d`.

The combined input is at
`.cache/reviewed-alias-combined-model-v1/public-model-input.json`. Its file
hash is `73cb0364df2a6c41c6de1f9ed832776a7937cbb1c8422addeb36eacb3c386959`.

Rebuild the local files with the already materialized baseline input and the
small reviewed context artifact:

```bash
uv run python scripts/materialize_reviewed_alias_combined_model.py \
  --baseline-model-input .cache/musicbrainz-full-seed-targets/pipeline/public-model-input.json \
  --adapter-report .cache/musicbrainz-full-seed-targets/pipeline/musicbrainz-model-adapter-report.json \
  --reviewed-alias-context .cache/reviewed-alias-context-v1/artifact-v1.json \
  --model-input .cache/reviewed-alias-combined-model-v1/public-model-input.json \
  --receipt .cache/reviewed-alias-combined-model-v1/receipt.json
```

The baseline has 421,427 unique stable seed and artist pairs. The reviewed
context has 683 pairs. Five pairs already occur in the baseline, so the
combined input has 422,105 pairs. The additive change is 678 pairs. The
reviewed context rows are observed MusicBrainz artist tags with approved
synonym normalization. They keep their `reviewed_alias_context` lineage, and
the original `direct_anchor` table remains unchanged. They are not album
propagation or learned membership rows.

The deterministic peer build consumed the combined input. Its gate passed with
the existing settings hash
`88a708cd5d0745c87a6c4f164fe8c0d306345ffaa59b87a87aa1b929255eef0f` and
produced artifact hash
`201a5061c2bcd0b71e7d6ac867e8a42d76b3c8cfed0318d88752cfbae12853eb`.
It has 28,713 scored genre pairs. The unchanged baseline build had 28,508.

The build also records 36,752 abstained genre pairs. This is a count of
candidate genre pairs that did not meet the peer support threshold. It is not
a count of seeds, artists, missing memberships, or unsupported genres. The
baseline had 36,654 abstained pairs.

Both inputs have `export_allowed=false`. The peer gate also records
`all_inputs_export_allowed=false`. These files are local research artifacts
only. They must not replace the default public model or serving data.

The peer evaluator used the existing H3 database only after construction. Its
report is `.cache/reviewed-alias-combined-model-v1/peer-historical-evaluation.json`
with hash `ccc0493e414a841383e7a308a77f688083de7011309ae132a63e654a13b8b5b5`.
The evaluation receipt binds the peer artifact and records
`historical_inputs_used_for_construction=false`. It matched 6,289 genres and
measured micro Recall at 25 of `0.2535762686342418` with macro Recall at 25 of
`0.20168792364977695`. H3 is positive-only, so absence is not a negative and
the overlap rate is not a complete precision measurement. This run is not a
measured improvement over the earlier peer result because that result was not
rerun against the same current public database.

The compact local index is
`.cache/reviewed-alias-combined-model-v1/peer-similarity-local-research.sqlite`.
Its file hash is `80e9519a6cf00218ed416ff4c0d6e29c824d52f65bc9ab067f777a7aa637405e`.
It streams the combined peer candidate, binds the matching evaluation receipt,
and does not replace the existing local peer index.

Build the evaluation and index with these local commands:

```bash
uv run python scripts/run_genre_reconstruction_pipeline.py peer-evaluate \
  --candidate .cache/reviewed-alias-combined-model-v1/peer-similarity.json \
  --public-input .cache/reviewed-alias-combined-model-v1/public-model-input.json \
  --public-database data/public.sqlite \
  --historical-database .cache/historical-custody-vault/historical-h3/membership/sha256/098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df.sqlite \
  --output .cache/reviewed-alias-combined-model-v1/peer-historical-evaluation.json \
  --object-store .cache/reviewed-alias-combined-model-v1/objects \
  --receipt .cache/reviewed-alias-combined-model-v1/peer-historical-evaluation.receipt.json

uv run python scripts/local_peer_similarity.py build \
  --artifact .cache/reviewed-alias-combined-model-v1/peer-similarity.json \
  --gate .cache/reviewed-alias-combined-model-v1/peer-similarity.gate.json \
  --historical-receipt .cache/reviewed-alias-combined-model-v1/peer-historical-evaluation.receipt.json \
  --reconciliation .cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json \
  --output .cache/reviewed-alias-combined-model-v1/peer-similarity-local-research.sqlite
```

The current evaluation uses public database hash
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` and
historical database hash
`098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df`.
The earlier report used the same historical database but a different public
database hash. Its result is therefore not a matched baseline comparison.
