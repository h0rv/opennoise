# Portable direct-source neighborhood experiment

The local experiment constructs a useful neighborhood graph from the portable
MusicBrainz direct proper-genre custody: **387,435 unique artist–seed observations,
198,409 artists, and 697 observed seeds**. It requires neither the ignored raw
archives nor historical memberships, coordinates, H3 labels, artist names,
release-group support, or tags. Names can be joined later for display.

The selected model recovers **32,935 of 77,206 held-out observations at rank 10**,
versus 32,615 for binary cosine. This is a small descriptive improvement of
**0.4145 percentage points**, not a significance claim or independent quality
certification. The artifact remains local research and cannot authorize a public
export, factual membership promotion, or serving change.

## Construction and evaluation

[`direct_custody_neighborhoods.py`](../../src/opennoise/ml/direct_custody_neighborhoods.py)
verifies the checked-in compressed custody object against its receipt and
deduplicates exact artist–seed pairs. It reuses the existing sparse cosine engine
in `ml/full_graph_signal/sparse_baselines.py`; the comparison is a real-corpus
extension of that engine rather than a separate dense or fixture-only model.

The existing deterministic split orders artists within each seed by
SHA256(seed ID, NUL, artist MBID), withholds the lowest fifth, and retains at least
four training observations. Applied twice, this creates:

| Partition | Direct observations |
| --- | ---: |
| Inner training | 248,460 |
| Validation | 61,769 |
| Outer training, including validation | 310,229 |
| Untouched test | 77,206 |

All artist degrees, genre frequencies, shared counts, cosine norms, graph
neighbors, and transfer scores are recomputed from the appropriate training
partition. The four arms and tie rules are fixed before testing. Validation
Recall@10 selects the arm, with MRR@10 and declared arm order resolving ties;
the selected arm is not changed after inspecting test results. A separate final
fit uses the full source only to provide a browsable candidate graph.

Each genre retains up to 20 cosine neighbors supported by at least two shared
training artists. Artist degree weighting scales each artist row by
`1 / sqrt(training genre degree)`. Shrinkage multiplies a genre edge by
`shared_count / (shared_count + 5)`. Specificity transfer additionally divides
each source-genre contribution by `sqrt(training source-genre artist count)`.
Known training genres are excluded from each artist's prediction ranking.

| Fixed arm | Validation Recall@10 | Test Recall@1 | Test Recall@5 | Test Recall@10 | Test macro seed Recall@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Binary cosine | 37.1432% | 14.3279% | 33.2422% | 42.2441% | 31.0880% |
| Artist-degree cosine | 37.2436% | 13.9070% | 33.1852% | 42.1211% | 32.3452% |
| Degree cosine with shrinkage | 37.7131% | 14.2165% | 33.4663% | 42.3257% | 30.2018% |
| **Specificity transfer, selected** | **37.9980%** | **14.3940%** | **34.1476%** | **42.6586%** | **33.2107%** |

Degree weighting alone loses micro recall to binary cosine. Shrinkage alone
also hurts the smallest support group. The final frequency adjustment improves
both overall and macro recall in this fixed split; the report preserves every
arm rather than presenting only the winning comparison.

## Coverage and limits

The test evaluates 687 of the 697 source seeds. Ten seeds have too few source
observations to hold out while retaining four training rows, so they are not
included in macro recall. Validation evaluates 685 seeds. No result measures the
remaining historical name universe, and the source-only model does not invent
observations for seeds missing from custody.

| Outer-training support | Evaluated seeds | Test positives | Binary hits@10 | Selected hits@10 |
| --- | ---: | ---: | ---: | ---: |
| 4–20 observations | 123 | 323 | 61 | 65 |
| 21–100 observations | 245 | 3,033 | 883 | 965 |
| Over 100 observations | 319 | 73,850 | 31,671 | 31,905 |

All test positives remain in the denominator, including **26,598 positives on
artists with no remaining training observations**. The selected graph can score
44,260 test positives; the other 32,946 abstain. The small-support result has only
323 positives and four additional recoveries, so it does not establish reliable
niche-genre quality.

This evaluation reconstructs missing observations from the same source. It is
not an independent source gold set, a test of new artists, a ranked relevance
judgment, or reproduction of the historical Every Noise model. Missing claims
are unknown rather than negative labels; no precision result is claimed.

The full refit has 683 supported genres, 14 overlap abstentions, 10,868 directed
genre-neighbor edges, and 13,642 inferred artist proposals. The artist proposals
reverse the score direction to rank artists within a genre. **Their ranking is
not validated by the artist-to-genre recall table.** Each proposal retains the
direct source genre IDs contributing to its score, under `via_seed_ids`.

A separate bounded `artist_neighbors` query ranks artists by IDF-weighted cosine
over shared direct genres and requires at least two shared genres. Exactly
82,571 artists have such a neighbor; 115,838 abstain, including all 115,512 artists
with a single source genre. Query results include their shared seed IDs. This
artist-to-artist ranking is likewise not validated by genre recovery.

## Local artifacts and reproduction

The completed run is under
`.cache/direct-custody-neighborhoods/run-20260930-final/`:

- `model.json`: source-bound genre graph and explicitly inferred artist proposals.
- `observations.npz` and `identities.json`: full sparse source observation matrix
  and canonical sorted IDs for local queries.
- `report.json`: input hashes, construction and split code hashes, runtime
  versions, formulas, bounds, all arm metrics, strata, and output byte bindings.

The model byte SHA-256 is
`906f633c8967bc1b7d5d8d67a3505143b6fb6c7489afda7395aed937ab1a1cc3`.
The report logical SHA-256 is
`3d723c11f840f3b6e92a39cd25b9eaeb66ff03367806f931f1408f31e62686d6`.
The direct source object SHA-256 is
`b1fc1ac9428832cb4543710b716e2d47eb8cc62dc052ed4d768ffb27dd1dcc3e`.

From the repository root, after the existing `poe sync` setup, run:

```sh
.venv/bin/python scripts/build_direct_custody_neighborhoods.py \
  --output .cache/direct-custody-neighborhoods/replay-20260930
```

The destination must be new and below this checkout's `.cache`; existing runs
are never overwritten. No network access is needed. `load_neighborhood_index`
verifies the report logical hash and all three artifact byte bindings before
loading the query matrix. A caller can then use `artist_neighbors(index, mbid)`.

Sparse expansion fails before cooccurrence if artist degree exceeds 256 or
genre pair visits exceed 5,000,000; it never silently truncates an artist profile.
There are at most 1,000 genres and 1,000,000 artists, and evaluation processes
512 artist rows at a time. No all-artist-pairs matrix is constructed. Canonical
IDs resolve equal-score cutoffs deterministically.

Ten focused tests cover held-out target exclusion, nested split disjointness,
inner/outer fit orchestration, validation-only selection despite reversed test
ordering, cold and single-overlap abstentions, exact shrinkage behavior,
cutoff-tie determinism, sparse bounds, artist-query explanations, forbidden
public destinations, and artifact byte tampering. The focused tests, Ruff, and
type checks pass. Two actual corpus runs produced identical prediction metrics;
an independent read-only replay reproduced the original selected-arm metrics.
