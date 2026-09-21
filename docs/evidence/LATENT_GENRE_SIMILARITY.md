# Latent genre similarity benchmark

`scripts/build_latent_genre_similarity.py` benchmarks a fixed rank-16 sparse
truncated SVD over the train-only artist-to-genre matrix already sealed by the
full graph signal. It reads no audio, listeners, raw listens, or historical
inputs. The output is review-only and cannot promote memberships or serving
edges.

It compares low-rank reconstruction retrieval, binary Jaccard, train-only
global popularity, and the abstaining direct-only baseline on one deterministic
artist-to-seed heldout split. Missing pairs are unknown, not negative; all
metrics are positive-only recall. The direct-only baseline has no scoreable
positives for this split and abstains on all 7,407 positives.

The first local replay used 1,416,893 train pairs and 5,000 deterministic
heldout artists (7,407 positives). Latent SVD recalled 0.3633 at 10 and 0.5130
at 25, with 6,400 scoreable and 1,007 abstained positives. It beat train-only
popularity (0.3262 / 0.4912), but did not beat binary Jaccard (0.5107 / 0.6763),
which has the same 6,400/1,007 coverage. This is an honest negative-result
benchmark: it is not a production selection, quality claim, membership edge,
or serving signal.
