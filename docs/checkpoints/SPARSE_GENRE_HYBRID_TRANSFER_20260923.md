# Sparse genre hybrid transfer

This local-only evaluation tests a fixed combination of train-only direct
MusicBrainz IDF peers and cosine-normalized ListenBrainz aggregate co-listen
votes. It does not create memberships, change a model, change serving output,
or authorize export.

## Method

The evaluator verifies the same direct-custody graph and privacy-filtered
aggregate co-listen receipt used by the earlier cosine checks. It uses the
fixed fold-zero holdout of 77,206 direct-custody positives over 687 seeds.
Known train artists are excluded from every arm. The matched cohort contains
the 1,453 held-out positives over 268 seeds whose artists are aggregate graph
endpoints.

The direct control expands all 15,839 accepted train-only IDF peer pairs. The
cosine control uses the fixed aggregate cosine vote. Each control returns no
more than 20 artists per seed, sorted by score descending and artist MBID
ascending. The hybrid takes only the top 20 candidates from each control and
applies reciprocal-rank fusion, `1 / (60 + rank)`. The fixed offset, candidate
limit, and tie break were chosen before reading held-out targets. The hybrid
therefore has at most 40 fusion candidates per seed and returns the same 20
artists as each control.

The run reads no historical Every Noise, H3, tags, Last.fm, release rows,
audio, raw listens, or listener identifiers. It uses no target-tuned weights.

## Results

| Cohort | Positives | Direct Recall@20 | Cosine Recall@20 | Hybrid Recall@20 | Direct macro Recall@20 | Cosine macro Recall@20 | Hybrid macro Recall@20 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Full holdout | 77,206 | 1,245 | 315 | 1,031 | 4.4841% | 0.5706% | 4.1970% |
| Endpoint matched | 1,453 | 85 | 315 | 270 | 8.6887% | 24.8135% | 23.8519% |
| Broad seed slice | 1,088 | 45 | 221 | 176 | 4.5348% | 26.0650% | 20.8914% |
| Niche seed slice | 5 | 2 | 1 | 2 | 40.0000% | 20.0000% | 40.0000% |

The niche slice has only five matched positives, so it does not support a
niche-seed conclusion. The hybrid loses to direct peers on the full holdout
and loses to cosine on the matched cohort. The hybrid also has lower macro
Recall@20 than the best arm in both cohorts. No tuning was performed after
seeing the held-out results.

## Candidate support

The full cohort has 49,995 direct-supported targets and 960 cosine-supported
targets. Their union contains 50,032 targets, with 49,072 direct-only, 37
cosine-only, and 923 common targets. The fusion candidate limit reduces hybrid
support to 1,529 targets. Hybrid Recall@20 contains 777 direct-only, 13
cosine-only, and 241 common-support targets. It adds zero targets that neither
control already recalls at 20.

The high full-holdout direct result is candidate reach from the direct
train-membership expansion. It does not show stronger ranking quality than
cosine. On the endpoint-matched cohort, where both routes can nominate the
target, cosine recovers 315 positives to direct's 85 and has higher macro
Recall@20. The hybrid does not improve either result, so it remains a negative
local ablation rather than a model candidate.

The sealed local report is
`.cache/sparse-genre-hybrid-transfer-v1/report-optimized.json`. Its logical
SHA-256 is `fa98ba2326c8aa5ce8c2ad3a1266cd378558d3e30382fd8b7d9f4e673a8bff6a`.
It is not a public asset or release input.

Reproduce it locally with:

```sh
.venv/bin/python scripts/evaluate_sparse_genre_hybrid_transfer.py \
  --direct-database .cache/musicbrainz-direct-custody-peer-graph-v1/peer-graph.sqlite \
  --direct-receipt .cache/musicbrainz-direct-custody-peer-graph-v1/receipt.json \
  --colisten-database .cache/listenbrainz-dual-overlay-v1/colisten.sqlite \
  --colisten-receipt .cache/listenbrainz-dual-overlay-v1/colisten.receipt.json \
  --output .cache/sparse-genre-hybrid-transfer-v1/report-optimized.json
```
