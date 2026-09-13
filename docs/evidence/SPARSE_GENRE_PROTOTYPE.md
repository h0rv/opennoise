# Sparse genre prototype baseline

This local, non-historical baseline consumes a sealed
`MusicBrainzSeedTargetArtifact`. It represents each matched artist using only
their contextual MusicBrainz tags, weighted with TF-IDF. A seed prototype is
the normalized mean of its training artists' tag vectors. Cosine similarity
between prototypes produces candidates that are deliberately separate from the
direct artist-overlap peer artifact.

Direct artist-to-seed target evidence is never a feature. It supplies only
positive labels: a deterministic hash selects a configured share of
artist-to-seed positives for holdout, prototypes use the remaining train
edges, and retrieval recall@k/MRR are measured only for held-out positives.
An artist or seed without contextual features abstains; the artifact makes that
count explicit. It makes no negative-membership claim, does not read
historical data, and is a weak-supervision baseline rather than a recovered
Every Noise model.

Run it after the extractor artifact is available:

```bash
uv run poe build-sparse-genre-prototype
```

The task requires `OPENNOISE_MB_SEED_TARGET_ARTIFACT`,
`OPENNOISE_SPARSE_GENRE_PROTOTYPE_OUTPUT`,
`OPENNOISE_SPARSE_GENRE_PROTOTYPE_OBJECT_STORE`, and
`OPENNOISE_SPARSE_GENRE_PROTOTYPE_RECEIPT`.

## Full-corpus checkpoint

The sealed full-corpus run used 6,291 seeds, 815,723 raw positive evidence
rows, and 212,696 contextual tag rows. It deduplicated direct supervision to
421,427 seed-artist pairs, trained 2,191 feature-backed prototypes, and wrote
24,623 neighborhood candidates. On 84,072 held-out positives, 42,610 had a
sparse retrieval score: recall@25 was 0.19444 and MRR was 0.16825. The other
41,462 positives abstained because no sparse score existed.

The logical artifact hash is
`e2571cc2805b095e56f2788d88f5a7ab4e12770dac70de993a843b6ca4ce0ab9`.
These candidates are broad contextual neighborhoods only; they are not
parent-child or subgenre assertions.
