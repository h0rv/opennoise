# One fixed acoustic-feature embedding experiment

This experiment tests whether a small supervised projection of the existing 44 acoustic descriptors improves source-annotation recovery through nearest neighbors. It is exploratory and does not establish musical similarity or justify replacing the serving model.

The fixed encoder uses component-weighted, centered multivariate ridge regression with penalty 1, then compresses the coefficient matrix to eight singular directions. Training targets are observed source genre indicators; absent annotations are not verified negative musical memberships. Feature normalization, label support, coefficients and singular directions are fitted within each inner training partition. Application to queries and candidates uses only their acoustic features. No held-out annotations enter fitting, representations, candidate nomination, distances or label transfer.

The five native component folds are unchanged. Every source-known row in the original training partition is a held-out query once. Hashes nominate up to 2,048 training components and one finite recording per component. Raw and learned cosine retrieval share the same eligible candidate pool and transfer unweighted source-genre votes from ten neighbors. Candidate nomination is label-blind; final common eligibility depends on the supervised encoder and is separately reported. The recording Gaussian, component-balanced Gaussian and recording-popularity models rank genres on the identical queries. All five arms are compared on source genre recovery, not on incompatible track-retrieval scores.

The primary comparison is learned-minus-raw component-equal Recall@10. All-positive Recall@10, query and positive-weighted MRR, coverage, support ceilings, per-fold results, and the giant component versus remaining components are also retained. Two thousand paired whole-component bootstrap draws describe variability of fixed predictions. They do not capture refitting uncertainty or establish population confidence; training partitions overlap.

Native component 2 remains intact: 39,312 recordings, 8,155 artists and 4,227 albums. Component balancing is not artist balancing. Giant-only and other-component reports retain the same fitted models and are influence descriptions, not deletion-and-refit experiments.

The corpus and previous split outcomes have already been examined. Confirmation requires a prospectively locked evaluation on genuinely unexamined independent components; a musical-relevance claim additionally requires blinded relevance judgments. No new data, audio, parameter search, serving replacement or public deployment is part of this experiment.

## Results

All 94,953 original-training queries were evaluated once across 5,883 native components. There were 92,677 labeled queries and 227,441 observed positive incidences. All five fits retained eight encoder dimensions. No parameter changes or additional model candidates followed these outcomes.

| Arm | Component Recall@10 | Positive Recall@10 | Query MRR | Ranking coverage |
| --- | ---: | ---: | ---: | ---: |
| Raw-feature neighbors | 42.230% | 40.321% | 38.414% | 97.124% |
| Ridge-8 neighbors | 42.657% | 40.951% | 39.631% | 97.124% |
| Recording Gaussian | 37.647% | 32.778% | 27.629% | 97.125% |
| Component Gaussian | 39.550% | 33.741% | 27.488% | 97.124% |
| Recording popularity | 39.458% | 37.861% | 39.214% | 100.000% |

The primary learned-minus-raw component Recall@10 difference is **+0.427 percentage points**, with a descriptive paired interval of **[-0.103, +0.968] points**. Positive-weighted Recall@10 improves by 0.630 points, interval [-0.123, +0.961]. Both intervals include zero: this experiment does not establish a reliable recall improvement from the embedding over raw-feature neighbors. Query MRR increases by 1.217 points, interval [0.567, 1.520]; this secondary result remains exploratory.

Ridge-8 component Recall@10 exceeds the component Gaussian by 3.106 points and recording popularity by 3.199 points. Raw-feature neighbors also perform better on that measure. Those comparisons therefore do not isolate a benefit of learning the embedding. All three recomputed Gaussian/popularity controls reproduce the previous experiment's pooled metrics exactly.

## Giant-component influence and coverage

With the same fixed models, giant component 2 has positive Recall@10 of 41.321% raw versus 42.494% learned (+1.173 points). Other components have 39.505% versus 39.692% (+0.187 points). The giant accounts for approximately 84% of the net additional recovered positive incidences, despite contributing one component to the component-average metric. Positive-weighted improvement appears in three of five folds; folds 0 and 2 decline. No component was split or reassigned.

Each fold nominates 2,048 candidate components. Four folds retain 2,047 eligible representatives; fold 2 retains all 2,048. No additional candidates are excluded solely by the learned norm in this run. Candidate label unions cover 143–149 of 164 native labels, while 154–158 labels meet the encoder support gate. The two neighbor arms have identical 97.124% ranking coverage and 99.356% candidate-label support ceilings. Missing descriptors and support abstentions remain in the positive denominators. Empty-label queries count toward coverage, and empty neighbor-label votes do not count as genre-ranking coverage.

## Verification and bounds

The protocol was fixed before fitting and reviewed with 11 synthetic tests. It is bound by SHA-256 `8323b4e1e9a6aba9a1fc5d04e1864b8b415647cc596e72ddd7fb23308934849a`. The execution seal binds exact implementation and dependency versions, with SHA-256 `e4351cfa8fb0f89d69c6984d63d7456510c78d39a2ba84aaa90c01134b5975e9`.

Five producer stages took 11.98–51.38 seconds; summary took 5.19 seconds. Peak producer memory was 511,336,448 bytes. Combined outputs are 75,056,572 bytes. The existing per-stage 120-second CPU/wall, 1,000,000,000-byte address-space, single-thread BLAS and 100,000,000-byte output limits were retained.

Independent numerical replay passed on its first execution: 15 fitted models, all 474,765 genre rankings, 189,906 neighbor lists, all per-component statistics and 33 bootstrap intervals matched. Maximum cosine-distance discrepancy was 1.23e-14 and interval discrepancy was 2.55e-15. The independent review receipt has SHA-256 `07b8b21ab014cef44bb25162913bd1192a6e13d8a997eaeaeb0aea51d3438aaa`. Final repository validation is recorded in the retained completion receipt. The independent verifier uses an augmented least-squares solve, a different SVD driver, direct Gaussian density calculations and multiplicity-based bootstrap aggregation. It checks the candidate roster, every neighbor list and genre ranking, sufficient statistics, and giant/other-component summaries.

## Reproduction

Use the minimized numeric input bundle with manifest SHA-256 `4344e609efd7442bf2c598fefb9d1f5abb08884b59f922a53a05643c60d0a323`. No audio or fresh network capture is needed. Run `poe sync` with the locked dependencies, then invoke the script directly as allowed by AGENTS.md:

```sh
PYTHONPATH=src .venv/bin/python scripts/run_fma_component_embedding.py freeze \
  --protocol data/recipes/fma-component-ridge-embedding-20261016/protocol.json \
  --source /path/to/minimized-inputs --output /tmp/fma-ridge-seal.json
PYTHONPATH=src .venv/bin/python scripts/run_fma_component_embedding.py fold \
  --seal /tmp/fma-ridge-seal.json --output /tmp/fma-ridge-run --fold 0
```

Run folds 1–4 once each with the same seal and fresh corresponding output directories, then run the `summary` stage with the same `--seal` and `--output`. Exact sealed executable files and dependency versions must match. Use `poe check` for repository validation. Full numeric models, neighbor/ranking records, independent replay scripts, logs and hashes are retained in the local evidence archive. No Library upload was retried and no public deployment or serving-model change occurred.
