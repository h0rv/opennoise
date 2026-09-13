# Hierarchy fusion baseline

This checkpoint builds a source-neutral, overlapping child-to-parent DAG for
all 6,291 stable genre seeds. It is a review baseline, not a claim that a
single taxonomy is true.

Construction binds eight immutable local inputs: seed reconciliation; the
evidence graph and its receipt; exact Wikidata P279 facts; the 66,132-row
public candidate corpus and its publication receipt; and the sealed full-graph
containment artifact and receipt. The candidate receipt must bind its 683,580,146
bytes, 66,132 rows, complete seed coverage, and a false historical-construction
flag. All bindings are stored as portable role-relative locators plus byte and
logical hashes.

Exact `wikidata_p279_subclass_of` rows stay factual evidence. Lexical and
artist-set containment remain review proposals with their source-local score,
counts, and provenance. The projection accepts facts first, then review edges,
rejecting self edges and cycle-closing edges while retaining their audit row.
This makes multi-parent structure possible without relabeling a rejected fact.

Review thresholds are picked only from a deterministic calibration split of
open factual P279 pairs. The policy chooses the highest threshold within 0.02
of the best calibration recovery. The holdout split is scored only afterwards.
Historical Every Noise and H3 products are excluded from construction and
threshold selection.

Run the sealed local checkpoint with:

```bash
uv run poe build-hierarchy-fusion
```

The H3 map is available only for a post-build co-assignment diagnostic:

```bash
uv run poe evaluate-hierarchy-fusion-h3
```

It reports whether an accepted DAG relation falls in the same H3 umbrella,
subcommunity, or microgenre. It neither supplies labels nor affects the DAG.
The current H3 cache artifact passes structural validation but its embedded
logical hash does not replay under its producer's canonical function, so this
diagnostic binds its exact bytes and marks the claimed logical hash unverified.

## Recorded laptop checkpoint

`artifact.json` logical hash:
`a37dc0e66e706cdfcb191a3fbb8792d7af4b069a612ec0e8a6062be825236d7e`.
The run took 56.840 seconds and 402,132 KiB peak RSS.

It preserves 216 factual source edges, all 216 in the DAG. It adds 2,448
review edges at threshold 0.25, rejects 63,510 below-threshold candidates and
one cycle, leaves 275 children with multiple parents, has 3,967 undirected
components, and has maximum depth 5. Seed states are 234 observed, 2,127
review, 1,077 abstained, and 2,853 isolated.

The calibration split contains 49 factual edges. Its recovery is 0.346939 at
the selected threshold; the untouched 46-edge factual holdout recovers 10
(0.217391). The artifact records every threshold's review-edge volume. These
are positive-only recovery measures, not a taxonomy accuracy claim.

The separate H3 diagnostic covers all 2,664 included DAG edges: factual edges
share an umbrella 40/216 (18.52%), while review edges share one 492/2,448
(20.10%). Combined co-assignment is 532/2,664 umbrellas (19.97%), 284/2,664
subcommunities (10.66%), and 160/2,664 microgenres (6.01%). This is
evaluation-only and byte-bound, not an H3 hierarchy correctness claim.
Target paths such as IDM to braindance, drill-and-bass, and ambient techno are
recorded as supported or missing diagnostics; no path is fabricated when the
stable seed universe or open evidence lacks a hop.
