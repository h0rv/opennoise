# Learned label alignment

This is a review-only experiment for the portion of the stable seed universe
that remains unresolved after reconciliation. It consumes the sealed
MusicBrainz seed-target artifact and the sealed reconciliation artifact.

Direct exact or normalized MusicBrainz tag evidence in the full target corpus
is an observed anchor. Those anchors supply positive supervision and are never
emitted as learned candidates, even if a narrower reconciliation snapshot had
left their seed unresolved. The model scores only reconciliation-unresolved
seeds without such an observed tag anchor.

The two producer-level seed-input hashes are retained in the output, but they
are not assumed to be in the same hash domain. The build instead requires the
same source ID, source-content hash, and stable fingerprint of sorted
`(source_item_id, source_external_id, seed_name)` rows.

Each score combines transparent lexical and support features. Candidates are
review queue entries, not observed identities, artist memberships, hierarchy
edges, or automatic taxonomy promotions. The artifact records the train and
held-out seed-split metrics, direct-anchor coverage, remaining review coverage,
and every abstention.

Run it after the target and reconciliation artifacts are available:

```bash
uv run poe build-learned-label-alignment
```

The task requires `OPENNOISE_MB_SEED_TARGET_ARTIFACT`,
`OPENNOISE_SEED_RECONCILIATION_OUTPUT`,
`OPENNOISE_LEARNED_LABEL_ALIGNMENT_OUTPUT`,
`OPENNOISE_LEARNED_LABEL_ALIGNMENT_OBJECT_STORE`, and
`OPENNOISE_LEARNED_LABEL_ALIGNMENT_RECEIPT`.

## Full-corpus checkpoint

The sealed full-corpus run retained 2,377 directly observed tag-anchor seeds
from the complete target artifact. Of 3,072 reconciliation-unresolved seeds,
2,310 remained genuinely unanchored and were eligible for review. The
deterministic seed-level split trained on 1,889 positives and 7,556 hard
negatives (log loss 0.48172), then evaluated on 488 positives and 1,952 hard
negatives (log loss 0.48185).

At the configured review threshold of 0.5, it emitted zero candidates and
2,310 abstentions; best scores ranged from 0.18273 to 0.21738. Validation also
made zero thresholded predictions, so precision is undefined and positive
recall is zero. This is a calibrated no-promotion result, not evidence that
the absent memberships or identities are negative.

The logical artifact hash is
`abb83ea6ec8ab862528c613451f5ebb6471833b6dd488fccfbc40913513a0864`.
