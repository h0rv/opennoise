# Sparse genre cosine robustness

This local-only follow-up repeats the sparse cosine transfer comparison on
five fixed holdout folds. It does not create a membership, change a model,
alter serving output, or authorize a public export.

## Method

The check verifies the same direct MusicBrainz custody graph and
privacy-filtered ListenBrainz aggregate co-listen overlay used by the original
checkpoint. It reads no historical Every Noise, H3, tags, Last.fm, release
rows, audio, raw listens, or listener identifiers.

Each eligible seed has at least five direct-custody artists. Artists are sorted
by `SHA-256(seed_id, NUL, artist_mbid)`. Each fold withholds one disjoint block
of `floor(seed_artist_count / 5)` artists. Fold zero is the original lowest
fifth split. Every fold keeps at least four train artists per eligible seed.
The raw and cosine rankers use the same train artists, aggregate edges,
candidates, target cohort, and lexical tie break.

The broad slice is the top 137 eligible seeds by direct-custody membership
count, with `seed_id` as the fixed tie break. The niche slice is the bottom
137 by the same rule. These groups were chosen before ranking. A slice only
contains held-out targets that are endpoints in the sealed aggregate graph.

## Results

The full denominator contains 77,206 direct-custody positives in every fold.
The matched denominator contains only its aggregate-endpoint subset. Candidate
support is identical in both arms, so every listed Recall@20 change is also a
change on the exact common support.

| Fold | Full positives, raw to cosine | Matched positives, raw to cosine | Common support | Broad positives, raw to cosine | Niche positives, raw to cosine |
| --- | --- | --- | ---: | --- | --- |
| 0 | 77,206, 188 to 315 | 1,453, 188 to 315 | 960 | 1,088, 129 to 221 | 5, 1 to 1 |
| 1 | 77,206, 181 to 296 | 1,326, 181 to 296 | 872 | 972, 129 to 202 | 2, 0 to 1 |
| 2 | 77,206, 184 to 291 | 1,301, 184 to 291 | 901 | 976, 118 to 198 | 7, 1 to 1 |
| 3 | 77,206, 184 to 323 | 1,402, 184 to 323 | 920 | 1,030, 127 to 219 | 6, 0 to 0 |
| 4 | 77,206, 176 to 298 | 1,391, 176 to 298 | 948 | 1,000, 109 to 194 | 2, 0 to 0 |

Cosine improves Recall@20 on the full and endpoint-matched denominator in all
five folds. The broad slice also improves in all five folds. The niche slice
has only two to seven matched positives per fold and zero to two supported
targets. It shows no regression, but it is too small to support a niche-seed
claim.

The fixed support count changes between folds because each fold holds out
different positive artists. It is never a source-coverage gain by cosine. Raw
and cosine support exactly the same target identities within each fold.

The sealed local report is
`.cache/sparse-genre-cosine-robustness-v1/report-with-full-denominator.json`.
Its logical SHA-256 is
`ed8a573396acc4ff618d86c945672422c60611ad3e32833487c2fa9c6d784ea2`.
It is not checked into public assets and is not a release input.

Reproduce it locally with:

```sh
.venv/bin/python scripts/evaluate_sparse_genre_cosine_robustness.py \
  --direct-database .cache/musicbrainz-direct-custody-peer-graph-v1/peer-graph.sqlite \
  --direct-receipt .cache/musicbrainz-direct-custody-peer-graph-v1/receipt.json \
  --colisten-database .cache/listenbrainz-dual-overlay-v1/colisten.sqlite \
  --colisten-receipt .cache/listenbrainz-dual-overlay-v1/colisten.receipt.json \
  --output .cache/sparse-genre-cosine-robustness-v1/report-with-full-denominator.json
```
