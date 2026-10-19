# Complete retained CC0 cultural catalog

This builds the ordinary source/projector/catalog/navigation/export path for both
retained Wikidata cohorts and the native MusicBrainz core. It replaces the previous
seven-overlap demonstration with all 150 requested cultural identities. No source
acquisition, model fit, research-license promotion, public default or UI changes
participate. Attribution: MusicBrainz and Wikidata contributors; structured inputs
are [MusicBrainz core CC0](https://musicbrainz.org/doc/About/Data_License) and
[Wikidata CC0](https://www.wikidata.org/wiki/Wikidata:Licensing).

The source census has 152 per-capture nominations, 150 unique MBIDs, 88 exact
matches, 62 unmatched, and 10 matched artists without observed P136. All missing
identities remain in `missingness.json`; absence is not a negative genre label.
The two raw SPARQL packs retain 287 P136 observations over 278 distinct artist/genre
facts and 151 genre QIDs. Each capture gets its own source, sealed CC0 policy,
snapshot, raw-body artifacts and projection provenance. Derived catalog projections
are not described as upstream response bytes. MusicBrainz custody is weaker:
verified retained portable core projections and exact credits, not original HTTP
response bodies.

The build preserves all 352 core artists, 87 release groups, 1,031 recordings and
1,344 ordered credited-member tuples. Seven cultural identities join existing
artists; the complete catalog contains 433 artists. Both ingestion orders produce
the same normalized identities, credits, claims and neighborhoods. Reprojection
is idempotent; conflicting registered source custody, rights or normalization
suppressions abort rather than rewriting policy. Subject and P136 target entity
suppression is checked before any pack projection writes.

All 433 artists have explicit neighborhood outcomes: 78 have observed P136, 72
have any co-genre neighbor, and 361 have none. There are 290 unordered co-genre
pairs; only six of the 352 native core artists acquire neighbors. These are
source-supported metadata relationships, not recommendations, similarity judgments
or inferred genre membership. No taxonomy expansion is included.

Three source artists lack English names. Their entity projections retain exact
identities without fabricated NameClaims or search rows. Backend responses keep
`name` and add `name_status`: `source_name` for existing sourced names and
`source_identifier` for an independently display-authorized, unambiguous typed
QID/MBID label. Entity/source/provenance/snapshot/artifact display suppression
prevents that fallback. One genre, Q3071, has no observed English label and retains
its existing identifier placeholder.

Capture order is fixed: cultural-context before independent-cultural-context.
Ordinary direct-evidence fingerprints retain 278 canonical facts, while generic
entity claims retain all 287 observations. The nine repeat observations are not
extra votes. Suppressing a canonical source does **not** select a later capture as
replacement direct evidence. Repeated name/identifier observations also need not
retain every capture's provenance. This conservative limitation is explicit.

From the repository root, after `poe sync`:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/replay_cc0_cultural_catalog.py \
  --core-source data/release/musicbrainz-credit-catalog-v1/objects/musicbrainz-credit-catalog/sha256/13921b94a5a0c77c625713b5e272d40d081c67de3eb5b1299c8c1c48baf6d6ba.json \
  --core-source-sha256 13921b94a5a0c77c625713b5e272d40d081c67de3eb5b1299c8c1c48baf6d6ba \
  --cultural-pack data/examples/cultural-context \
  --cultural-receipt-sha256 3c931909700e2840dff10e2afd2463e9123faa2a7b36e5fc1b90c472677453a7 \
  --independent-pack data/examples/independent-cultural-context \
  --independent-receipt-sha256 df9763aef5b3f5801cc9ef999ecd34b24b97c588dc25679a2adaf8432461cfa5 \
  --output .cache/cc0-cultural-catalog-replay
```

The output must be fresh. The CLI bounds one process to 120 seconds CPU/wall,
1 GB address space, one numerical thread and 32 MB combined output. Pack inventory,
physical hashes, bounded inputs and path symlinks are checked before use. The nine
outputs are two SQLite catalogs, two v2 approved inputs, two v2 receipts, adapter
policy, complete source missingness and the hash-inventory report. The report binds
implementation files, including the reused identity replay normalization helper.
SQLite file hashes vary with truthful ingestion timestamps; normalized graph
comparison is the two-order equivalence test. Each v2 adapter emits 278 facts,
151 genres, 574 eligible metadata bindings and four raw source artifacts. Repeated
Wiki selectors produce a deduplicated compatible consumer source policy.

`results.json` pins the actual local final build and aggregate results. Its local
`.cache` path is a current executor example, not a promise of future artifact
availability. Rebuild from the exact retained approved sources above if absent;
otherwise report missing custody. No NC/research models or human votes are inputs.
The initial attempted build failed atomically on a repeated-label provenance
collision; fingerprints now bind the raw artifact as well as derived projection.
No source facts or rights were changed to address that collision.

Validation: 40 focused tests passed (one historical skip), covering real two-order
replay, empty artist names, display vetoes, canonical suppression, registered-source
and provenance conflicts, whole-pack subject/target suppression, closed inventory,
atomic failure and consumer policy compatibility. A late provenance veto rolls
back the entire pack with a savepoint while preserving the caller's transaction.
Full checks are pending.

An independently implemented raw/core SQL oracle checks all source identities,
credits, observations, canonical facts, all 574 metadata bindings and neighbor lists
in both final databases (oracle SHA256
`92c53e0f045387e6aa551bf1c66e2b93b4a5307ffe455c9226d1fcc3e31371f4`). The final guarded
relocated CLI used copied source inputs, actively denied original data/cache/oracle
reads, network, research-model imports and supervised fitting, and passed five
guard probes with zero forbidden production operations (10.53 seconds). Its proof
SHA256 is `2568c3fd5c1e764c219371c7552c4ec8e9cefc0aa682d3c233577d938ec2c9dc`;
local evidence and actual producer pins are in `results.json`. SQLite bytes vary
with new truthful timestamps; the raw/core oracle compares normalized facts.
