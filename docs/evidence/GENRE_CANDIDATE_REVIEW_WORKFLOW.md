# Genre candidate review workflow

`opennoise.taxonomy.candidates.workflow` is a small, sealed review ledger for
generated genre proposals. It is intentionally outside the catalog, static
site, source adapters, and release path.

A source adapter first supplies immutable `SourceGenreClaim` records. A
candidate has an opaque `candidate:` identifier, a proposed label, the
generator revision, and one or more claim IDs. It is not assigned a genre ID,
does not update a source record, and cannot be served as a map genre.

The batch policy is versioned and bounded: it limits source claims, candidates,
and decisions, and declares the independent approval and rejection thresholds.
Every candidate has a derived state:

| State | Meaning |
| --- | --- |
| `pending_review` | No decision has been recorded. |
| `needs_evidence` | A reviewer requested more source support. |
| `rejected` | The configured rejection threshold was met; rejection wins over approval. |
| `ready_for_separate_publication` | The configured independent approval threshold was met. This is not publication. |

Review events are append-only inputs to a new sealed artifact: each has a
decision ID, reviewer reference, review-guide revision, disposition, and
rationale. One reviewer can record only one decision per candidate batch.
The artifact carries separate canonical hashes for policy, immutable claims,
candidates, and decisions, the sealed upstream candidate-artifact hash, plus a
logical output hash. Verification replays those hashes and bounds.

The artifact has explicit false flags for source-claim mutation, generated
genre publication, and catalog mutation. The verifier returns only a review
gate that says approved candidates require a separate publication workflow.
There is deliberately no function here that writes a catalog row, assigns a
public genre ID, changes a source claim, or exposes a generated genre in the
static UI.

## Open-label-graph queue CLI

The adapter consumes the existing sealed `open-label-graph-model-v1` artifact,
which already contains review-only source-bound label candidates. It does not
read catalog identity edges. In particular, it makes no factual identity claim
from materially different labels and offers no catalog or serving path.

```bash
poe genre-candidate-review queue \
  --source-artifact .cache/musicbrainz-full-seed-targets/pipeline/open-label-graph-model-v1.json \
  --output .cache/genre-candidate-review/queue.json

poe genre-candidate-review apply \
  --source-artifact .cache/musicbrainz-full-seed-targets/pipeline/open-label-graph-model-v1.json \
  --queue .cache/genre-candidate-review/queue.json \
  --decisions review-decisions.json \
  --output .cache/genre-candidate-review/reviewed.json
```

Each queue claim ID is derived from the seed-target artifact file hash and the
retained evidence reference. The queue also stores the exact source candidate
artifact output hash. The decision file is a JSON array, or an object with a
`review_decisions` array. `apply` seals review results only; it never
publishes a genre.

## Candidate-triage audit CLI

The separate triage audit groups review work without making a review or
publication decision:

```bash
poe audit-genre-candidate-triage \
  --source-artifact .cache/musicbrainz-full-seed-targets/pipeline/open-label-graph-model-v1.json \
  --output .cache/genre-candidate-review/triage-audit-v2.json
```

Its JSON output reports `genre-candidate-triage-audit-v2` and its coverage.
`repeated_proposed_label_count` is the number of candidate rows whose proposed
label occurs in more than one candidate. It is not a count of repeated source
claims: distinct immutable claims can produce the same proposed label. The v2
revision deliberately replaces the inaccurate v1 field name, so v1 and v2
audit artifacts are not interchangeable.

Run the focused checks with:

```bash
poe test
poe lint
poe typecheck
```
