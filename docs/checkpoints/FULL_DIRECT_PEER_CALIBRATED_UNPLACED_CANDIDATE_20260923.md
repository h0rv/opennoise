# Full direct-peer calibrated unplaced candidate

This is a local-only, non-serving geometry candidate. It does not change the
atlas, establish factual genre membership or placement, authorize export, or
use historical output during construction.

The calibration replays the exact pinned full direct MusicBrainz membership
input (`3c2c8b23e00c0201f1505be6851bc392258665cb11fc353949c1a332ebc9dd1c`).
It predeclares the sparse rule: a pair must have exactly one artist in its full
artist-set intersection, and that sole witness's seed degree must be below ten.
Ineligible witnesses are filtered before candidate-pair enumeration, then the
complete intersection check rejects any hub-contaminated pair. It then evaluates only placed-to-placed retained pairs with
each target coordinate excluded from both its peer-centroid estimate and the
leave-one-out global-centroid baseline.

| Calibration measure | Result |
| --- | ---: |
| Eligible sparse edges from full direct input | 15,061 |
| Placed-to-placed calibration edges | 13,564 |
| Evaluable held-out placed targets | 1,663 |
| Mean direct-peer error | 0.2615540953 |
| Mean leave-one-out centroid error | 0.2904804866 |
| Mean improvement | 0.0289263913 |

Only after this calibration succeeds does the builder read the separately
pinned 1,497-edge conservative frontier. That frozen frontier supplies support
only, not calibration evidence: it yields 405 local candidate positions and
abstains on 2,941 unplaced seeds. Each position is a centroid of its placed
frontier peers and is labeled `local_candidate_only` in the ignored output.

The run wrote
`.cache/full-direct-peer-calibrated-unplaced-candidate-v1/report-streamed.json` with
logical SHA-256 `94da2767b45baa3e1672da35d4ba77e1a42535c8e3de29d61df06204da0662ea`.
It pins the v3 layout bytes and the frozen conservative frontier bytes. The
source-family calibration supports continued local review only; it does not
validate any individual singleton frontier edge or permit public placement.
The 302 MB direct-membership input is hashed and parsed as streams; only exact
artist and genre identifiers enter the bounded graph accumulator. The writer
creates outputs only below the repository `.cache` root with `O_EXCL` and
rejects path or symlink escapes.

The navigation-tail rerun wrote `report-navigation.json`, logical SHA-256
`1130ade8938952f870ff9dc91308bf1e8c27ec56ffb9ee338f8af46b3e3e70b4`. Across
the 1,663 held-out targets, median peer error is 0.1107193540, p90 is
0.8115002929, and 62.8984% improve on the target-excluded global centroid.
For one placed anchor (96 targets), median/p90 are 0.0290933484/0.9803979157
and 69.7917% improve; for two or more anchors (1,567 targets), they are
0.1152097933/0.8010784901 and 62.4761% improve. The 405 proposal support
distribution is 91 with one placed peer, 72 with two, 65 with three, 54 with
four, 38 with five, 40 with six, 22 with seven, 10 with eight, 6 with nine,
3 with ten, 2 with eleven, 1 with twelve, and 1 with fifteen. Each proposal
now retains its exact frontier peer evidence references. These are risk-visible
local diagnostics, not a navigation approval or a factual placement claim.

Reproduce locally without replacement:

```sh
.venv/bin/python scripts/build_full_direct_peer_calibrated_unplaced_candidate.py \
  --public-input .cache/musicbrainz-full-seed-targets/pipeline/public-model-input.json \
  --layout .cache/semantic-map-layout-v3/artifact.json \
  --frontier .cache/musicbrainz-peer-threshold-sensitivity-v1/conservative-peer-candidate-v2.json \
  --output .cache/full-direct-peer-calibrated-unplaced-candidate-v1/report.json
```
