# Phase 3 historical run2 local projection

## Result

One attested local experimental projection was run on 2026-09-21. It failed
before any output was published because its constructed model input SHA-256 did
not match the sealed manifest boundary. This is not a model-equivalence result,
does not create a gate result, and does not authorize a retry or any policy
change.

The command used only the fresh directory
`/tmp/phase3-historical-projection-cda73d4` and the detached run2 binding. It
returned status 2 after 10.220 seconds of elapsed time (12.106 user seconds,
0.803 system seconds):

```text
candidate public projection failed: candidate model input_sha256 does not match manifest
```

The output directory is empty. Therefore no serving SQLite database, model JSON,
gate report, projection report, layouts, graph counts, or output hashes exist.

## Inputs preserved

Read-only checks after failure preserved the attested values:

| Input | SHA-256 |
| --- | --- |
| manifest | `795992807586432e2b285e2ddca9a24a00a16e9fc83b6c382a3e914539333232` |
| run2 candidate | `327bbf377cb9ad8a1ed48821718979606622175f255ece5958d674146aba6763` |
| run2 receipt | `8d9974e5700c98e9de76385137b65f9d9154df3648a968866d8c1ad9b67ae0d0` |
| detached binding | `ddaf45593ad78a6c6535691bf499c003d86e36227dd1bceb3e97e60dfae9d6a6` |

The source candidate remained schema 12 with `PRAGMA integrity_check: ok` and
zero `foreign_key_check` rows. The detached binding continues to state
`local_experimental: true`, `certified_database: false`,
`byte_identical_database_replay: false`, and `publication_authorized: false`.
No sealed, public, static, or source-vault artifact was changed.

## Model-input differential (read-only)

The run2 candidate's actual canonical `PublicModelInput` SHA-256 is
`80b20e4b54bf120644cf774f53c071744f7f13b08aa1bea282431b6b92a66a14`.
The sealed manifest and `data/public.sqlite` bind
`70c5c40f6206eb3895203e61864b62cf361532d02c1c61535281f22ce5fced6e`.

Five of the six ordered input arrays are byte-for-byte equivalent after
canonical JSON serialization. The only difference is the ListenBrainz
provenance string embedded in every artist-pair row.

| Input array | Candidate count / SHA-256 | Sealed count / SHA-256 | Result |
| --- | --- | --- | --- |
| `artifacts` | 62 / `a09a7976977f05b6a007a0393e7d32383c1ae3ca7dd136c1f51bf8f9bac8d6be` | 62 / same | equal |
| `genres` | 603 / `831c36df55cfd4cccec84ba53d838d5974a15f37275325075140a429adb8a20a` | 603 / same | equal |
| `direct_memberships` | 4,890 / `3b7ea16939fe7b3abec42bceb1d0bd2a9952f4673976933773998ccf50f787bd` | 4,890 / same | equal |
| `artist_pairs` | 13,175 / `76a6d665e8909b43bb704b2ef044de961e0d98be2911b88510ccf1ffea898b3b` | 13,175 / `8f4717022e7a808208b3bfc0825c65c9685c60b837276fff95f818b0cd9bf947` | provenance only |
| `metadata_candidates` | 6,546 / `d6a30226fabad6d5f5002de2bc301aff67859c8453adcf120caf4ad990d4de1b` | 6,546 / same | equal |
| `hierarchy` | 712 / `ed78508bb03c6f67f2545fa0a1fdce453de09dd5284144903c1aec62b40544ec` | 712 / same | equal |

For all 13,175 pair rows, artist IDs, `listener_day_support`, and
`supporting_windows` are identical and retain order. Candidate rows say
`listenbrainz:attempts:62-62`; sealed rows say
`listenbrainz:attempts:8-8`. Both refer to the same single joint source
artifact: source key `listenbrainz_joint_20260824_20260830`, snapshot
`listenbrainz_joint_20260824_20260830:joint:6c30524486b47af9fe0fe554830b50639f716ba39e265c7560d60b84124208b7`,
and SHA-256 `6c30524486b47af9fe0fe554830b50639f716ba39e265c7560d60b84124208b7`.
Both databases have one co-listen run and 30,903 co-listen evidence rows.

