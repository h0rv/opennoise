# Sparse genre cosine transfer

This local-only, source-isolated ablation asks whether a sparse
genre-to-artist co-listen vote can avoid favoring globally broad artists. It
does not create a membership, change a model, alter serving output, or
authorize a public export.

## Inputs and isolation

The experiment verifies the direct MusicBrainz custody graph before using its
positive seed--artist pairs, and verifies the privacy-filtered ListenBrainz
aggregate overlay before using its edges. It reads no historical Every Noise,
H3, tags, Last.fm, release rows, audio, raw listens, or listener identifiers.
The overlay fixes a five-distinct-user privacy floor. These source roles admit
a local retrieval experiment only; they do not admit model construction or
factual genre claims.

| Verified input | SHA-256 |
| --- | --- |
| Direct-custody graph receipt | `a4ae5e59a5d7b3b46976d7379e93cdb21d6e09493e0ae113f4dd8ed13a3a14f0` |
| Direct-custody graph database | `1193a4e0f36ef02071fb3af417250d8496328b1e68c803bf1ab099122252ab69` |
| ListenBrainz overlay receipt | `bdda6ec7629f87592ee5385babfc21ca91e78ad03819237b9b8765bc262169ae` |
| ListenBrainz aggregate database | `bea7666d073cc0caaef44042a893b9551ea9cadf189a72a6b8eaf7272b05bd5f` |

For every eligible seed, the lowest fifth of
`SHA-256(seed_id, NUL, artist_mbid)` is held out before either ranker scores.
Known train artists for that seed are excluded from both rankings. The full
positive-only holdout contains 77,206 pairs over 687 seeds. Its matched
endpoint subset contains 1,453 pairs over 268 seeds: a target is included
there only if its artist is an endpoint in the sealed aggregate co-listen
graph. Unsupported positives remain in the full denominator; they are not
treated as negatives.

## Sparse ranking rule

The raw control uses the existing aggregate edge vote:

`score(seed, candidate) = sum(log(1 + distinct_users))`

over co-listen edges from that seed's retained train artists. The new sparse
cosine ablation uses the exact same edges, candidates, split, and tie break,
but divides each edge by the geometric mean of the two artists' total
aggregate edge strength:

`log(1 + distinct_users) / sqrt(source_strength * candidate_strength)`.

This is a fixed graph normalization, not a tuned threshold or a second source.
It downweights a candidate whose apparent support mostly comes from many or
very heavy aggregate relationships. The candidate set is unchanged, so both
arms support exactly 960 held-out pairs.

## Retained-input result

| Cohort and arm | Recall@10 | Recall@20 | Support |
| --- | ---: | ---: | ---: |
| Full 77,206-positive holdout, raw | 129 (0.1671%) | 188 (0.2435%) | 960 (1.2434%) |
| Full 77,206-positive holdout, cosine | 231 (0.2992%) | 315 (0.4080%) | 960 (1.2434%) |
| Endpoint-matched 1,453-positive subset, raw | 129 (8.8782%) | 188 (12.9387%) | 960 (66.0702%) |
| Endpoint-matched 1,453-positive subset, cosine | 231 (15.8981%) | 315 (21.6793%) | 960 (66.0702%) |

On the exact common support of all 960 supported targets, raw recovers 188 at
20 and cosine recovers 315. The cosine improvement is therefore a reranking
result, not an increase in aggregate graph reach. It exceeds the prior direct
IDF all-peer control (85/1,453 Recall@20) and the raw full co-listen control
(188/1,453), while preserving the already fixed source boundary.

The endpoint-matched macro Recall@20 rises from 16.0544% to 24.8135%, and
MRR@20 from 3.7054% to 6.7075%. Of the 268 matched seeds, cosine improves 81,
worsens 5, and ties 182 at Recall@20. The lift is therefore not confined to
one large seed, though the many ties make clear that it does not broaden graph
reach. The full-denominator 77,206-positive figures remain the relevant
coverage caveat: this is a sparse reranking improvement on the 960 targets
the aggregate graph can support, not recovery of unavailable targets.

The sealed local report is
`.cache/sparse-genre-cosine-transfer-v1/report.json`, logical SHA-256
`b58ac57cbc0e5541701b9760ba3fadd1d244ad08e0fbe5569a8e05a3698fc2b9`.
It is not checked into public assets and is not a release input.

Reproduce it locally with:

```sh
.venv/bin/python scripts/evaluate_sparse_genre_cosine_transfer.py \
  --direct-database .cache/musicbrainz-direct-custody-peer-graph-v1/peer-graph.sqlite \
  --direct-receipt .cache/musicbrainz-direct-custody-peer-graph-v1/receipt.json \
  --colisten-database .cache/listenbrainz-dual-overlay-v1/colisten.sqlite \
  --colisten-receipt .cache/listenbrainz-dual-overlay-v1/colisten.receipt.json \
  --output .cache/sparse-genre-cosine-transfer-v1/report.json
```
