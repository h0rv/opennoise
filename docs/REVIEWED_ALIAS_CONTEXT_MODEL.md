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
