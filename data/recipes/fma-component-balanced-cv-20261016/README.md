# Component-balanced descriptor baseline

This is an exploratory comparison on retained numeric FMA descriptors and native
source annotations. It acquires no recordings or other data and does not replace
the serving model. The small audio explorer remains a separate listening benchmark.

The minimized input pack contains 106,574 rows of 44 acoustic summary features
and 109,727 native track records. Its closed manifest has SHA256
`4344e609efd7442bf2c598fefb9d1f5abb08884b59f922a53a05643c60d0a323`.
Its numeric schema, file hashes and original native component/fold assignments
were verified before model outcomes. It cannot substitute for the separately
retained raw-source capture receipts.

## Frozen comparison

Only the original training rows with known native artist identity enter the
experiment. Five inner folds are assigned by a fixed hash of the original
component ID. All normalization, positive-class moments, priors, active columns
and label support are learned from the other four inner folds. Previously
inspected outer validation and test outcomes are not used for fitting, scoring,
selection or tuning here.

The three fixed arms are the existing recording-weighted positive Gaussian on
44 features, one component-balanced positive Gaussian, and recording-count
training popularity. The balanced arm gives equal total mass to each finite
training component for normalization, each finite positive component within a
label for that label's moments, and each training component for the source prior.
The shared five-positive-record support gate, variance shrinkage, variance floor
and descriptor support threshold remain unchanged. Distinct component support is
reported separately: five recordings do not imply five independent components.

Balancing changes normalization, conditional moments and priors together. Any
difference cannot be attributed to just one of those changes. Native components
join artists, albums and exact-feature duplicates; they are not individual
artists or proven independent musical units.

The primary comparison is the pooled out-of-fold difference in component-equal
Recall@10. Each component's recall is hits divided by its observed positives;
the component rates then receive equal weight. Positive-weighted recall,
ordinary query MRR, positive-weighted MRR, component-equal MRR and coverage are
reported alongside it. Empty annotations have no recall/MRR denominator but
remain in query coverage; missing features, abstentions and unsupported labels
remain in the relevant common denominators.

The 2,000 paired whole-component bootstrap draws describe composition variation
conditional on the five fixed fitted models and their predictions. Their
overlapping training sets induce dependence. These intervals are not uncertainty
for refitting the complete training procedure, nor confirmation on a new corpus.
Undefined resampled ratios remain undefined and are counted, never rerolled or
imputed as zero.

## Training concentration

The original training population has 94,953 known-identity recordings in 5,883
components, with 227,441 observed positive label incidences. One component has
39,312 recordings (41.40%) and 102,190 positives (44.93%). It spans 8,155 native
artists and 4,227 non-null albums. Its identities are positive native IDs, and
the complete original component ledger was independently reproduced.

Consequently, the positive-mass inverse-Herfindahl effective component count is
only 4.92. Keeping the large component intact produces one inner holdout of
50,105 recordings; the other folds contain 9,736 to 12,366. Neither the component
nor the folds are split or reassigned to improve balance or results.

Each declared stage retains the 120-second CPU/wall limit, decimal 1 GB address
space limit and one numerical thread. Combined new output is limited to 100 MB.
Protocol and producer source hashes are sealed before actual fits; changes after
that point require explicit new evidence rather than silently rewriting a run.

Source positives are incomplete annotations. Their recovery is not musical
similarity, calibrated genre probability or evidence that playback suggestions
are useful. This experiment makes no public-deployment or full-parity claim.

## Results

The balanced model improves component-equal recall relative to the existing
Gaussian, but does not establish an advantage over training popularity. It does
not warrant a serving replacement.

| Fixed arm | Component-equal Recall@10 | Positive-weighted Recall@10 | Component-equal MRR | Query MRR | Positive-weighted MRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| Recording Gaussian | 0.376471 | 0.327782 | 0.266606 | 0.276291 | 0.290982 |
| Component Gaussian | 0.395504 | 0.337411 | 0.279645 | 0.274882 | 0.287676 |
| Training popularity | 0.394577 | 0.378608 | 0.313258 | 0.392144 | 0.488055 |