This is surrogate-ID replay drift: source content, policy, qualification, and
graph evidence are unchanged. Database timestamps do differ (run2 was created
on 2026-09-21; the sealed database on 2026-08-31), but timestamps are outside
`PublicModelInput`. The canonical 62-row
source/snapshot/artifact/policy-permission mapping has SHA-256
`7edaaae8b811ab02b657177a342a449fecf60f4571faccc8b29584ca9e68b653` in
both databases. The historical candidate inserted Wikidata first, leaving the
ListenBrainz sources and joint run at ID 62. The sealed database inserted
ListenBrainz first, giving the joint run ID 8.

There is also a second, currently masked gate mismatch. Candidate projection
uses default `PublicModelSettings`, SHA-256
`0dc40e7522e85f8c414ab487fb30818bce38fab624fd19bd9b23dca3fd794700`.
The manifest requires `d27fa893459f5480e663253972191b5b90c3ab616cfaad49facc15c645ee22b0`,
whose differing limits are `max_direct_memberships=100000` and
`max_artist_pairs=250000` (with `neighbors_per_genre=25`). Thus an exact
legacy retry also needs those release settings.

## Next decision

For exact comparison to the existing manifest, replay the legacy insertion
order (ListenBrainz first, so the joint attempt is 8) and use the release
settings above. This is a compatibility path only.

For reproducible open reconstruction, prefer source-neutral pair evidence
references derived from the stable joint artifact/source identity rather than
SQLite `ingest_attempt_id`; issue a new model revision and manifest, while
retaining the old-manifest comparison as a diagnostic. The minimal equivalence
test is equality of all six arrays after normalizing only the artist-pair
attempt-ID suffix, plus equality of the stable pair tuple
`(left_artist_id, right_artist_id, listener_day_support, supporting_windows)`.

## Source-artifact v2 projection attempt

One full local v2 projection ran on 2026-09-21. It used the run2 candidate,
receipt, and detached binding above, with `--source-artifacts-v2`, and wrote
only to the fresh `/tmp/phase3-historical-v2-20260921` directory. It failed
after 11.0 seconds before it wrote a model, serving database, receipt, or gate
report. No retry was run.

```text
candidate public projection failed: one-hop graph evidence is outside the release source attestation
```

The candidate stayed unchanged. Read-only checks after the failure found schema
12, `integrity_check: ok`, and zero foreign-key violations. The v2 input had
SHA-256 `a50d3b286ef66632a505a8e36b1d9eb04b8d58646e1056c559792191f401c3cf`
with 62 artifacts, 603 genres, 4,890 direct memberships, 13,175 artist pairs,
6,546 metadata candidates, and 712 hierarchy edges. The loader resolved the
pair evidence to the attested joint ListenBrainz source artifact and its exact
source key, snapshot, and SHA-256. The fixed v2 input-load settings hash was
`f6aa4cbd7b120f1041c6c4a39ad6ce191f29426316d30d8283469026a1bcadfb`.
The fixed model settings hash was
`d27fa893459f5480e663253972191b5b90c3ab616cfaad49facc15c645ee22b0`.

The failure came from the new projector check, not the source artifact lookup.
One-hop propagation keeps both the direct seed reference
`catalog:artist-genre:*` and the source-artifact v2 pair reference. The first
v2 check rejected the direct reference. The check has since been narrowed to
allow only source-backed direct seed references and attested v2 pair references.
It still rejects unknown references. The changed check has focused tests, but
this run remains failed. There are no v2 logical, file, serving, receipt, gate,
layout, or graph-output hashes to report.

## Source-artifact v2 retry

One fresh local retry ran on 2026-09-21 after the mixed-reference check was
fixed and independently reviewed. It used the same attested run2 inputs and
the new `/tmp/phase3-historical-v2-retry-20260921` directory. It failed after
16.2 seconds. No further retry was run.

```text
public model artifact exceeds the 33554432 byte limit
```

The projection passed the 62-source source, snapshot, and artifact attestation.
It built the graph and passed the positive public-model gate before local
publication. The publisher then rejected the staged JSON artifact because it
was larger than its 32 MiB input limit. The staged files were removed by the
projector, and the output directory contains no files. Therefore there is no
saved model input, logical model, model file, serving database, receipt, layout
or graph count, gate report, or output hash from this retry.

The run2 candidate, replay receipt, and detached binding still hash to the
values recorded above. No sealed, public, static, or source-vault file changed.
The artifact-size limit is a separate local publication boundary. It needs a
reviewed design change before another projection may run.
