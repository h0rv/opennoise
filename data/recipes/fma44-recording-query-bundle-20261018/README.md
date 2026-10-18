# Portable historical FMA saved-rank lookup

The existing replay CLI can now export a small pinned lookup bundle once, then
answer explicit track-ID queries without original source packs, membership
packs, target metadata, feature arrays, model weights or complete artist exports.
This is the same historical rank-profile retrieval as the
[recording query recipe](../fma44-recording-artists-20261018/README.md).
The existing query policy, query rows and selection kernel are unchanged.

## Export once from verified retained inputs

Materialize the existing membership recipe into a fresh directory, then request
the optional bundle during the normal externally pinned ranked-artist export:

```sh
.venv/bin/python scripts/materialize_fma_membership_example.py \
  --output /tmp/fma-bundle-memberships
.venv/bin/python scripts/replay_fma_memberships.py \
  --saved-pack data/examples/fma-acoustic-baseline \
  --memberships /tmp/fma-bundle-memberships \
  --saved-pack-receipt-sha256 3e1651c136f5ae0c588e6dd6930a7a8f68fc7b332d1e423d29d1657e20cd0106 \
  --membership-receipt-sha256 ad54dc99a09e0c0f492dd97ac21e216a4a70bfd39a7749932a6f1a1a45646c1d \
  --export-artists /tmp/fma-bundle-artists.json --rank-artists \
  --export-query-bundle /tmp/fma-recording-bundle
```

The bundle option requires ranked artist export; ordinary flags and output
semantics remain available. All output paths must be fresh and outside every
input and each other. Output overlap is rejected before any export is written.
The final manifest is published only after the complete bounded lookup data.
Record the returned `query_bundle_manifest_sha256` externally.

The closed bundle has exactly `lookup.json` and `manifest.json`. Its allowlisted
payload contains all 109,727 native identity rows (track/artist/known/component/
fold), all 13,800 saved top-ten recording ranks and original abstentions, and
minimal artist profiles with track IDs and support counts in each historical
partition. It retains the 974 unknown-source-artist ledger rows, preserving the
distinction between unknown track IDs and native tracks without predictions.
Artist profiles are copied after their original aggregation over **all 158 saved
ranks**; they are never recomputed from truncated recording rows. No source
targets, calibrated memberships, artist-neighbor graph, features or model weights
are included. Source receipt/file hashes and original licensing survive in the
manifest without storing source filesystem paths.

## Query or relocate the bundle

The checked bundle manifest SHA256 is
`8204d73e445bc370f2a896a1a36307a911e012d69c5e640c3759a8d43daced37`.
With that bundle, query one recording using only its native ID and external pin:

```sh
.venv/bin/python scripts/replay_fma_memberships.py \
  --query-bundle /tmp/fma-recording-bundle \
  --query-bundle-sha256 8204d73e445bc370f2a896a1a36307a911e012d69c5e640c3759a8d43daced37 \
  --query-track-id 213 --output /tmp/fma-recording-result.json
```

Repeat `--query-track-id` for up to 100 positive uint32 IDs; order and duplicates
are preserved. To reproduce the frozen hundred-request batch, use its unchanged
`requests` list from `../fma44-recording-artists-20261018/protocol.json` (SHA256
`7ee032991f48dd8f3fb219fcb00eb734a0e72e47838c26bfc818b38b4d0f6e20`) as
repeated ID flags. Use the pin returned by your own export if implementation or
numerical runtime differs from this checked run.

Bundle mode rejects all source/export flags, and source mode rejects bundle-only
output/pin flags. It returns only the requested query rows, policy, native
namespaces, bundle reference, source receipt/file pins and original CC BY license/
attribution. Candidate artist IDs resolve to exact profile evidence in the pinned
bundle partition. Copy just the two bundle files to relocate it; original data
paths are not execution dependencies. Matching targeted implementation hashes and
Python/NumPy/SciPy versions are required rather than silently accepting runtime
drift.

Before query execution, existing artifact helpers verify the external manifest
pin, closed regular-file inventory, file sizes and hashes. The lookup validator
checks exact schemas/types, native ID uniqueness and artist/component/fold joins,
complete heldout saved-query coverage, original abstention/rank consistency,
partition isolation, complete profile track coverage, track-support counts and
finite bounded rank weights. It rejects inconsistent data even if its file hashes
were resealed. The external pin authenticates the approved profile values;
truncated recording ranks cannot independently reconstruct the full-rank artist
scores. This is a verified export, not a runtime replay of native source files.

The complete bundle is capped at 10 MB, results at 2 MB, the native ledger at
110,000 rows and each artist pool at 2,000. The CLI retains 120-second CPU/wall
and 1 GB address-space limits. Each call reads and validates the complete bundle;
there is no persistent service or implied constant-time lookup.

## Fixed engineering measurement

`protocol.json` (SHA256
`3f27d8ec5a6f8e94877c9001008e920bbf39902d915093136e6a09bd9979a088`)
freezes the one-ID request (213), unchanged hundred requests, parity checks and
measurement method. There was one fresh child process for each mode/batch and
one bundle build. Monotonic wall time surrounds child execution; per-child Linux
`wait4` peak RSS is converted from KiB to bytes. Source mode emits full ranked
artist profiles without the optional artist graph, making the comparison against
the existing smaller source output. These are single local observations with no
universal latency or memory guarantee.

| Operation | Output bytes | Wall seconds | Peak RSS MiB |
| --- | ---: | ---: | ---: |
| Source mode, one ID | 4,839,242 | 4.137 | 219.2 |
| Portable mode, one ID | 3,770 | 0.750 | 125.6 |
| Source mode, hundred IDs | 4,980,452 | 3.937 | 219.8 |
| Portable mode, hundred IDs | 144,980 | 0.855 | 127.1 |

The one-time bundle export took 5.699 seconds and 262.3 MiB peak RSS, including
ordinary verified source replay and ranked-artist export. The bundle totals
5,209,932 bytes: 5,207,687 lookup bytes and 2,245 manifest bytes. All requested
query rows match source mode exactly. The hundred includes 75 emitted queries /
450 edges, ten original `missing_feature_row` abstentions, ten
`no_saved_prediction` and five `unknown_native_track_id` results.

A relocated copy produced byte-identical hundred-request results while a Python
audit hook denied opens/listings under original pack, membership, full-export and
original bundle paths. The hook was active in the actual query child. Focused
tests cover parity, duplicates, original-source denial, bad pins, changed/extra/
symlinked files, resealed runtime/schema/identity/rank/support/partition/attribution
corruption, ambiguous CLI modes and output overlap. `results.json` retains exact
artifact hashes and measurements; the temporary run retained logs and the copied
bundle under `.cache/fma44-recording-bundle-run-20261018/`.

A separate audit compared all 109,727 native projections, all 13,800 saved
recording rows and all 1,714 original full-rank artist profiles against the
pinned originals, then matched all hundred query rows to the independently
verified prior recording export. Its separately relocated CLI run denied seven
original data/export/bundle roots, with zero forbidden-open attempts and the
same result bytes. The denial guard was first tested against an existing target
file. Original license, attribution, namespaces and source pins all survived.
The independent audit is included in `results.json`.

No new features, source acquisition, model fit, calibration, model inference,
listener judgment, music-quality evaluation or public promotion occurred. The
results remain historical FMA44 model-rank-profile similarities, with all existing
abstentions and incomplete-source-evidence limitations.
