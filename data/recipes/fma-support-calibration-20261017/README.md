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
