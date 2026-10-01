# Source-based artist feature enrichment, 2026-09-30

A separate sparse association model predicts missing musical style features
from observed proper genres and tags. It complements the community hierarchy;
it does not turn predictions into MusicBrainz facts or use them as independent
source observations for that hierarchy. Names, historical Every Noise data,
and audio do not participate in construction.

Training collapses duplicate musical values across source facets. Sparse
cue-to-target associations require at least two jointly observed artists and
use source-degree correction, rarity weighting, smoothing, and a stronger
proper-genre cue weight. Each cue retains at most 128 targets. Query values are
excluded from predictions. Profiles without musical evidence abstain. Scores
are uncalibrated. Explanations identify observed query cues and their retained
source references, with exact training joint, cue, and target artist counts.
Two cue roles for the same value are model weights, not independent observations.

The nested evaluation declares a new outer evidence-component split and an
inner split before testing. This is a new split of a previously explored corpus,
not independently obtained genre gold. Outer targets are removed before inner
fitting; vocabulary, support, and associations use training evidence only.
Inner validation selects smoothing 4 from the declared candidates 4, 16, 64.
Degree power 0.5, rarity power 0.15, genre boost 2, joint support 2, and 128
neighbors stay fixed. All cold and unseen positives remain in the denominator.

On 85,755 outer positives, overall Recall@10 is 45.83%, versus 56.99% for the
conditioned proper-genre baseline and 28.14% for global frequency. The model
abstains on 25,769 cold positives; the conditioned baseline guesses 11,481 of
those correctly. On 8,015 tag-only positives, enrichment is 24.12% versus
16.48% for the conditioned baseline. On 17,880 positives with exactly one
observed musical value, it is 68.18% versus 65.40%. Rare training-support-at-most-5
targets remain weak, 2.71% versus 0.67%. Removing the reported cold stratum gives
65.51% versus 62.33% for the remaining positives; this is post hoc arithmetic,
not the selection criterion. No fallback or hyperparameter was changed after
the outer result.

The independent audit replays both split files byte-for-byte, the selected
training-only sparse association and support matrices, all 198,409 artist
rankings, all three scorers, and the inner selection rule. Evidence remains in
`.cache/artist-feature-enrichment-nested-v1` and
`.cache/artist-feature-enrichment-nested-v1-independent-audit.json`. The original
implementation snapshots are retained. Later serialization and batch-export
hardening leave statistical fitting and ranking unchanged.

The latest full fit uses the cleaned primary-corpus feature cache, not the
older evaluation input. It has no new predictive test claim. Source SHA-256:
`0c298b1241b03e642dbc7b13981f59b9008cb1fdc4e01186b5fe55e7f2c78748`.
The `.cache/artist-feature-enrichment-primary-v2` export has 198,409 rows,
198,348 artists with supported suggestions, 61 explicit abstentions, and
594,776 top-three suggestions. Its 256 source shards are joined into the
explorer's 4,096 artist-prefix shards. It binds the selected settings,
source/model identity, frozen code, and every output byte. Prediction receipt:
`c987e91f4de32dc7d254f9d1e69ddf8185dd5bbae0503c73e9f67dcb6575d63c`.

The final explorer at `.cache/community-explorer-enriched-clean-20260930-final`
shows the cleaned adaptive hierarchy and suggestions separately from direct
source observations. It preserves actual skipped resolutions and marks the
unsupported coarse cores as candidates. All ten exact reference artists,
including Aphex Twin and Four Tet, have source data and fine assignments;
weak affinities still appear. Three suggestions are shown for each of those
two artists without describing them as verified genre memberships.

Final explorer receipt:
`6228934743a67c9408e39c3f2dc30f1198da48029be675713ab96af9c59901ec`.
Independent Chromium and artifact evidence is at
`.cache/community-ui-browser-enriched-clean-20260930-final`: nine screenshots,
14,377 verified output files, all 18 feature-source input bindings,
198,409 assignment/prediction rows, 780,893 overlapping memberships,
594,776 suggestions, 1,242 community metadata rows, 1,238 offline positions,
and 30,015 exact postjoined source profiles. The observed local ready time is
363 ms, not a production percentile. All 34 browser requests are local; no
external/media requests or runtime errors occurred.

Source tag and genre associations carry CC BY-NC-SA obligations. Research
artifacts remain local and noncommercial; no preview is deployed. Positive-only
metadata reconstruction cannot establish listening relevance, independent
microgenre validity, or 100% Every Noise parity.

```sh
.venv/bin/python scripts/export_artist_feature_proposals.py \
  --features .cache/microgenre-features-primary-v2/artist-features.jsonl \
  --selection .cache/artist-feature-enrichment-nested-v1/selected-before-outer-scoring.json \
  --output .cache/artist-feature-enrichment-new-run
.venv/bin/python scripts/build_local_community_preview.py \
  --source .cache/parity-source-explorer-20260930-v3 \
  --model .cache/emergent-topics/adaptive-lexical-primary-clean-20260930-v1 \
  --features .cache/microgenre-features-primary-v2/artist-features.jsonl \
  --enrichment .cache/artist-feature-enrichment-new-run \
  --output .cache/community-explorer-enriched-new-run
```

Use fresh output paths; research builders refuse to overwrite earlier runs.
