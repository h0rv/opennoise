# Experimental descriptor-support calibration

The unchanged support default requires every active standardized descriptor to be
within ±12, complete finite inputs, and a finite nonzero embedding norm. It is a
per-coordinate check, not a calibrated acceptance probability. The prior coverage
diagnostic attributed all 3,546 additional 518-feature abstentions to this check,
with no missing-feature or zero-norm losses. That post-outcome diagnosis motivates
this separate measurement; it does not select a replacement threshold.

This protocol reserves whole native identity components for calibration using one
fixed hash split inside the original training corpus. Two matched linear encoders
are fitted on the remaining components. No previously scored development folds or
original validation/test queries are evaluated. The new proper-fit cohort justifies
the two new fits; existing model artifacts and defaults are unchanged.

Thresholds target 90%, 95%, and 99% component-weighted empirical descriptor acceptance
among common-finite calibration rows. Each bank has its own thresholds. Quantiles
are calculated before embedding-norm checks and without using calibration labels.
They provide no future, conformal, full-roster, or nonempty-ranking coverage guarantee.
The unchanged threshold 12 is included as a reference under these same new models.

A fixed common candidate pool uses only proper-fit components and the original
12-coordinate gate. Each arm ranks every calibration query once. Four query masks
are then applied to these fixed rankings. Reports retain full calibration
query/positive denominators and separately show accepted-only and common-accepted
subsets. Annotation-recovery metrics are descriptive on already examined training
data, not independent validation or evidence of musical quality. No operating point
is selected or promoted from these results.

Run the locked Python scripts directly, with a fresh seal and output directory:

1. `scripts/run_fma_support_calibration.py freeze --protocol PROTOCOL --input-seal FACTORIAL_SOURCE_SEAL --output SEAL`
2. `scripts/run_fma_support_calibration.py fit --seal SEAL --output RUN --arm linear44`
3. Repeat `fit` with `--arm linear518`.
4. `scripts/run_fma_support_calibration.py calibrate --seal SEAL --output RUN`
5. `scripts/run_fma_support_calibration.py score --seal SEAL --output RUN`

The input seal binds verified numeric sources only; prior fitted models and outcomes
are not read. Stages retain the 120-second CPU/wall, 1-GB address-space and combined
100-MB output guards. Failed partial stages cannot be resumed as completed. Exact
source/code/protocol/environment pins and completed artifact receipts are checked.
Independent protocol/code review precedes execution; independent numerical replay
must verify the split, fitted state, quantiles, candidate pool, ranks, masks and
metrics afterward. Receipt verification alone is custody checking.

## Completed descriptive calibration

The frozen split assigned 82,985 rows across 4,740 components to proper fitting,
including the giant component. The matched finite fit cohort contained 81,013 rows.
Calibration retained all 11,968 rows across 1,143 components. Quantiles used the
11,257 common-finite rows in 1,054 components; 89 components had no common-finite
calibration rows. All 711 missing-feature rows remain in whole-roster metrics.

| Arm | Gate | Threshold | Conditional weighted descriptor acceptance | Whole-roster ranking coverage | Component Recall@10 |
| --- | --- | ---: | ---: | ---: | ---: |
| linear44 | original12 | 12.00000 | 99.989% | 94.026% | 41.627% |
| linear44 | q90 | 3.59098 | 90.013% | 80.523% | 37.130% |
| linear44 | q95 | 4.18176 | 95.002% | 86.255% | 39.403% |
| linear44 | q99 | 6.13384 | 99.021% | 93.199% | 41.171% |
| linear518 | original12 | 12.00000 | 97.395% | 91.419% | 47.211% |
| linear518 | q90 | 6.82908 | 90.076% | 84.124% | 43.563% |
| linear518 | q95 | 8.90222 | 95.003% | 89.113% | 46.046% |
| linear518 | q99 | 20.79093 | 99.044% | 93.023% | 48.032% |

The same original threshold 12 accepted 99.989% versus 97.395% under the
conditional component-weighted descriptor measure. Thus 12 has different empirical
coverage meanings for the two banks; it was never a common coverage probability.
At the fixed 95% operating point, thresholds were 4.18176 and 8.90222. Whole-roster
component Recall@10 was 39.403% and 46.046%. On the same 9,913 queries accepted by
both arms at that point, it was 45.581% and 52.679%. This shared subset describes
ranking differences separately from which queries each bank accepts. It is not an
independent validation population.

The 99% threshold is below 12 for the 44-bank and above 12 for the 518-bank.
These are the prespecified empirical quantiles, not an outcome-selected adjustment.
Ranking, neighbor, embedding, and descriptor-acceptance counts happened to coincide
in this run, with zero norm failures; the artifacts retain their separate counters.
No operating point is selected or promoted, and historical/default inference is
unchanged. Component-weighted conditional acceptance must not be substituted for
recording-weighted whole-roster coverage.

Independent replay rederived both fitted states and exactly verified all descriptor
scores, weights, thresholds, candidate IDs, 23,936 ungated rankings, 95,744 masks,
availability counts, and all three metric populations. The audit SHA-256 is
`e1f4ee67df1905695afbd8bb3806dc5a5be96aa7d531a4dd27ed07e4de58f576`;
the pre-outcome independent reference SHA-256 is
`769e8536a7317e3f6ceb478661d5d58013ae848997eec6c1cea328565119d82c`.
All five stages passed; maximum stage time was 10.38 seconds and outputs totaled
7,049,592 bytes, within unchanged guards. Runtime source remained frozen at
`55ab6304f3541c69d45acaabd0d4ac905826b18f`.

Aggregate results and exact original result/threshold hashes are in `results.json`.
Individual excluded component IDs and detailed rank records remain local. Execution:
`/workspace/opennoise-support-calibration-run-20261017`; independent audit:
`/workspace/opennoise-support-calibration-independent-20261017`. These local paths
are not public downloads or confirmed Library saves.
