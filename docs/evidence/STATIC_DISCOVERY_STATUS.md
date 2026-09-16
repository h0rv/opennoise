# Static discovery status

The static map can publish direct artist discovery without a backend or audio.
It reads only the export- and display-authorized catalog snapshot
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`.

| Current snapshot output | Count |
| --- | ---: |
| Map names / placed nodes | 6,291 / 2,945 |
| Exact one-to-one catalog-label bridges | 294 |
| Map genres with direct artists | 260 |
| Artists with a mapped direct genre | 1,008 |
| Direct P136 observations on mapped labels | 2,900 |
| Direct P136 observations in the authorized catalog | 4,948 |
| Source partitions | 8 Wikidata artist partitions |

The bridge is presentation only: a catalog genre may appear on the map only
when its casefolded name names exactly one placed map label. It does not infer
membership, expand aliases, or create a relation from a name resemblance.

The exported flow is map genre → direct-source artists → each artist's direct
mapped genres → artists with one or more shared direct mapped genres. Shared
artist relations include their shared genre IDs and a Jaccard score in JSON;
they are not listener similarity claims. Structural map connections remain a
separate graph signal.

No direct observation for a map label is an explicit empty state. The 3,346
unplaced names, unmatched labels, candidate or propagated memberships,
historical Every Noise assignments, non-public peer indexes, and all audio are
excluded. A privacy-safe co-listen snapshot exists locally (30,903 aggregate
rows), but its current display policy denies serving it; it is an offline/model
signal, not a product relation.

The next useful data work is broader direct catalog coverage and audited
identity bridges, then independently evaluated promotion of any derived
membership or similarity signal.
