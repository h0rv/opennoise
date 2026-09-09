# Historical membership signal benchmark

This experiment asks a limited question: how much of the retained Every Noise geometry can be
reconstructed from a sealed genre-to-artist membership artifact? It does not claim to reproduce
Spotify's private data, embeddings, weights, or ranking system.

## Inputs and boundary

The model uses 306,136 H3 genre-to-artist memberships across 6,289 of 6,291 retained H2 names.
H2 coordinates are not model features. They are read only after model fitting for this report.
The two H2 genres without a membership remain nodes with `no_h3_membership` evidence.

With 6,291 nodes, random nearest-neighbor recall@10 is about `10 / 6,290 = 0.00159`.

## Direct-signal diagnosis

On a deterministic 512-genre query sample against H2 coordinate neighborhoods, direct H3 metrics
have the following recall@10:

| Metric | Recall@10 | Lift over random |
| --- | ---: | ---: |
| weighted Jaccard | 0.02539 | 16.0x |
| cosine | 0.02520 | 15.9x |
| IDF overlap | 0.02402 | 15.1x |
| shared-artist count | 0.02383 | 15.0x |

Artist overlap is therefore useful evidence, but not enough to reconstruct the legacy geometry on
its own. The artifact publishes each statistic separately; it never presents IDF overlap as
Jaccard.

## Coordinate-free layout comparison

| Layout | Graph-neighbor preservation@10 | H2 recall@10 | Normalized stress | Double-build runtime | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| anchored diffusion | not measured in this run | 0.00234 | 1.404 | 31.45 s | 396 MiB |
| sparse normalized Laplacian | 0.03066 | 0.00371 | 1.292 | 8.54 s | 420 MiB |
| spectral plus bounded force refinement | 0.08301 | 0.01270 | 1.205 | 20.89 s | 418 MiB |

The force-refined spectral layout is the current production candidate because it improves both
topology-local and post-fit oracle diagnostics without reading H2 during fitting. It emits a 16:9
world coordinate system, 24 overview communities, progressive 24/240/1,200/all-node levels, and
16 by 16 tile membership lists. Initial view edge count is zero; edges are a focus interaction.

## Next bounded experiment

A separate `calibrated_replica` must keep an H2 train/holdout split and may test an explicit
blend of H3 similarity with token and character n-gram TF-IDF of the 6,291 permitted genre names.
It must select weights on train neighborhoods and publish one untouched holdout result. That is a
reverse-engineering aid, not the coordinate-free production model.
