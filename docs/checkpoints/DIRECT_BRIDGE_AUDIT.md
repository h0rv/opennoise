# Direct catalog bridge audit

`audit_direct_bridges.py` compares the claimed
`canonical_catalog_identity` edges in the verified open-construction graph with
the current exact static discovery bridge. It reads the same public database
and applies the same export/display rights and `direct_source_claim` filter as
the static discovery exporter. It never edits serving assets or promotes an
edge.

```sh
poe audit-direct-bridges \
  --discovery dist/assets/static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json \
  --output .cache/direct-bridge-audit-v1.json
```

The current retained inputs produce 441 claimed identity edges. Of these, 245
are exact casefolded-label matches with one-to-one graph endpoints, 101 are
non-exact review-only mappings, and 95 have conflicting or ambiguous graph or
static-discovery evidence. Every classification, including `safe_exact`, is a
review subject, not an automatic bridge promotion. There are currently 244
edges with an exact static discovery bridge. The not-yet-bridged edges have
1,520 potentially reachable direct P136 observations summed across edges under
the existing display policy. This can count an observation more than once. It
is a review queue estimate, not a publication recommendation: names such as
`dub techno → dubtronica` remain review-only.

The report binds the graph hash, static discovery hash, and public database
hash. It verifies the graph's logical hash and requires each identity edge's
public-catalog hash to equal the database bytes used for the audit.

## Human review packet

Generate a source-bound, ranked packet for manual review with:

```sh
poe direct-bridge-review-packet \
  --discovery dist/assets/static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json \
  --output .cache/direct-bridge-human-review-packet-v1.json
```

The packet is deterministic for its sealed graph, discovery asset, and public
database hashes. It ranks every edge by potential additional direct
observations and retains its exact legacy/catalog IDs and labels, classification
and ambiguity reasons, plus source-authorized artist identifiers and each
candidate observation's evidence and provenance references. Every entry is
`pending_human_review`; the packet is not an approval, bridge edit, catalog
mutation, static-discovery mutation, or publication command.

## Review-only decision ledger

`opennoise.checkpoints.direct_bridge_audit` also provides a typed,
deterministically sealed decision workflow on top of a parsed audit report.
Each `DirectBridgeReviewDecision` names an existing audit edge, reviewer,
review-guide revision, disposition (`approve`, `reject`, or `needs_evidence`),
and rationale. Decisions are retained in sequence. A successor artifact must
preserve every predecessor decision as a prefix and append at least one new
event, so it cannot rewrite a prior review ledger.

The artifact hashes the full audit, its edge set, policy, decisions, and its
own logical contents. It derives each edge as `pending_review`,
`needs_evidence`, `rejected`, or `ready_for_separate_publication`; rejection
wins. An exact one-to-one label match starts `pending_review` just like every
other edge. Even the latter state has no serving effect: the artifact records
false catalog-mutation, static-discovery-mutation, and static-bridge-publication
flags, and verification returns only a gate requiring separate publication.
No function in this workflow writes a catalog row, modifies static discovery,
or publishes a bridge.

Create an empty queue from a previously written audit only after recomputing it
against the supplied graph, discovery asset, and database. This prevents a
stale or edited audit JSON from becoming a review source:

```sh
poe direct-bridge-review queue \
  --audit .cache/direct-bridge-audit-v1.json \
  --discovery dist/assets/static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json \
  --output .cache/direct-bridge-review/queue.json
```

Append one or more new decisions to that predecessor ledger with:

```sh
poe direct-bridge-review apply \
  --audit .cache/direct-bridge-audit-v1.json \
  --discovery dist/assets/static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json \
  --predecessor .cache/direct-bridge-review/queue.json \
  --decisions review-decisions.json \
  --output .cache/direct-bridge-review/reviewed.json
```

The decisions file is a JSON array, or an object with a `review_decisions`
array. `apply` rejects a predecessor tied to another verified audit and rejects
a non-appending decision sequence.
