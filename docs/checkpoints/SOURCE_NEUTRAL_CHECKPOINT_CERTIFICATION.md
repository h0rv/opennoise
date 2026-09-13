# Source-neutral checkpoint certification

This local-only certificate binds a sealed evidence-graph SQLite database and
receipt, consensus micro-neighborhood artifact, and exact-QID factual taxonomy
artifact. It verifies that the graph receipt matches the database bytes and
schema bindings; that consensus direct/support inputs are the graph's exact
peer inputs; and that the exact-QID taxonomy is the graph's exact factual
hierarchy input.

The construction certificate accepts only the graph, consensus, and taxonomy
paths. It requires the same 6,291 stable IDs in the graph, consensus
eligible-or-abstained partition, and exact-QID taxonomy coverage. Consensus
abstentions are explicit. Missing positive artist memberships and missing
factual hierarchy positives are reported as unknown coverage, never negatives.

Historical Every Noise output is accepted only by the separately invoked blind
evaluator after all construction artifacts are sealed and validated. Its input
binding and output are distinct from the construction certificate. It records
observed membership-seed and peer-pair overlap while making no precision,
recall, parity, or quality claim. Its display hierarchy is not factual taxonomy.

Run with explicit sealed cache paths:

```bash
uv run python scripts/certify_source_neutral_checkpoint.py \
  --graph-database EVIDENCE_GRAPH.sqlite \
  --graph-receipt EVIDENCE_GRAPH.receipt.json \
  --consensus CONSENSUS.json \
  --taxonomy EXACT_QID_TAXONOMY.json \
  --output CERTIFICATION.json
```

To invoke the blind evaluator in a later explicit step, additionally pass
`--historical-evaluation HELD_OUT_HISTORICAL.json --historical-output EVALUATION.json`.
