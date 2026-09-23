# MusicBrainz direct-custody exact-signature ablation

This local, source-only audit derives a separate in-memory shadow graph from
the verified direct-custody peer graph. For each signature-concentration review
pair, it removes only artists whose complete sorted seed-membership signature
is exactly that pair's dominant signature. It then recomputes the existing
IDF-weighted Jaccard metric and top-ten directional neighbors. It does not
remove facts, rewrite the baseline graph, or use H3, historical Every Noise
data, tags, release rows, Last.fm, or display names.

The audit is designed to distinguish overlap that depends entirely on one
exact cohort from overlap that remains after that cohort is absent. A
`cohort_dependent` result means that residual support is below two artists or
the pair drops from both shadow top-ten lists. A `cohort_resilient` result
means it retains two or more artists and at least one shadow top-ten position.
Neither label establishes that any source fact is false; mixed outcomes remain
review material.

Residual support is reported before the graph's two-artist candidate rule, so
a surviving singleton is visible as one rather than collapsed to zero. Each
ablation also includes compact before-and-after top-ten peer-ID lists for all
review-pair endpoints; pair ranks alone are not used as the neighborhood
comparison.

It reads the same receipt-bound local inputs as the concentration audit and
prints JSON to stdout only:

```sh
.venv/bin/python scripts/audit_musicbrainz_direct_custody_exact_signature_ablation.py \
  --database .cache/musicbrainz-direct-custody-peer-graph-v1/peer-graph.sqlite \
  --receipt .cache/musicbrainz-direct-custody-peer-graph-v1/receipt.json
```

The output binds the baseline graph receipt and database hashes, preserves all
policy flags as false, and includes one deterministic output hash. It is local
research only and authorizes no suppression, deletion, serving, export,
promotion, layout, or deployment.

## Observed local result

One read-only run used graph database SHA-256
`1193a4e0f36ef02071fb3af417250d8496328b1e68c803bf1ab099122252ab69` and graph
receipt SHA-256
`a4ae5e59a5d7b3b46976d7379e93cdb21d6e09493e0ae113f4dd8ed13a3a14f0`. Its
output SHA-256 was
`1a2a08f22f217c92a362d62d2bba2cabd8c74b896de0326a4640295143bf97c2`.

All 13 review pairs shared one six-seed exact signature:
`item1000`, `item1044`, `item300`, `item5`, `item546`, and `item667`. Removing
only its 4,103 complete-signature artists (24,618 seed-artist claims) left the
shadow graph with the same 20,178 candidate pairs. Ten review pairs retained a
shadow top-ten position and three dropped from both relevant top tens. Residual
support for the 13 pairs ranged from 70 to 334 artists, so none was represented
as a false zero or singleton. The JSON includes before-and-after top-ten IDs
for all six endpoints; it was emitted only to local stdout and was not retained
as a serving or public artifact.
