# Selective numeric recovery port, 2026-10-03

Source patch: 139,159 bytes, SHA256
`b4a67e1ccb52e002002677d7e9c2ede0f812e1dc1f8560db72e2e7799a6138db`.
The [recovery handoff](https://chatgpt.com/space/page_63f9af5ecd7c81919df309cc4807e2e7)
was reviewed as an input. Four new-file sections were extracted as inert text and
reviewed individually: generic connected splitting, its identity/numeric CLI,
recording-credit example CLI, and connected-split tests. This does not apply or
publish the original branch, import its explorer, replace the native FMA adapter,
or alter existing models, folds, source packs or release paths.

## Distinct capability retained

`TrackIdentity` supplies namespaced track IDs and any number of artist, album,
canonical recording and duplicate IDs. A track connects transitively through every
supplied identity; it never substitutes one selected artist for multiple credits.
Namespaces and identity kinds remain distinct, and empty groups are unknown rather
than shared sentinel nodes. An independent audit checks literal cross-partition
identity intersections without trusting component IDs. Whole-component hashing
uses a prescribed seed and bucket counts; it makes no balance or nonempty guarantee.

The raw-input seal binds byte SHA256/length/format and canonical normalized
identities. Numeric features and labels are sealed as bytes and do not enter
component construction. Verification independently reconstructs every assignment,
component, hash and audit using the caller's separately retained seed and buckets.
Tests show that changed numeric bytes with identical identities fail the old seal;
rehashed manifests with changed assignments fail even with a clean overlap audit;
and a post-hoc seed cannot pass verification under the prescribed seed. Hashes
establish input custody, not source truth, rights or complete identity resolution.

```sh
.venv/bin/python scripts/build_connected_track_split.py \
  --source SOURCE.json --input-format numeric --seed PRESCRIBED_SEED \
  --output .cache/connected-split-v1.json
.venv/bin/python scripts/build_connected_track_split.py \
  --source SOURCE.json --input-format numeric --seed PRESCRIBED_SEED \
  --output .cache/connected-split-v1.json --verify
.venv/bin/python scripts/build_recording_fact_split.py --pack-kind native-sonic \
  --output .cache/native-recording-split-v1.json
```

Writers require a fresh output. The last command first replays retained native
AcousticBrainz identity/numeric responses and independent MusicBrainz core credits;
it uses only canonical recording IDs and all exactly credited artists for grouping.
The retained cohort selects 100 recordings, of which 55 have accepted verified
source/credit joins. Those 55 form nine components (largest ten), with 38/4/13
train/validation/test tracks under the stated example seed. All 55 lack supplied
album and duplicate groups. This is an identity-isolation example with
`evaluation_ready=false`; no feature fitting, genre labels, inherited artist
memberships, musical evaluation or publication is inferred.

## Current FMA contracts checked and preserved

The patch's separate centroid evaluator and numeric-evaluation script were not
ported. The current FMA Gaussian path already has a prespecified model, training-only
normalization/support fitting, feature abstention and source/declaration custody.
Adding the older centroid implementation would introduce another experiment and a
different missing-feature policy, rather than fix the established model.

Focused current-model tests change held-out features, held-out labels and unlabelled
target rows, then compare every fitted numeric parameter and support mask exactly.
They verify unknown holdout labels keep query coverage without inventing positives
or negatives; missing-feature queries retain their source-positive denominators;
rare and training-unseen targets retain their zero-hit counts; precision stays
unavailable because source absence is unknown. The existing saved-rank replay was
also run: validation keeps 7,332 queries, including 79 unlabelled, and 16,668 observed
positives; test keeps 6,468 queries, including 99 unlabelled, and 14,402 positives.
Unlabelled rows have no observed positive denominator, not fabricated negatives.

A read-only actual-source comparison rehashed the native metadata projection and
used its supplied artist/album/full-native-feature duplicate identities. Generic
component membership exactly matched all 7,410 current native components across
109,727 metadata tracks. An independent identity audit passed for the existing
native hash assignments, without replacing them with the generic splitter's hash
policy. Source-unresolved positive artist IDs remained graph bridges. Current
model eligibility still excludes 974 unresolved-artist tracks and their 2,075
source positives explicitly; this exclusion is not hidden in a successful isolation
claim. Missing features for eligible held-out artists remain zero-hit queries.

The independent [full native audit](FMA_INDEPENDENT_AUDIT_20261003.md), commit
`ee6e2a112f5a8fe03de08cb21f665ee1d01068a0`, separately checks the full native fit,
folds, ranks, saved target rows and metric replay. This port did not rerun or tune a
new FMA experiment. The preserved model and declaration implementation hashes are
recorded in [the port evidence](NUMERIC_RECOVERY_PORT_20261003.json).

Validation: 24 focused tests passed, including retained FMA tests and saved-rank
replay; all changed Python files pass formatting, Ruff and ty. Native component
comparison and the 55-recording structural example used fresh temporary outputs.
Full-suite integration validation belongs to the combined root checkout because
this temporary worktree checks out only the required source/tests/input packs.
