# Conservative MusicBrainz peer layout holdout

This is a local-only, open-data geometry diagnostic. It neither changes the
sealed v3 layout nor asserts validated musical similarity. The 6,291 retained
IDs remain 2,945 placed and 3,346 explicitly unplaced.

## Fixed conservative unplaced candidate: holdout unavailable

The fixed candidate
`.cache/musicbrainz-peer-threshold-sensitivity-v1/conservative-peer-candidate-v2.json`
was read with the current v3 atlas as read-only anchors. It retains 1,497
overlap-one direct-artist edges after the predeclared sole-artist degree-below-
ten control. Its endpoints include 509 placed and 414 unplaced IDs, but **zero
of its edges join two placed IDs**. Consequently no placed target has a
conservative peer anchor after its own coordinate is held out.

The leakage-safe neighbor-centroid holdout and its leave-one-out global-centroid
baseline are therefore unavailable for this candidate. It has 405 directly
reachable unplaced IDs, but this is coverage only, not validation. The report
intentionally emits no proposed coordinates and abstains on all 3,346 unplaced
IDs.

The report is
`.cache/conservative-musicbrainz-peer-layout-holdout-v1/report.json`, logical
SHA-256 `91880f215778ae1c5fdba60278574ea892c59dd70596d21eae98cdb225fc06e4`.
Its reader requires the pinned v3-layout byte hash
`e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972`, the
pinned conservative-candidate byte hash
`b605e855681bab1c8b17a7e67dd66f128b00dd4acc6ba1bcde05a9629361c028`, exact
2,945/3,346 disjoint layout counts, and the fixed 1,497-edge / 509-placed-
endpoint / 414-unplaced-endpoint frontier before evaluation. Report output is
created with `O_EXCL`, so a competing process cannot replace a receipt.

## Separate fixed placed-peer diagnostic

To test whether the already frozen baseline direct-peer graph has useful atlas
geometry, a separate replay read
`.cache/musicbrainz-full-seed-targets/pipeline/peer-similarity.json`. Its
pinned input hash is
`ddc5d06c26ca79efa2fe038eea758200bff1528d21db5f2d8927b8aed55f24de` and its
settings hash is
`88a708cd5d0745c87a6c4f164fe8c0d306345ffaa59b87a87aa1b929255eef0f`.

Every retained edge has at least two shared direct artists, which satisfies the
same conservative predicate without taking the singleton exception branch.
All 28,508 frozen edges join placed nodes. For each target, its coordinate was
excluded from both the peer-centroid estimate and the global-centroid baseline.
There were 1,580 evaluable targets:

| Metric | Direct-peer centroid | Leave-one-out global centroid |
| --- | ---: | ---: |
| Mean Euclidean error | 0.17749994 | 0.31024221 |
| Median Euclidean error | 0.04664457 | 0.15328932 |

The peer estimate beat that baseline for 1,420 targets; the mean error
difference was 0.13274227. This shows only that the fixed minimum-two
direct-artist graph is geometrically aligned with existing anchors under this
holdout. It does not validate the sparse 1,497-edge unplaced candidate, does
not authorize transfer to its 405 reachable unplaced IDs, and is not a quality,
similarity, publication, or map-placement claim.

The separate report is
`.cache/conservative-musicbrainz-peer-layout-holdout-v1/baseline-placed-report.json`,
logical SHA-256 `2e49f33cf57089667334fb74319149a67d2407c6c11b6933e1f50142fb413650`.
Its reader also pins the baseline bytes to
`1991cac3a084d2f02bd56c090fef7cadca263d6953a9aaaaee13425b1813bb39`, requires
the same disjoint v3 layout counts, and rejects any replay not yielding exactly
28,508 placed-to-placed edges. It uses the same atomic no-replace output rule.

Reproduce the two no-overwrite reports:

```sh
.venv/bin/python scripts/evaluate_conservative_musicbrainz_peer_layout_holdout.py \
  --layout .cache/semantic-map-layout-v3/artifact.json \
  --candidate .cache/musicbrainz-peer-threshold-sensitivity-v1/conservative-peer-candidate-v2.json \
  --output .cache/conservative-musicbrainz-peer-layout-holdout-v1/report.json

.venv/bin/python scripts/evaluate_musicbrainz_baseline_peer_placed_holdout.py \
  --layout .cache/semantic-map-layout-v3/artifact.json \
  --baseline-candidate .cache/musicbrainz-full-seed-targets/pipeline/peer-similarity.json \
  --output .cache/conservative-musicbrainz-peer-layout-holdout-v1/baseline-placed-report.json
```
