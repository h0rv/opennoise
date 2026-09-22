# Phase 3 v3 ListenBrainz provenance replay diagnosis (2026-09-21)

## Result

The retained inputs do not support a genuine deterministic reproduction of the
sealed ListenBrainz `artist_co_listen_run` provenance record. The semantic
comparator must continue to treat the records as different. No public or
sealed artifact was changed.

## Pinned rerun

The read-only comparator was rerun against the pinned historical v3 files and
the sealed public files:

| Input | SHA-256 |
| --- | --- |
| v3 model | `c430b9948b863404827dd346fed6324a38b650ab2a827608078fc145b79fd1ba` |
| v3 database | `1fca548fa214aae999f7b2462fd2ebf3e265a7f5195a3d6d76b5393f06bd8df9` |
| sealed model | `c9964b7a1a76ddd65b2a79eb73998168e6e4328a4f81b35f2e64c6ddd70a2d1e` |
| sealed database | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |

It returned status 1, with only this unequal projection:

| Projection | v3 rows | sealed rows | v3-only | sealed-only | v3 rows SHA-256 | sealed rows SHA-256 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Normalized provenance bindings | 37,017 | 37,017 | 1 | 1 | `2ee7f88612d47d6fb68567d63a8de73b80639c22722512d8e63796b506c31607` | `8bf5e655a5aa056c3aa9933d8d20ea7a4e2612659985f2774203de06c1ef9e27` |

The different rows share the same source key, snapshot reference, source
artifact SHA-256, parser release, and bound artifact SHA-256. Their only
different tuple field is the record fingerprint:

| Side | Record fingerprint |
| --- | --- |
| v3 | `b759b28149d3a9576c09aa456c0f4a6b2f8fca3fb423bd8cb080075872727920` |
| sealed | `3d3ddb75e9f8d31097eb6d33b0c6bb047087164089087df53a2e544ded84601e` |

## Root cause

`persist_pipeline_record` computes a parsed-record fingerprint from source
identity, snapshot, projection external ID, and exact-record SHA-256. For the
completion record, the exact-record SHA-256 is SHA-256 of the complete
`ArtistCoListenRunProjection` JSON. That JSON includes adapter build SHA-256,
elapsed milliseconds, and peak RSS bytes.

The retained staged records at ordinal 30,904 establish the following
differences:

| Field | v3 | sealed |
| --- | --- | --- |
| External ID | `14ce6faefecf9e4aea9eb7937af0fd46f8926a786000bb8f4d6b95da06a0473c` | `fe60fa037aded21aaa79b66b7f93a0342ef434372f30177ed7d6ff773e1d7f73` |
| Adapter build SHA-256 | `d99136efcf624e113aa6f30ebca5d2d1bedfcb632e4bc7296ed899c93607ce18` | `72efb5a2a33cbfef3ddf1c5f24b6ac8c3d3ef3080727418f6ed639dea9f4f9bb` |
| Elapsed ms | 324,102 | 252,901 |
| Peak RSS bytes | 396,734,464 | 368,578,560 |
| Completion time | `2026-09-21T19:00:53.397Z` | `2026-08-31T23:52:18.059Z` |

All fixed-window configuration and result counters are identical: 30,469,708
listens seen, 993,589 with artist MBIDs, 79,673 artists, 40,782 user windows,
8,420,452 candidate pairs, 30,903 emitted pairs, and one quarantined record.

The sealed adapter source is recoverable as the parent of commit
`d889e85017a7264d0d6dfeef9f4aa0d17d0f8fb9`. Its file digest is exactly the
sealed adapter-build value. Its only content changes relative to the current
adapter are six internal package-import renames. Since the adapter
intentionally hashes its own full module bytes, those renames change its
adapter-build value and consequently the completion external ID. Separately,
the projection intentionally samples wall-clock
elapsed time and process peak RSS, neither of which can be recovered from the
source vault or replayed deterministically.

## Safe next step

Keep the strict normalized-provenance comparison unchanged and leave v3
uncertified. A candidate may replay the seven raw ListenBrainz objects and
match the sealed joint artifact and all semantic evidence, but it cannot claim
the sealed run provenance without substituting historical adapter bytes and
recorded runtime measurements. Such substitution would manufacture a sealed
provenance record rather than reproduce it. If exact replay is required in the
future, preserve an executable, content-addressed adapter artifact together
with an explicitly specified deterministic runtime-metadata policy before
sealing a new release.
