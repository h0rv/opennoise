# MusicBrainz release-group genre recovery feasibility

This is a local-only feasibility result for exact MusicBrainz release-group
proper-genre labels. It does not promote labels into model input, artist
membership, serving, or public data. Positive native `genres` are the targets;
MusicBrainz `tags` are excluded.

## Evaluation

The experiment used the existing receipt-bound 10,000-record release-group
sample at `.cache/musicbrainz-release-group-native-artist-support-v1/report.json`.
The sample is the first 10,000 valid records in archive order, so its results
are not a population estimate. The 1.16 GB archive was not replayed for this
evaluation. The separate 3.26 GB full support SQLite artifact has no secondary
indexes; a full scan would be required to filter its genre facet, so it was not
read for this bounded experiment.

The target set contains a release group's positive native proper-genre names
whose normalized spelling exactly matches one of the pinned 6,291 seed names.
This yielded 6,449 labeled groups among the 10,000 sampled groups. The split is
deterministic: SHA-256 of the exact release-group MBID, interpreted from the
first eight bytes, modulo five equal to zero selects held-out groups. The
remaining groups are training data. Whole release-group IDs stay on one side;
artists may occur on both sides because artist overlap is the feature used for
transfer.

For each held-out group, the transfer rule sums the training count of each
exact seed label across its credited artists and predicts the highest-scoring
label, with normalized label order breaking ties. The baseline predicts the
most frequent exact seed label among training release-group/label pairs. Both
rules make one top-1 prediction per held-out group. Transfer abstains when no
credited artist has a training label. Accuracy is shown both among scoreable
transfer groups and adjusted for abstentions over the full held-out denominator.
Macro recall gives each held-out seed label equal weight; it is computed across
all held-out labels, including labels with no training support.

## Result

There are 1,209 held-out labeled groups and 3,508 group/label pairs. The split
contains 284 distinct target labels, of which 20 have no training support.

| Rule | Correct top-1 | Scoreable groups | Abstentions | Accuracy / coverage-adjusted | Macro recall by seed |
|---|---:|---:|---:|---:|---:|
| Artist transfer | 511 | 697 / 1,209 | 512 | 73.3% / 42.3% | 6.0% |
| Train popularity | 616 | 1,209 / 1,209 | 0 | 51.0% / 51.0% | 0.35% |

The artist rule does better when it can score a group, but it abstains on 42.3%
of held-out groups and loses to the popularity baseline after abstentions are
counted. Its low macro recall also shows that these top-1 results do not
establish useful recovery for rare seed labels. The 10,000-record archive-order
sample and one deterministic split are too limited to make a quality or
promotion decision. They support only this next step: test a bounded artist
transfer rule on a less biased, adequately powered sample before considering
the 6,291-seed enrichment.

## Reproducibility

The create-only evaluator is `scripts/evaluate_musicbrainz_rg_genre_recovery.py`.
Its local output is
`.cache/musicbrainz-rg-genre-recovery-v3/report.json`, logical output SHA-256
`489289685a9f71f011250c4a9f63f4414c26c1295e435666e51f9cc788417867`.
It binds the sample report SHA-256
`f06e2a900780321489164d348044a986e76b6d6377f2fb6e5571b755522c4876`, archive
SHA-256 `6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43`, and
pinned reconciliation SHA-256
`a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0`.
