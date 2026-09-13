# Wikidata enrichment reuse audit, 2026-09-13

## Decision

Do not reuse the preserved `data/wikidata-genre-enrichment` worktree to
construct new taxonomy facts. It is currently fast-forwarded to `main` at
`74287d7`, has no worktree diff, and its checked-in query is byte-identical to
`config/wikidata_public_genres_20260831.rq`.

The source-neutral relation adapter already has a receipt-rooted cached
baseline. Its full verification succeeds for logical artifact
`21126aae5cf8b849edd132e9125ad12f1037474fecc1f89f6b8c1f8254efbd15`:

| Measure | Count |
| --- | ---: |
| Immutable legacy labels | 6,291 |
| Unambiguous canonical/alias exact-QID seed bindings | 346 |
| Export-permitted CC0 P279 rows in the snapshot | 853 |
| Accepted factual seed edges | 216 |
| Review edges / cycle abstentions | 0 / 0 |
| Factual-isolated seeds | 6,057 |

The accepted graph is acyclic and explicitly reports no normalized-name joins
and no historical construction input. It does not create a membership.

## Archived-query proof

The retained 2026-08-31 response is present at
`.worktrees/phase3-public-evidence/data/phase3-final-vault/raw/sha256/6e25bf1c044594aecfb9a7ed15838ef6bb62c8d7cbe2d3daf68ec920c6c8397f`.
Its bytes hash to `6e25bf…c8397f` and it contains 174 unique direct P279
pairs. The historical report binds that response to query hash `476fe2…ad0fc`,
but the now-preserved checked-in query hashes to
`4564bdc178e49efee7eacf0fd936da604ace356c8e541c58fac35eb1fb2c0379`.
The original request bytes are not retained, so the response cannot be bound
to the present query.

The row-level comparison against the current receipt-rooted CC0 SQLite
snapshot (`240047…3e8fc`, 182,419,456 bytes) is also non-promoting:

| Archived direct P279 result | Count |
| --- | ---: |
| Pairs replayed by the snapshot | 170 |
| Pairs absent from the snapshot | 4 |
| Pairs already represented among the 216 accepted seed edges | 63 |

The preserved query's `VALUES ?entity` block has 140 QIDs. The retained Phase
3 shards have 747 distinct QIDs; 136 overlap and four preserved-query QIDs do
not occur in those shards. This is availability information only, not a
name-based identity bridge.

## Why zero new facts are safe

`taxonomy_relation_expansion` accepts a factual Wikidata edge only when it
replays as `catalog_wikidata_p279_sqlite_v1`: its row ID, child QID, parent
QID, row hash, source object hash, object-store custody receipt, and
export-permitted CC0 catalog provenance must all agree. A generic SPARQL JSON
response, including the archived one, has no such current row binding. It
therefore cannot increase either the 346 exact-QID mappings or the 216 factual
edges under the existing contract. The four non-replayed pairs fail closed;
the 63 overlapping pairs are already covered.

No Every Noise artifact, historical coordinate, membership, neighbor, or
normalized label was read for this audit or used for construction.

## Reproduction checks

```sh
git -C .worktrees/wikidata-genre-enrichment diff --quiet
cmp -s config/wikidata_public_genres_20260831.rq \
  .worktrees/wikidata-genre-enrichment/config/wikidata_public_genres_20260831.rq
sha256sum config/wikidata_public_genres_20260831.rq \
  .worktrees/phase3-public-evidence/data/phase3-final-vault/raw/sha256/6e25bf1c044594aecfb9a7ed15838ef6bb62c8d7cbe2d3daf68ec920c6c8397f \
  .cache/catalog-snapshots/sha256/240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc.sqlite
UV_CACHE_DIR=/tmp/musix-wikidata-uv UV_OFFLINE=1 uv run --no-sync python -c '
from pathlib import Path
from musix.storage import LocalObjectStore
from musix.taxonomy.relations.expansion import TaxonomyRelationExpansionArtifact, verify_taxonomy_relation_expansion
artifact = TaxonomyRelationExpansionArtifact.model_validate_json(Path(".cache/taxonomy-relation-expansion-v3-replay-candidate/artifact.json").read_bytes())
print(verify_taxonomy_relation_expansion(artifact, source_store=LocalObjectStore(Path(".cache/taxonomy-relation-expansion-v3-replay-candidate/objects"))).model_dump_json(indent=2))
'
```

The final command verifies every accepted factual edge against the cached
source rows and custody object, without network access.

## Remaining gap

There are 5,945 labels without an unambiguous exact-QID binding and 6,057
factual-isolated seeds. Any future uplift needs a newly retained
request-and-response pair selected from the sealed taxonomy's exact QIDs, then
an import into a fresh export-permitted CC0 catalog snapshot so each P279 row
can receive the required replay binding and custody receipt. Until then, keep
new raw SPARQL observations as abstentions or separately labelled review data;
do not promote them to factual edges.
