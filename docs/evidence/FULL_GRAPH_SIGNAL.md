# Full graph signal baseline

This is the first real sparse model checkpoint over the sealed v2 evidence
graph. It streams and deduplicates positive
`musicbrainz_artist → stable_seed / artist_membership` claims into complete
artist--seed pairs. Pair splitting happens after that collapse, so every claim
for a held-out pair stays out of train.

Implementation is deliberately separated into typed contracts, sealed
input/cache handling, sparse baselines, positive-only evaluation, and a small
pipeline orchestrator under `opennoise.ml.full_graph_signal`.

The builder writes train-only `float32` SciPy CSR matrices with shape
`artist_count × 6,291`. Their cache filenames derive from the graph receipt,
construction certificate, and settings hashes. The baseline compares binary
Jaccard overlap, weighted cosine overlap, PPMI, and a direct-only binary
ablation. It does not run SVD in this first checkpoint; the artifact records
that explicitly rather than implying a comparison.

The cached matrices retain every deduplicated pair. To keep sparse
co-occurrence multiplication laptop-safe, feature construction deterministically
caps the number of train genres contributed by one artist (32 by default); the
setting and resulting cache key are recorded in the artifact.

Metrics are positive-only. They report Recall@1/10/25, score coverage, and
abstention for complete held-out open membership pairs. A split-cold seed (no
training membership support) is never assigned a fabricated score and is
reported separately from anchored labels. Genre-peer recovery is induced only
from pairs held out of the same open membership graph. It is not a claim that
unobserved pairs are negative.

Artist-set containment produces review-only asymmetric parent candidates. It
is acyclic only when a later taxonomy review accepts it; this checkpoint never
promotes candidates, forces one parent, or projects coordinates.

The sealed graph currently provides MusicBrainz direct/release-support and
reviewed alias-context memberships. It does not materialize artist-level
ListenBrainz similarity. Receipt-bound ListenBrainz candidates, hierarchy
candidates, compositional open-construction relations, and exact artist-name
metadata are future adapter overlays; the sparse core consumes the same
complete pair representation rather than assuming those sources are present.

Run with:

```bash
uv run poe build-full-graph-signal
```

The task uses `OPENNOISE_EVIDENCE_GRAPH_DATABASE`,
`OPENNOISE_EVIDENCE_GRAPH_RECEIPT`,
`OPENNOISE_EVIDENCE_GRAPH_CONSTRUCTION_CERTIFICATE`,
`OPENNOISE_FULL_GRAPH_SIGNAL_CACHE`, `OPENNOISE_FULL_GRAPH_SIGNAL_OUTPUT`, and
`OPENNOISE_FULL_GRAPH_SIGNAL_RECEIPT`, and `OPENNOISE_FULL_GRAPH_SIGNAL_RUN_REPORT`.
The run report records elapsed time and peak process RSS separately from the
replayable logical artifact.

## Recorded capped v2 run

The receipt-bound cached run at
`.cache/full-graph-signal-v2/artifact.json` has logical hash
`6b992c2faa3cfd41b90fd6b986905c2942d1cd4f8aedbf71242bc39ae5b609e0`.
It binds evidence-graph receipt
`abb516066320039386517871eebb850d79f3c535c603411853f9c8eaf7dc7ce6` and
construction certificate
`a28768b0e121aea7a765dee255a87dcc60d304802da1f8ee922d44793fc894de`.

It streamed 5,591,670 claims into 1,773,093 complete pairs (1,416,893 train;
356,200 held out), across 552,283 artists. The bounded evaluation sampled
5,000 held-out artists: 7,403 anchored targets had 86.40% score coverage
(1,007 abstentions), while the four split-cold targets were all abstained and
never scored. The direct-only ablation covered only 34.24% of its anchored
targets, which is concrete evidence that release-group support carries most of
the useful signal.

| Baseline | Anchored Recall@10 | Anchored Recall@25 |
| --- | ---: | ---: |
| Binary Jaccard, all open memberships | 0.5113 | 0.6755 |
| Weighted cosine, all open memberships | 0.5059 | 0.6561 |
| PPMI, all open memberships | 0.0590 | 0.1143 |
| Binary Jaccard, direct-only ablation | 0.1646 | 0.2276 |

The same-artist held-out co-membership proxy recovered 17.95% at 10 and
33.12% at 25 over 3,119 positive-only pairs; it is an open-evidence proxy, not
proof of semantic peer quality. Artist-set containment emitted 218 review-only
candidates for 164 children, with 43 children retaining multiple parents. No
candidate was promoted to factual hierarchy. The corrected score ordering
makes PPMI a clearly losing baseline; earlier stronger PPMI figures were not
comparable because sparse column order had incorrectly been used as rank order.

The initial cached run took 110.417 seconds and 485,096 KiB peak RSS. A warm
replay reused the verified pair/matrix sidecars (without a claim scan), wrote
an identical logical artifact, and took 56.198 seconds at 484,892 KiB peak
RSS. These numbers are a membership-propagation checkpoint only: no
artist-level ListenBrainz similarity, regional/era overlay, or taxonomy review
evidence is materialized in this graph yet.
