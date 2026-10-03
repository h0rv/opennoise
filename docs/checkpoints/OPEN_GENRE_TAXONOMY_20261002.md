# Independent CC0 genre taxonomy, October 2, 2026

The new [portable pack](../../data/examples/open-genre-taxonomy/README.md) supplies
source-independent Wikidata genre entities and typed taxonomy observations.
Existing Wikidata adapters either resolve historical seed names or join artist
context through exact MusicBrainz identities. This adapter uses neither path:
it verifies Wikidata's `Q188451` music-genre class, then captures at most 1,000
entities with direct `P31 Q188451`. Selection uses no historical names, artist
IDs, P434, MusicBrainz tags or benchmark cohort.

The exact selection query and bounded follow-up policy were written to
`query-plan.json` before any request. The selection does not sort the global
Wikidata result set; the response's arbitrary endpoint order is frozen by its
raw byte binding. That avoids an expensive global sort but introduces selection
bias. Five sorted exact-ID batches of 200 request `P31`, `P279`, and optional
English labels. Each is bounded by `LIMIT 2000`.

| Measured output | Retained result |
| --- | --- |
| Class verification | Q188451 exact entity, English label `music genre` |
| Source-selected entities | 1,000; selection cap hit, possibly truncated |
| Typed direct-property observations | 3,091: 1,549 P31 and 1,542 P279 |
| Follow-up rows by batch | 630, 651, 602, 603, 605; no 2,000-row cap hit |
| Entities missing taxonomy rows | 0 within the selected cohort |
| Entities missing English labels | 2: Q3071 and Q704073 |
| Requests / HTTP failures | 7 / 0 |
| Source body bytes | 2,092,096 |
| Artist memberships / inferred levels | 0 / none |

All sources and the permitted structured projection are Wikidata CC0-1.0.
The source responses, observed times, HTTP outcomes, exact URL/query strings,
request timing and byte budgets are preserved in the manifest. Every claim has
an exact genre QID, explicit property ID and role, target QID, available English
labels, source capture identity, hash, URL and observed time. Instance-of and
subclass-of remain separate. Labels and targets are source observations, not
reviewed community names. Targets outside the selected cohort remain explicitly
outside that source-type confirmation boundary.

The source queries capture direct truthy properties, without statement ranks,
qualifiers or reference statements. Observation dates are client capture dates,
not a consistent Wikidata dump snapshot. These limitations remain visible.
The pack can seed independent vocabulary and source taxonomy browsing; it does
not provide artist memberships, independent musical relevance, broad/sub/micro
granularity, reviewed genre equivalence, full-corpus reconstruction or parity.

Verification recomputes the entire projection from raw responses after checking
every source and projection byte binding. It enforces the frozen query policy,
exact returned source cohort, sequential request ledger, canonical QIDs, typed
P31/P279 roles, safe file paths and request/byte budgets. Failure responses and
possibly truncated batches remain report data rather than invented facts.
No network requests occur in verification.

```sh
.venv/bin/python scripts/capture_open_genre_taxonomy.py \
  --output data/examples/open-genre-taxonomy --verify
```

Nine adversarial tests cover successful raw replay, cap hits, missing labels,
endpoint failure, response byte caps, forbidden contextual properties, fake
entity URIs, unrequested entities, query/cohort tampering, symlinks, and changed
projection semantics even with updated receipt hashes. The checked-in live pack
also replays offline. Source custody success supplies construction evidence;
the [full-foundation acceptance gates](../foundation/ACCEPTANCE.md) remain unmet.
No deployment or product/model promotion is included.
