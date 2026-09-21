# Next direct-signal audit

## Finding

The highest-yield locally retained signal that can expand direct artist to map
genre coverage is the already ingested, export/display-authorized Wikidata
`P136` evidence behind the direct-catalog bridge review packet. It is a factual
source observation, unlike the much larger MusicBrainz tag matrix (review
context only), Last.fm archive (diagnostic only), or H3 (historical evaluation
only). No historical Every Noise artist observation is involved: the packet
preserves the Wikidata evidence ID, source record, method, and provenance for
each proposed presentation bridge.

## Measured ceiling and gate

The current static asset exposes 2,900 of 4,948 authorized direct observations,
for 1,008 artists on 260 of 2,945 placed nodes. The retained bridge audit has
197 not-currently-bridged edges: 101 review-only, 67 conflicting/ambiguous, and
29 safe-exact-but-still-pending. Its summed lift is 1,520 candidate-observation
rows (not a deduplicated publication count) across 139 positive-lift target
nodes and 124 catalog genres. The packet reduces those to 1,343 distinct direct
`P136` evidence IDs for 709 artists. Of those artists, 122 are absent from the
current static asset; therefore 1,130 artists is only an all-approved upper
bound, not a forecast.

The exact serving gate remains: a catalog label must casefold-match exactly one
**placed** map label, that node must bind to exactly one catalog genre, and the
evidence must be `direct_source_claim` with both export and display rights
allowed. For a non-current edge, the hash-bound audit and packet must first be
recomputed against the same database/static asset; two independent reviewers
must append `approve` decisions to the review ledger before an edge is
`ready_for_separate_publication`. `safe_exact` is not an automatic promotion,
and that state still needs its separate publication gate.

## Evidence

| Input | SHA-256 |
| --- | --- |
| `data/public.sqlite` | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |
| static discovery asset | `b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8` |
| direct bridge audit | `9e3f7d4b7c58657c23909542f644266dd59e12a361edb597a9fc9ad895efd461` |
| human review packet | `e5a2e4112cf553d4c148c7be4a8d8c1ebb7b515cf9f0cde8994f526fa511e9e9` |

## Bounded next task

Review only the highest-lift pending edges whose target has no current static
bridge, using the existing packet's Wikidata provenance (start with the 29
safe-exact edges, then submit individually justified decisions for ambiguous
ones). Recompute the audit and append two independent approval decisions per
edge without modifying the catalog or static asset; report approved unique
evidence IDs, artists, and target nodes before proposing a separate
static-export publication candidate.
