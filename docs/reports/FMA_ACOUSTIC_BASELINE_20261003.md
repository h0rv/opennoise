# Audited native FMA acoustic baseline

The independent open corpus now has full native feature custody and a reusable
positive-only acoustic model. In the single prespecified test fold, Recall@10
is 39.59% versus 36.63% for training-label popularity. This is limited source-label
recovery: first-hit reciprocal rank is lower than popularity, rare-label recovery
is weak, and there is no independent musical-relevance or artist-genre result.

| Fold / arm | Recall@5 | Recall@10 | Macro Recall@10 | First-positive MRR |
| --- | ---: | ---: | ---: | ---: |
| Validation / acoustic | 24.41% | 37.05% | 25.33% | 0.30261 |
| Validation / popularity | 23.64% | 36.33% | 7.19% | 0.32789 |
| Validation / constant | 7.47% | 10.22% | 6.47% | 0.13431 |
| Test / acoustic | 26.50% | 39.59% | 27.40% | 0.31296 |
| Test / popularity | 25.82% | 36.63% | 7.35% | 0.31911 |
| Test / constant | 5.40% | 8.12% | 7.35% | 0.11533 |

The official FMA README (SHA256 `54148723ff06c19374c368499f1e97afb3d10f58646d20a221e4d9c7ab63fac9`)
describes `features.csv` as common features computed with Librosa, and licenses
metadata under CC-BY-4.0. Attribution: Defferrard, Benzi, Vandergheynst and Bresson,
*FMA: A Dataset For Music Analysis*, ISMIR 2017,
<https://github.com/mdeff/fma>. This source is separate from proprietary EchoNest
tables and individually licensed audio. Neither was consumed. Code's MIT license
is not the license evidence for the corpus.

Two audited native HTTP ranges retained 293,323,155 bytes, including the local
header/name prefix and the 293,323,100-byte bzip2 member of the official ZIP.
The complete 951,117,185-byte uncompressed feature stream was read without
materializing it, CRC32 `e8eb7a19` and observed SHA256
`a035d04941e15fc3240aadd6880c519471d218329bbfe0e82c17553ba50e9e16`.
The entire ZIP archive hash was not verified. Native range captures and previous
failed/earlier projections remain immutable local artifacts.

The final projection has 106,574 native tracks, 44 selected float32 mean channels
and stable FMA track IDs, using under 20 MB. All selected cells are finite.
All 518 original native feature cells participate in the duplicate diagnostic:
1,689 exact groups containing 3,800 tracks. The initially failed empty projection
is retained; the schema-only correction explicitly maps conceptual
`zero_crossing_rate` to native `zcr`, statistic `mean`, before any model fit.
It did not change features, hyperparameters or folds based on outcomes.

The native metadata has 109,727 tracks and 260,586 observed label positives,
164 taxonomy IDs but only 162 observed genre IDs. This is the raw API snapshot,
not the published cleaned 161-label benchmark. There are 2,609 missing target rows,
3,153 tracks without features (6,717 positives), and 974 unresolved artists
(2,075 positives). Unresolved artist tracks are excluded from fitting/evaluation;
their positive source IDs remain grouping nodes and can bridge known albums.
All 3,035 known-artist missing-feature tracks (6,434 positives) remain eligible
raw metadata queries in their component's fold and receive acoustic abstentions.

The frozen split joins whole native primary-artist/known-album components and
exact full-feature-cell duplicate groups. Minimum positive native artist ID
determines the fixed SHA256 80/10/10 bucket assignment, without labels or balance
reshuffling. There are 7,410 components; the largest contains 39,750 tracks.
Consequently realized known-artist train/validation/test counts are
94,953 / 7,332 / 6,468, approximately 87.31% / 6.74% / 5.95%.
Native-ID grouping does not establish complete recording/performer independence;
unknown albums and nonexact aliases remain unresolved. No source artist names
were merged or used as model inputs.

Normalization and diagonal Gaussian positive-label means/variances/prevalences
use training rows only. No source absence is treated as a verified negative.
The fixed model fits on 92,270 finite training rows with 44 active channels and
158 labels having at least five finite-feature positives. Validation was not
used for tuning. A pre-fit independent audit restricted both comparators to
training-observed labels, with the original declaration preserved and a separate
addendum recording that clarification.

Validation has 7,332 queries, 7,253 labeled queries and 16,668 positives; test has
6,468 queries, 6,369 labeled queries and 14,402 positives. Test acoustic abstains
on 182 missing-feature rows and one numeric out-of-support query; validation
abstains on 170 missing-feature rows and three out-of-support queries. Every
observed target stays in the denominator. Test rare labels have 263 positives
and only 4.94% Recall@10. Fourteen test positives have below-five training support
and recover zero; no held-out positives are training-unseen in this partition.
Unseen labels remain in the vocabulary and metric machinery; focused tests
verify zero-support labels cannot gain comparator recovery credit.

The single model evaluation took 2.959 seconds with one BLAS thread, measured
peak RSS 283,226,112 bytes. Trained weights are 112,268 bytes; original saved run
artifacts total about 3.53 MB. The tracked pack adds native held-out targets,
receipts and rights evidence for exact offline saved-rank replay (about 3.7 MB).
It ships neither the 293 MB native feature member nor the complete numeric corpus;
native replay still requires the retained or newly acquired member. Full query
rankings, abstention reasons, folds and implementation hashes are preserved.

Eleven focused tests, Ruff and ty pass. The complete tracked saved-rank replay
matches every validation/test acoustic and comparator metric without fitting,
source downloading or consulting audio. This verifies the preserved experiment,
not independent source custody. Independent native-source and grouping/metric
audit results are recorded separately.

The model has no MBID bridge, factual artist genres, EveryNoise construction,
reference training, known-benchmark artist coverage, calibrated scores,
precision, audio validation or public product promotion. This closes a substantive
larger independently licensed acoustic-corpus/model gap while preserving those
limitations.
