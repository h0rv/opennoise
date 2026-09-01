# Phase 3 qualified release manifest

`config/releases/phase3-public-20260831/release-manifest.json` is the checked-in, cache-first
boundary for the schema-10 qualified public release. It lists all 62 exact source artifacts:
seven ListenBrainz increments and their aggregate, eight artist discoveries, eight release-group
discoveries, eight recording discoveries, eight release-group detail responses, seven recording
detail responses, three hierarchy-discovery responses, four label-closure responses, and eight
music-genre qualification responses. Each entry records its immutable artifact hash, source
manifest hash, byte size, policy key, and, for Wikidata, the exact query hash.

The earlier layout report stated qualification selection hash
`0467cab215b4dcfde5c18b99cdfd086b0f1b21eb3328287ec02b61f6932dc974`. No retained payload hashes
to that value. The two abandoned selection files have different schemas and hashes, so treating the
report-only value as a release input would be false reproducibility.

The canonical replacement is the checked-in v3 selection
`qualification-selection.json`, SHA-256
`3eea58195b8b913a0e1daa19f9521739c693bcc926938e6ea63ced7e78115f3d`. It is regenerated from the
completed database's exact pre-qualification inputs and has 746 exact QIDs. Its eight query shards
hash exactly to the eight v3 qualification source snapshots recorded in the release manifest. The
selection requires an explicit nondeprecated P31 `Q188451` statement and excludes only an explicit
nondeprecated direct P279 `Q25379` parent. It uses no labels to select or classify an entity.

Run offline manifest verification with:

```sh
python scripts/verify_phase3_release_manifest.py
python scripts/verify_phase3_release_manifest.py --database data/phase3-public-qualified.sqlite
```

The second command verifies only a locally retained cache-backed build. It does not call Wikidata,
ListenBrainz, or any media service, so it cannot replace a sealed response with a later one.

`PHASE3_HIERARCHY_COVERAGE_20260831.json` records the corresponding direct qualified hierarchy:
603 QID identities, 712 direct P279 edges, and 107 deterministic navigation-root candidates.
Electronic music (`Q9778`) is one candidate, with a 61-node / 62-edge retained descendant closure.
The report includes all multi-parent observations. A candidate is not a chosen display parent: the
catalog continues to preserve the complete directed acyclic graph.
