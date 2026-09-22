# Direct custody artist signature concentration audit

This local, source-only audit checks whether a candidate peer pair's shared
artists are dominated by one exact sorted artist seed-membership signature. An
artist's signature is the sorted set of seed IDs whose verified custody rows
contain that artist. It does not use genre IDs or names, H3, Last.fm, labels,
or tuning data. The peer graph and its public assets were not changed.

The audit verifies the existing peer graph receipt and database hash before
reading the graph in read-only mode. For every candidate pair it recomputes
shared artist support from `seed_artist`, checks that support against the
stored edge count, and confirms the candidate total against the receipt. The
report shows at most 50 suspects and includes deterministic source hashes and
a typed output hash. A suspect has at least 1,000 shared artists with at least
90% in one exact signature class. This is a review threshold, not a finding of
false data: the report sets `review_needed` and authorizes neither fact
deletion nor candidate suppression or public export.

On the current graph (database SHA-256
`1193a4e0f36ef02071fb3af417250d8496328b1e68c803bf1ab099122252ab69`, graph
receipt SHA-256
`a4ae5e59a5d7b3b46976d7379e93cdb21d6e09493e0ae113f4dd8ed13a3a14f0`), the
audit scanned all 20,178 candidate pairs and marked 13 for review. The top
pair, `item1044`–`item667`, has 4,173 shared artists, of which 4,103 (98.32%)
have the same exact six-seed signature. The report output SHA-256 is
`31253430e22b2a07ab3dca434f54d07775e4c5a0e41732908eedba4aa31f65a0`. The JSON
is emitted to stdout and is not stored as a public asset.

Run the audit against the verified local inputs with:

```sh
.venv/bin/python scripts/audit_musicbrainz_direct_custody_signature_concentration.py \
  --database .cache/musicbrainz-direct-custody-peer-graph-v1/peer-graph.sqlite \
  --receipt .cache/musicbrainz-direct-custody-peer-graph-v1/receipt.json
```

Fixture tests cover repeated exact cohorts, ordinary overlap, corrupted
receipt rejection, stored-support mismatches, and stable ordering. This
checkpoint remains local research and does not authorize serving, publication,
or any change to graph candidates.
