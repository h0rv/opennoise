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

## Completed development comparison

All 43 orchestrated stages completed using the existing verified native bank.
All 94,953 queries and 227,441 source positives remain in primary denominators.

| Arm | Component Recall@10 | Positive Recall@10 | Query coverage | Macro recall | Rare macro recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Linear44 | 42.674% | 40.899% | 97.124% | 12.001% | 0.881% |
| RFF44 | 42.366% | 40.804% | 97.124% | 11.633% | 0.718% |
| Linear518 | 48.368% | 44.047% | 93.389% | 14.755% | 1.611% |
| RFF518 | 43.496% | 40.004% | 93.389% | 11.912% | 0.847% |

The four prespecified component-recall contrasts are -0.308 percentage points
(RFF44 minus Linear44), -4.872 (RFF518 minus Linear518), +5.694
(Linear518 minus Linear44), and +1.130 (RFF518 minus RFF44).
The richer linear system improved this development annotation-recovery measure;
the fixed nonlinear systems did not improve over their corresponding linear systems.

Linear518 covered 3,546 fewer queries. On the common 88,676-query subset,
component recall increased from 46.307% to 53.690%. Pooled recall improved
within both the giant component (42.432% to 44.467%) and other components
(39.648% to 43.703%). Rare-label recovery remains poor. These diagnostic subsets
are not replacements for the full-denominator primary result. Previously inspected
folds, incomplete labels, feature correlation and unequal effective regularization
preclude independent-validation or musical-quality claims. No model is promoted.

Independent replay rederived all 20 fitted states using separate NumPy code and
alternative accumulation, and verified all 379,812 query rank records, candidate
rosters, neighbors, label votes, support flags and aggregate metrics. Maximum
coefficient discrepancy was 1.34e-15; replayed cosine distances matched exactly.
The reference was frozen before outcomes. Its SHA-256 is
`642b1f7320ae5bcbb022350ae23d681d582b2b7d4de2827427e7eb9a78e1539b`;
the complete audit SHA-256 is
`f229900ef602db5033cfcc7f09be175cc47bc3246be9cbb802a7ef85b7837982`.

Actual results SHA-256:
`724350c44dd4d2d8db4c80066716619323156aa0c8ac6ba520f2f821c20c9c27`.
Execution plan SHA-256:
`1c57c76d8986130b91f6bb7084db4395a62191e047dc0f1c061b18328425bde1`.
Final checkpoint SHA-256:
`942c6038f4d0b1ae685e0099101c5b47df1cea3975bb1988605f43596421c75f`.
Local run: `/workspace/opennoise-backend-run-20261017`.
Independent audit: `/workspace/opennoise-nonlinear-independent-20261017`.
These are local evidence paths, not public downloads or confirmed Library saves.

The model outputs total 86,944,927 bytes; maximum model stage was 17.83 seconds
and peak RSS was approximately 548 MB, below unchanged 120-second/1-GB guards.
Independent custody checking verified all 43 stages and 273 files. A relocated
copy verified under the same external pins without rewriting its seal or refitting.
Only aggregate results and recipes are committed; detailed research inputs and
per-query artifacts remain local.
