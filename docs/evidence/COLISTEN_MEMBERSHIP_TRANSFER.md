# Co-listen membership transfer

`uv run poe build-colisten-membership-transfer` writes a local, receipt-bound
review artifact under `.cache/colisten-membership-transfer-v1/`. It needs no
environment variables and reads only the sealed v2 evidence graph plus the
privacy-thresholded ListenBrainz aggregate co-listen sidecar.

The channel is deliberately narrow. For an artist with no direct
`artist_direct` membership, it aggregates the direct labels of co-listening
artists using `log1p(distinct_user_count)`. It emits only
`review_only_not_factual_membership` candidates. It never writes the evidence
graph, public catalog, serving model, or a factual membership claim.

Every candidate retains its source MusicBrainz artist ID and bounded exact
co-listen evidence fingerprints with their aggregate user counts. The candidate
field `summed_distinct_user_support` is a sum across aggregate rows; it is not a
deduplicated global listener count. Raw listens, listener IDs, audio, and
historical H3/Every Noise inputs are not read.

The input receipts must bind one another exactly: the aggregate co-listen
sidecar must bind the same graph receipt as the graph database. The artifact
also records byte hashes and counts for both databases and receipts. It fails
closed if the bounded candidate count exceeds its declared cap rather than
truncating artist coverage by sort order.

## Evaluation

Evaluation is positive-only. Direct `(artist, seed)` pairs are deterministically
split before source labels are aggregated. A target's held-out edge is not a
feature; a source artist's held-out edge is likewise unavailable to every
target. Artists with a remaining train-side direct label are excluded from the
cold-target evaluator. Unknown pairs are not negatives, and the report makes no
precision claim.

The artifact reports recall@10 and recall@25 beside two non-tuned ablations:

- train-only global direct-label popularity, using exactly the same edge split;
- no-co-listen/direct-only cold retrieval, which cannot transfer absent labels.

The local v2 replay on 2026-09-20 had 1,455 aggregate co-listen artists. Of
those, 66 had no direct label; 60 received at least one review candidate and 6
abstained. It emitted 402 candidates while preserving all 6,291 stable seeds.
The held-out cold cohort was small: 45 positives across 34 artists. Transfer
recalled 29/45 at 10 and 32/45 at 25 (0.6444 / 0.7111); the same-split global
popularity baseline recalled 15/45 at both cutoffs (0.3333 / 0.3333), a delta of
+0.3111 / +0.3778. The direct-only cold ablation was 0. These are checkpoint
diagnostics, not a promotion decision or a precision estimate.