| Fixed arm | Query coverage | Positive-weighted coverage | Component-equal query coverage |
| --- | ---: | ---: | ---: |
| Recording Gaussian | 0.971249 | 0.974222 | 0.923898 |
| Component Gaussian | 0.971238 | 0.974217 | 0.923748 |
| Training popularity | 1.000000 | 1.000000 | 1.000000 |

The balanced-minus-recording component-equal recall difference is **+1.903
percentage points**, with a descriptive paired interval of **+1.428 to +2.383**.
Component-equal MRR changes by +0.013040 (interval +0.008812 to +0.017368).
Positive-weighted recall changes by +0.963 points (interval -0.419 to +1.621),
while positive-weighted MRR changes by -0.003306 (interval -0.032610 to +0.007894).
These are distinct estimands, not alternatives selected after seeing results.

Against popularity, balanced component-equal recall differs by only +0.093
points (interval -1.194 to +1.447), and component-equal MRR is worse by 0.033613
(interval -0.045263 to -0.021282). Its positive-weighted recall is lower by
4.120 points (interval -6.264 to +0.733), and positive-weighted MRR is lower by
0.200378 (interval -0.270065 to -0.057017). All 2,000 draws have defined ratios
on this corpus. Full paired results and per-fold metrics are in the accompanying
aggregate result file; no model arm is promoted.

Balanced component-equal recall exceeds the recording Gaussian in all five
folds. Positive-weighted recall improves only in the large-component holdout
fold and falls in the other four. This makes the distinction between component
and recording/positive weighting consequential. The intact large component is
reported separately, not removed from the aggregate.

The five fits/scoring stages took 5.3 to 20.0 seconds each; the summary took
4.7 seconds. Peak process memory was below 299 MB. The complete local run is
40,818,300 bytes, below the 100 MB bound. These measurements concern the actual
retained corpus and this environment, not a production scaling guarantee.

## Reproduce

Use the locked project environment (`poe sync`). The input root must be the
verified minimized pack above; it is not included in Git. Freeze before fitting:

```sh
PYTHONPATH=src .venv/bin/python scripts/run_fma_component_balanced.py freeze \
  --protocol data/recipes/fma-component-balanced-cv-20261016/protocol.json \
  --source /workspace/opennoise-clean-inputs-20261015/candidate \
  --output /workspace/new-balanced-seal.json
PYTHONPATH=src .venv/bin/python scripts/run_fma_component_balanced.py preflight \
  --seal /workspace/new-balanced-seal.json --output /workspace/new-balanced-preflight
```

Run `fold --seal /workspace/new-balanced-seal.json --output /workspace/new-balanced-run
--fold N` separately for each N from 0 through 4, then `summary --seal
/workspace/new-balanced-seal.json --output /workspace/new-balanced-run` using
the same Python script. Each fold directory and summary directory must be fresh.
The output root is shared across the five serial stages so the combined budget
is checked. Keep the original seal and outputs immutable. Different numerical
library versions require a new seal rather than bypassing the environment check.

## Subsequent embedding experiment

The scalable inputs are the existing acoustic descriptor rows plus numeric
metadata and relationships. Expanding audio acquisition is not needed for this
line of work. The retained small audio set can support optional human listening
checks, separate from source-tag recovery.

A small feature-based learned embedding is a reasonable subsequent hypothesis,
not a result of this experiment. Before implementing one, specify one compact
train-only projection/encoder, the use of source annotations as incomplete weak
evidence, its dimension/objective and its resource budget. Compare it against
these fixed baselines using grouped development folds and retain an untouched
evaluation cohort for confirmation. Do not repeatedly optimize against these
now-inspected out-of-fold results. The present comparison does not establish that
a nonlinear encoder, larger framework or additional recordings would help.
