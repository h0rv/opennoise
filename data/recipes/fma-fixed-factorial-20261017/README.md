# Fixed feature-bank and nonlinear comparison

This development experiment compares four fixed source-annotation recovery systems:
44 versus 518 native numeric features, each with linear or 128-coordinate random
Fourier ridge and eight-dimensional coefficient compression. The shared finite
training cohort makes the new 44-column fit a matched control, rather than a repeat
of the prior baseline. Native identity components, five folds, and the original
2,048 nominated candidate components are retained. No audio or new source download
is needed.

`protocol.json` freezes the complete transform, candidate, metric, and resource
choices. The protocol is exploratory on already examined development data. It does
not establish musical similarity, provide independent validation, or authorize a
serving-model replacement. Different effective regularization, correlated feature
blocks, incomplete source annotations, and supervised common-candidate eligibility
limit causal interpretations.

Use `scripts/run_fma_fixed_nonlinear.py` directly with the locked environment:

1. `freeze --protocol .../protocol.json --source NUMERIC44 --bank NATIVE518 --output SEAL`
2. For each fold 0–4 and arm `linear44`, `rff44`, `linear518`, `rff518`,
   `fit --seal SEAL --output RUN --fold F --arm ARM`.
3. After all four models for a fold exist, run the same command with `score`.
4. `summary --seal SEAL --output RUN` validates full query/component denominators
   and produces descriptive arm comparisons.

Every command inherits 120-second CPU/wall and 1 GB address-space limits with one
BLAS thread. The combined model-output cap remains 100 MB; the separately declared
native518 projection has its own explicit budget. Failed stages are retained and
cannot be accepted as completed. Inputs are hash-verified, native ID rosters must
match, and every 44-column subset value and missing cell must equal the existing
numeric bank. Existing seals bind original absolute input paths; relocation is not
silently treated as the same execution.

Before actual fits, obtain independent protocol/code review and freeze the exact
code and numerical environment. After scoring, independent formula-based replay
must verify all rank records and metrics. Receipt verification alone is not that
numerical replay. The repository recipe records a method; actual result claims
require the separately preserved execution artifacts and independent audit.
