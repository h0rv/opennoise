# Fixed artist rank evidence from historical FMA44 predictions

The optional ranked artist view addresses a limitation of the saved-membership
export: eleven calibrated labels yield broad, often tied frequency counts. It
uses full existing saved track ranks to expose at most ten artist-level source
annotation candidates. It leaves calibrated memberships, source predictions,
identity joins, all abstentions and original partitions unchanged.

For each artist/genre, the fixed score is the sum of reciprocal saved track ranks
divided by **all nominated tracks** for that artist. Abstained tracks contribute
zero through the denominator. Ties break by native genre ID. The scores are not
probabilities, the candidates have no membership calibration, and no labels are
added to calibrated `genre_evidence`. An entirely abstained artist stays empty.
Only saved model rankings enter the scorer; target tags enter the separate audit.

## Use the existing export command

Follow the membership materialization and externally pinned export command in
[the membership recipe](../fma-source-memberships-v1/README.md), adding
`--rank-artists` and choosing a fresh output path. The flag requires
`--export-artists`; omitting it retains the prior export view.

Each artist gains `ranking_supported_track_count` and
`ranked_source_annotation_candidates`, including genre ID, mean reciprocal track
rank and contributing track count. The opt-in artifact has its own revision and
records the ranking implementation and fixed protocol hashes. The same 24 MB,
110,000-native-row and 120-second/1-GB CLI bounds apply.

The checked export has SHA256
`e47508c2ef02315714a003aaf727abbffada3f7dcc96152679fcd3e35c1bdf1b`
and is 4,836,095 bytes. All 1,714 artist identities and their calibrated evidence
match the unranked view. The 95 artists whose saved tracks all abstain keep empty
rankings; query coverage is unchanged. Ranked candidates span 144, 142 and 145
distinct source genre IDs in the three respective partitions; these are
uncalibrated candidates, while calibrated memberships retain eleven labels.

## Reproducible historical diagnostic

`protocol.json` was frozen before the diagnostic computation, with SHA256
`971efc50e483c189b0fbabe68ae29840704675c8f48a980cccb99f60d2b294c8`.
It specifies one reciprocal-rank rule, one baseline, top ten, native-ID ties,
source-positive target union and all three original partitions. No parameter
search or retuning was performed. The baseline ranks genres by existing saved
calibrated-membership track count, with the same ID tie-break and top ten.

The audit uses the union of observed source track genre IDs per artist as
incomplete weak positives. Macro recall averages over artists with any observed
positive; positive-weighted recall counts those positive genre associations.
Artist coverage includes every nominated artist, including unlabeled artists and
abstentions. No precision or verified-negative claim is made.

| Historical partition | Artist-averaged recall@10: counts → ranks | Positive-weighted recall@10: counts → ranks | Artist coverage, both |
| --- | ---: | ---: | ---: |
| Calibration | 36.68% → 42.86% | 37.33% → 39.33% | 94.70% |
| Confirmation | 38.95% → 41.10% | 39.53% → 38.61% | 94.63% |
| Previously observed diagnostic test | 34.44% → 42.74% | 35.08% → 39.55% | 94.23% |

The confirmation positive-weighted result regresses (387 → 378 recovered source
associations). This is a mixed tradeoff, so the ranked view is opt-in and does
not replace the calibrated output. Historical FMA44 source-annotation recovery
is neither listener-quality evidence nor a result for the FMA518 five-fold model.
The diagnostic test and earlier aggregates were previously observed; no fresh
heldout claim, generalization guarantee, model selection or promotion follows.

Recompute all values from the generated ranked export and the checked-in targets:

```sh
.venv/bin/python data/recipes/fma44-artist-ranking-20261018/audit.py.source \
  --export /path/to/ranked-export.json \
  --export-sha256 e47508c2ef02315714a003aaf727abbffada3f7dcc96152679fcd3e35c1bdf1b \
  --saved-pack data/examples/fma-acoustic-baseline
```

`results.json` retains all counts and denominators. The independent audit reads
the consumer export rather than invoking the ranker again, validates its external
hash and protocol, replays the target pack and checks the complete artist track
sets before counting positives. No raw feature download, waveform, refit, new
calibration, Library transfer, UI or service cost is involved.

## Optional artist profile neighbors

The same replay can optionally export native artist evidence and retrieve six
neighbors from each artist's top-ten mean reciprocal track ranks:

```sh
.venv/bin/python scripts/replay_fma_memberships.py \
  --saved-pack data/examples/fma-acoustic-baseline \
  --memberships /tmp/fma-source-memberships-v1 \
  --export-artists /tmp/fma-artist-profile-neighbors.json \
  --rank-artists --artist-neighbors \
  --saved-pack-receipt-sha256 3e1651c136f5ae0c588e6dd6930a7a8f68fc7b332d1e423d29d1657e20cd0106 \
  --membership-receipt-sha256 ad54dc99a09e0c0f492dd97ac21e216a4a70bfd39a7749932a6f1a1a45646c1d
```

This opt-in uses cosine similarity over the retained rank profiles, keyed by
native genre ID. Each named historical partition supplies its own candidate
pool; none is a training pool. Retrieval excludes the full query component,
selects at most one artist per other component, breaks exact ties by native
artist ID, and requires positive profile overlap. Empty profiles and queries
without eligible overlap abstain explicitly. Candidate references resolve to
profile evidence in the same partition; edges retain shared genre IDs, component
IDs, track-support counts and cosine distance. `eligible_candidate_artists` and
`eligible_candidate_components` count nonempty other-component profiles before
positive-overlap filtering, including when the query profile is empty. They do
not count selectable neighbors. Existing memberships and ranked profiles are
unchanged. Pools are capped at 2,000 artists per partition and the
existing 24 MB export limit remains in force.

The retained example has 1,714 artists: calibration emits 2,682 edges for 447
artists with 25 empty profiles; confirmation emits 2,328 for 388 with 22 empty;
historical test diagnostics emit 4,704 for 784 with 48 empty. Independent
intersection-based tests verify every edge and distance against the saved
profiles. These are model-rank-profile similarities: acoustic similarity,
listener relevance and held-out quality remain unestablished. This does not
consume FMA518 features or authorize product promotion.

The checked neighbor export has SHA256
`62f47c4144129483dcacde8c3d564820007c96200a46ca1936e230e10bd21bc4`
and is 6,874,277 bytes. It contains 9,714 directed edges. An independent NumPy
dense-matrix oracle matched every artist's ordered neighbor IDs, with zero
ordering mismatches and maximum cosine-distance difference of 4.44e-16. All
edges passed separate checks for same-partition membership, self/full-component
exclusion, distinct neighbor components and exact shared genre support. No
source labels entered this neighbor computation or either edge audit.

`tests/test_fma_artist_neighbors.py` runs the pinned replay command against the
retained data, independently reconstructs every ordered edge and distance using
dictionary intersections, and confirms that removing only the new neighbor
fields recovers the ordinary ranked partitions exactly. Synthetic fixtures cover
native-ID ties, component exclusion, empty and disjoint profiles, and malformed
weights. No model quality experiment or change to evaluation gates is involved.
