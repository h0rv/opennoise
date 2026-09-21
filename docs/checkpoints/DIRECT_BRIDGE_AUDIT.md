# Direct catalog bridge audit

`audit_direct_bridges.py` compares the claimed
`canonical_catalog_identity` edges in the verified open-construction graph with
the current exact static discovery bridge. It reads the same public database
and applies the same export/display rights and `direct_source_claim` filter as
the static discovery exporter. It never edits serving assets or promotes an
edge.

```sh
poe audit-direct-bridges \
  --discovery dist/assets/static-discovery.8310a95109d9f33d08c0f2b6bc934c8e84246d1bf911d986395f84a2ed49c0fc.json \
  --output .cache/direct-bridge-audit-v1.json
```

The current retained inputs produce 441 claimed identity edges. Of these, 277
are exact casefolded-label matches, 164 are non-exact review-only mappings,
and 244 edges currently have an exact static discovery bridge. The not-yet-bridged
edges have 1,520 potentially reachable direct P136 observations summed across
edges under the existing display policy. This can count an observation more
than once. It is a review queue estimate, not a
publication recommendation: names such as `dub techno → dubtronica` remain
review-only.

The report binds the graph hash, static discovery hash, and public database
hash. It verifies the graph's logical hash and requires each identity edge's
public-catalog hash to equal the database bytes used for the audit.
