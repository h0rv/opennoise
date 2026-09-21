# Phase 3 combined candidate versus sealed database

This is a read-only checkpoint for the completed local candidate at commit
`46cfc23`; it does not promote, modify, or certify a database.

## Bound evidence

| Artifact | SHA-256 |
| --- | --- |
| release manifest | `795992807586432e2b285e2ddca9a24a00a16e9fc83b6c382a3e914539333232` |
| candidate SQLite | `6dea0c5d81e690b2ee7e9ff989f71d596f218b71dc992e2b86294381122c3972` |
| candidate replay receipt | `e29e9962046c5fc63426b66fde86cb6172bb3f1a8367a4080c94d62193ceecf2` |
| sealed public SQLite | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |

Both databases have schema version 12, 105 non-internal tables, identical
schema SQL, and clean `integrity_check` / foreign-key checks. The candidate
receipt binds the manifest, reports 62 verified objects, 30,904 accepted
records, one quarantine, and exact regenerated/sealed joint-artifact equality.
The manifest's 62 artifact hashes equal the artifact-hash set in both databases.

## Difference is construction scope

The candidate contains no `public_model_runs`, layouts, current selections, or
public graph materializations. The sealed database adds exactly one public model
whose input, settings, and logical-output hashes equal the manifest:
`70c5c40f…ced6e`, `d27fa893…e22b0`, and `e3270450…2108b`.
It also adds four layouts, 2,002 layout points, and public graph rows: 603
names, 3,344 representatives, 26,525 profile memberships, and 34,348
neighbors. Both databases contain the same 37,017 provenance records. The
sealed database adds 37,017 derivation edges (37,024 versus seven), creating
the release-model dependency closure without a mismatch in the 62 source
artifacts.

These expected downstream rows, plus newly generated provenance, timestamps,
adapter build identity, SQLite allocation/FTS pages, explain the distinct file
hashes and the receipt's `certified_database: false` and
`byte_identical_database_replay: false`. This comparison found no evidence of
a candidate-ingestion bug.

## Smallest next gate

Run a fresh, receipt-bound public-model projector from the candidate and require
the manifest logical model hash `e327045074fc6bb4e3b2e1c14410b3f337b6822e048c6038aa18703a11d2108b`, then the four layout/output row counts above. That proves the missing
derived-release stage without claiming SQLite-byte identity; only a separately
specified deterministic provenance/timestamp and SQLite-build contract could
make byte-identical certification meaningful.
