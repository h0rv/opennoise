# Track-supplied artist display names

The retained FMA catalog contains 250 native artist IDs without corresponding
artist records, referenced by 974 tracks. Every one has a unanimous nonempty
`artist_name` already retained in the verified track projection. The catalog now
uses those exact strings for display and search, with an explicit track-source
label. This is not artist identity resolution or repair of the source table.

Fallbacks require every track for one positive native artist ID to supply the
same nonempty string. A blank or conflicting value abstains. Null IDs abstain;
existing source artist records remain authoritative. Equal names never merge
IDs. Eighteen fallback IDs have an exact case-sensitive name collision with
another native ID. Search may match additional case-insensitive collisions.

All 250 retain `missing_source_artist_record`. Known-artist support counts,
track identities, model components and exclusions remain unchanged. The optional
index field and profile `name_source` marker identify
`unanimous_track_artist_name`. Artist search, details and track credits disclose
the fallback. No newly inspected raw artist URLs or websites are exported.

## Provenance and validation

Inputs are the same retained 2017 CC BY 4.0 FMA metadata used by the
[co-tag evidence recipe](../fma-cotag-evidence-20261017/README.md). Source receipt:
`cd46d53488e6892eed78b742814ef95e6531b18b6d69c8eb95688da075e6df99`;
projected corpus receipt:
`088588f58ca80662f47e809d054de88eb320b402f110d6637d318f00edbff1ed`.
No new acquisition, audio, model fitting, credentials or public deployment.
Dataset attribution and the derivation notice remain in Sources.

The existing offline static builder reproduces this derivative after full native
source replay. Actual build: 14.67 seconds, 366,841,856 bytes peak RSS under
120-second CPU/wall and 1 GiB address-space limits. The receipt accounts for
35,436,111 bytes and 6,970 manifest files; unchanged shard/export limits apply.

Independent replay confirmed every fallback name and marker, unchanged known
artist profiles, all 109,727 track identities/statuses, 310 track shards,
4,416 co-tag files and `catalog.json`. Browser checks cover name/native-ID/title
search, separate colliding IDs, source labels, missing-record filtering,
history/reload, keyboard and 320/390px layouts. The 250 missing records and
2,609 tracks without genre annotations remain genuine source gaps.
