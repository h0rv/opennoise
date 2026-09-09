# Local peer similarity research index

This is a local-research tool for the sealed full MusicBrainz peer candidate.
It is deliberately not a public API, map input, or export artifact. The input
gate records `all_inputs_export_allowed=false` and the candidate is marked
`non_production_candidate=true`.

Build the compact, receipt-bound SQLite index without rebuilding the peer
model:

```bash
uv run python scripts/local_peer_similarity.py build \
  --artifact .cache/musicbrainz-full-seed-targets/pipeline/peer-similarity.json \
  --gate .cache/musicbrainz-full-seed-targets/pipeline/peer-similarity.gate.json \
  --historical-receipt .cache/musicbrainz-full-seed-targets/pipeline/peer-historical-evaluation.receipt.json \
  --reconciliation .cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json \
  --output .cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite
```

The builder streams the 817 MiB candidate JSON with `ijson`; it does not load
the corpus or candidate list into RAM. It refuses an exportable gate, an
unpassed gate, a receipt bound to another candidate output hash, or an existing
final/partial output. It writes a sibling temporary SQLite database and only
renames it into place after the complete transaction.

Query a stable retained seed key:

```bash
uv run python scripts/local_peer_similarity.py neighbors \
  --index .cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite \
  --seed item1 --limit 25
```

The JSON response preserves the original peer score, direct and aggregate
components, direct-artist count, aggregate support counts, sufficiency, and
provenance summary (`source_evidence_ref_count`, `component_kinds`). The index
metadata binds every result to the candidate output hash, gate, and historical
evaluation receipt. A known retained seed with no edge returns `abstained:true`;
an unknown stable seed is an error.

The edge endpoints are already the reconciliation `source_item_id` values.
They are not inferred MusicBrainz identities. Historical H3 data is not read by
the builder and was not used for construction; its receipt is used only to
verify the candidate identity and construction-policy declaration. This index
does not assert artist membership and must not be exposed by serving routes.
