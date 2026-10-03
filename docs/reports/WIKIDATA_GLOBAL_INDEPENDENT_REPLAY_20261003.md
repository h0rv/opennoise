# Independent bounded Wikidata replay review

Reviewed the in-progress `evidence` worktree implementation of
`src/opennoise/ingest/wikidata/global_artist_genres.py` and the frozen pack at
`/workspace/opennoise/.cache/wikidata-global-musical-artists-20261002-v1` on
2026-10-03. This was a read-only robustness and evidence review; the pack was
not modified. Implementation fixes were sent to the enrichment agent.

## Independently reproduced evidence

The pack has exactly 25 files: its four control/projection files, one initial
response, and 20 follow-up bodies. Their hashes match the receipt. Its receipt
SHA-256 is `555465b856ed3446a3a7486eed61284bb9b420f0d3c3136a31bec564d5b125fb`.
The raw response bodies sum to 7,199,783 bytes, matching the manifest.

The usable capped scan yields 19,997 valid rows and three explicitly quarantined
rows, representing 19,144 distinct canonical artist UUIDs. I verified the bound
MusicBrainz core receipt and compressed-table SHA-256, streamed all 2,999,670
identity rows, and independently reproduced 18,952 eligible source UUIDs and
192 absent core UUIDs. I rederived the SHA-256 ranking and the selected roster:
exactly 3,000 distinct UUIDs, in the recorded order, with native names matching
the core input. No name-based join was used.

All recorded follow-up query hashes match queries reconstructed from their
requested values. Requested artist pairs are exact selected UUID/QID pairs
from the initial source scan; genre requests belong to unambiguous candidates.
Every accepted artist response stays within its recorded requested pair set.
Raw projection replay preserves every selected ID once, including unresolved
IDs, and closes the denominator:

| Identity outcome | IDs |
| --- | ---: |
| Exact P434 pair and normalized core-name match | 539 |
| Detail unavailable | 2,194 |
| Core-name mismatch | 96 |
| English label missing or ambiguous | 15 |
| QID reused for multiple UUIDs | 155 |
| UUID associated with multiple QIDs | 1 |
| Total | 3,000 |

The 539 resolved rows contain 563 direct source P136 values. All other rows
have empty claims. This is bounded source assertion evidence. Name coherence
and P31 context do not certify musical fit, artist genre truth, or complete
Wikidata coverage. The capped scan can omit other QIDs, identities, and claims.
This review grants no serving or release authorization.

## HTTP ledger limit

Six initial large artist batches preserve HTTP 503 metadata; the genre-label
batch preserves HTTP 200 metadata. Thirteen subsequent bodies cover 650
requested artist pairs, but their capture process lost the HTTP ledger. Their
status correctly remains null. Their content and deterministic requested-pair
plan are replayable; HTTP success and historical request timestamps cannot be
recovered from those bytes. JSON parsing proves syntactic completeness, not a
successful HTTP exchange. The recorded hydration timestamp must describe
recovery work, not the lost captures.

## Implementation fixes requested

At inspection, the generic verifier trusted selected core names and the
recorded roster rather than independently enforcing the bound core input and
full eligible-cohort hash ranking. It also omitted follow-up query-plan
validation, admission checks on ordinary HTTP status/body completeness, exact
response-byte summation, and a closed file set derived from the request plan.
A self-rehashed receipt is insufficient to validate these contracts. Failed
captures must still have a recognized kind and valid request binding.

I requested that these checks move into ordinary offline verification, with
focused tampering regressions, while preserving a distinct admission rule for
the explicitly recovered unknown-status bodies. The QID parser should reject
foreign schemes and query/fragment suffixes on otherwise valid entity paths.
The independent checks above validate this particular frozen pack; they do
not substitute for those verifier repairs or constitute their final review.
