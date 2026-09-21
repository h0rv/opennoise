# Phase 3 historical replay bounded comparison (2026-09-21)

This is a read-only comparison of the retained historical-declaration replay
candidate and sealed public SQLite file. It does not attach, copy, modify,
normalize, construct from, promote, or certify either database.

## Bound inputs and method

| Input | SHA-256 |
| --- | --- |
| retained historical candidate | `327bbf377cb9ad8a1ed48821718979606622175f255ece5958d674146aba6763` |
| sealed public SQLite | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |

The comparator first verifies those exact hashes, opens both inputs with SQLite
`mode=ro&immutable=1`, enables `query_only`, and streams sorted typed,
length-prefixed SHA-256 projections. It does not materialize tables in memory.
Each table is capped at 50,000 rows; the largest is `entity_names` at 40,399,
so the pinned run has no abstention. The cap limits rows returned to Python;
it does not claim to bound SQLite's internal work for the required `ORDER BY`.

Both inputs have `PRAGMA user_version = 12`, `integrity_check = ok`, zero
foreign-key violations, the same 105 non-internal tables, and the same full
SQLite schema-object SHA-256:
`c277ac01091acac698fabae19cd404c613d36a2758f9c7c8b03ef615e1e50b42`.
Their file bytes are not identical.

## Table result

Of 105 tables, 54 are exact row-and-cell matches. The remaining 51 differ even
after removal of a column named `acquired_at`, due to historical declarations,
run/provenance identity and timestamp allocation, plus the sealed database's
derived public-model materialization. Dropping `acquired_at` alone is therefore
not a logical-equivalence test.

All 12 core ingest/evidence tables have equal row counts but no exact
row-and-cell hash match. Database primary IDs, provenance and execution state
are construction details, so this is not by itself a failed raw replay.

## Logical source and evidence projections

| Projection | Rows each | Result | SHA-256 when equal |
| --- | ---: | --- | --- |
| Source-key/artifact-SHA pairs | 62 | equal | `a2a06e7e1aa711b7d620efe03e532f9fbbe9e14b9bf9b592e52031bf1236cf55` |
| Direct artist/genre evidence fingerprints | 4,948 | equal | `1547d4e564aa9f2c0c535561763b714b29a9688d9d6bcd6ebf9840948ec420c3` |
| Co-listen observed windows | 30,903 | equal | `39e89d179ee352dbeafe35cb7c79e00e9647411ef53178ba4fea8c132035a254` |
| Album/genre observed values | 1,550 | equal | `22f8374fbe3c065da4e8a6e20cddaaa85da840110a91b89cd2635396ba85ae49` |
| Recording/genre observed values | 833 | equal | `9ce902942932e8a4bfa5707d3b7523d2351f1c57a6f4a2a2172a7c2b9c7e71de` |
| Music-genre qualification observed values | 603 | equal | `39584fae03cf2fce26a23d65bde3f1f08d940974801a5f012bcc0e18c8769d4f` |

The following equal-count source projections are deliberately not equal and
remain declaration or construction drift, not fields to normalize away:

| Projection | Rows each | candidate SHA-256 | sealed SHA-256 |
| --- | ---: | --- | --- |
| Source snapshot declarations | 62 | `f9ebe145bdbd3101297880c5c0f43a872fcc9495efdea4fbf80038e45625ee3e` | `53c7812cd8173db1935debd5107ac705fe0a52cb953a7cdb3bae2fbd4f7edb3c` |
| Staged raw-record metadata | 37,011 | `f5279ebcbf6f0613a9e7fda1c5c9ad2c3550d20fca4219f871cb498f41914dda` | `ccdb0509141d666d8130247cd318b0e6eac92b76cb668450f5d41736ffc0322a` |
| Source-object identities | 37,010 | `7e5d9e70634a1e4f9983c1ac6b6c2d7cd7870afb0bd3f807e335475b1fb1cec5` | `42e05a0bf4c1b6c712826685f285147bb6630dd0f9081d46e1a94bef9bf54003` |
| Source-object observation fingerprints | 37,010 | `3c1ba26356d8091ddfc1fee72953d4b92eed7a23a81385220351112d8a4016ab` | `2382d60a6432a85253c31966ed2854acdf1a2e2ccfd3f199e5aa73c35eff47d1` |

The earlier timestamp result remains: all 62 shared `source_snapshots` have
different `acquired_at` values. It is one byte-difference cause, but not the
only persisted difference and not permission to rewrite either input.

## Absent derived stage

The candidate has zero rows where the sealed database has one public model,
four layouts, 2,002 layout points, 603 public genre names, 26,525 profile
memberships, 34,348 neighbors, 3,344 representatives, and 37,017 public-model
input-provenance rows. It has seven derivation edges versus the sealed 37,024.

Those are downstream model/layout outputs. Their absence is a missing pipeline
stage, not a failed source replay. This evidence does not authorize that stage,
policy changes, or candidate certification.

## Reproduction

```bash
.venv/bin/python scripts/compare_phase3_replay_databases.py \
  --candidate /tmp/phase3-historical-combined-4a76c76-run2.sqlite \
  --candidate-sha256 327bbf377cb9ad8a1ed48821718979606622175f255ece5958d674146aba6763 \
  --sealed data/public.sqlite \
  --sealed-sha256 240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc \
  --report /tmp/phase3-replay-comparison-20260921.json
```

The generated local report contains every table hash, classification, row
count, and logical-projection result.
