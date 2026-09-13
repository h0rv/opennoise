# ListenBrainz dual overlay

`uv run poe build-listenbrainz-dual-overlay` builds or verifies two separate,
receipt-bound SQLite sidecars in `.cache/listenbrainz-dual-overlay-v1/`.
The task has pinned local defaults and needs no exported environment variables.
If the complete checkpoint already exists, the same command verifies both
sidecar receipts, database bytes, and every pinned source byte instead of
overwriting anything.

The derived-review sidecar contains `derived_review_evidence_not_factual_membership`.
It preserves the propagation score, rank, full direct-anchor/co-listen path,
and source provenance for every retained artist-to-seed candidate. It validates
the exact `legacy:item…` to `item…` bridge against the graph identity table.
It is never written into the evidence graph's factual `claim` table.

The co-listen sidecar contains only canonical-undirected,
privacy-thresholded aggregate observations. Every row retains its two graph
artist IDs, start/end window, distinct-user count, fingerprint, source binding,
and provenance reference. It is evidence, not a learned artist-similarity edge.
Raw listens, listener identifiers, audio, and historical data are not read.
The retained raw fields intentionally support a later, separate genre projection
that can compare degree-normalized log co-listen, NPMI, and support-shrunk
signals without collapsing those choices into this checkpoint.

Both receipts bind the exact v2 graph database and receipt. The review receipt
also binds the sealed propagation artifact and receipt. The co-listen receipt
also binds the qualified SQLite input
`282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866`.
Input dispositions are mutually exclusive and exhaust every source row.

The first real build took 119.6 seconds:

- Review candidates: 23,497 input, 23,422 retained, 75 graph-artist abstentions.
- Co-listens: 30,903 input, 30,433 retained, 470 graph-endpoint abstentions.

The review database SHA-256 is
`5ef2a6bceb198fd9d74f5a5506835fe1ec81a3134d8eeb1b91027bb0b16325d3`
(123,908,096 bytes), with logical receipt
`b697210abc1032089b69013f604c58aed26b175bf2ce9b7ecf0cec216dbe09d2`.
The co-listen database SHA-256 is
`bea7666d073cc0caaef44042a893b9551ea9cadf189a72a6b8eaf7272b05bd5f`
(19,689,472 bytes), with logical receipt
`7fe2eed2608cf8b03d9c61806ed0e9914a538fdd389014162e378f31448080c6`.

The durable artist-name sidecar is likewise under
`.cache/evidence-graph-v2.artist-identities-v1/`; it is never kept only in an
agent worktree.
