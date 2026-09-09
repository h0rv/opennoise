# ListenBrainz offline co-listen experiment

## Purpose

This experiment checks whether privacy-thresholded ListenBrainz co-listen aggregates can predict new artist pairs better than direct genre overlap. It uses no audio, listener identifier, raw listen, artist-neighbor lookup, or UI output.

## Inputs and policy

The input is the sealed qualified database with SHA-256 `282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866`. The public catalog snapshot has SHA-256 `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`.

The source policy allows normalization, training, and embedding. It denies display and local search. The experiment artifact therefore has `export_allowed=false` and `serving_allowed=false`. Raw pairs, ranked artists, and per-pair support do not enter the public database, API, or UI.

The input has seven daily windows. Every window is 86,400 seconds and every retained pair has at least five distinct listeners in that day. The experiment treats support as the number of distinct daily windows. It does not sum daily counts or claim a global unique-listener total.

The public artist cohort uses exact MusicBrainz artist IDs. All 1,331 public IDs occur among the qualified source's 1,525 endpoints.

## Method

The first four chronological daily windows form training data, and the last three form the held-out period. A held-out pair already present in training is removed before scoring.

The experiment evaluates three rankers for 944 artists with a novel held-out pair. The two co-listen graph rankers use only training windows. Direct genre IDF uses the fixed current public direct-claim snapshot as approved transductive side information; that snapshot can postdate the training period, so it is not a strict forecasting feature.

- Direct genre IDF weighted Jaccard over the fixed public direct-claim snapshot.
- Common-neighbor cosine over the training co-listen graph.
- Artist degree popularity from the training co-listen graph.

The held-out set has 3,210 novel undirected pairs, or 6,420 directed retrieval references. The training graph has 8,203 undirected pairs and 1,035 candidate artists.

## Results

The receipt-bound result is at `.cache/listenbrainz-offline-experiment/artifact.json`. It keeps the same source hashes and has `export_allowed=false` and `serving_allowed=false`.

The whole held-out cohort has 944 queries and 6,420 directed references. Each method can score a different number of queries, so the comparison below describes end-to-end coverage as well as ranking results.

| Method | Queries it can score | Hit rate at 25 | Recall at 25 |
| --- | ---: | ---: | ---: |
| Direct genre IDF weighted Jaccard | 870 | 0.443856 | 0.125701 |
| Common-neighbor cosine | 669 | 0.484110 | 0.276012 |
| Train-degree popularity | 944 | 0.625000 | 0.249688 |

The common scoreable cohort has 631 queries and 5,785 directed references. This compares the three methods where each produces a score.

| Method | Hit rate at 25 | Recall at 25 |
| --- | ---: | ---: |
| Direct genre IDF weighted Jaccard | 0.556260 | 0.123768 |
| Common-neighbor cosine | 0.681458 | 0.296975 |
| Train-degree popularity | 0.746434 | 0.252031 |

Common-neighbor cosine has the highest recall at 25. Train-degree popularity has the highest hit rate at 25. These results do not establish artist similarity, genre similarity, or a production ranking policy. A later review needs more time windows, coverage slices, and a decision about a separately licensed and policy-allowed derived output.
