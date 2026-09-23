# Unplaced structural relation review

The local review packet combines existing hierarchy review candidates with
co-listen proposals. It is material for a music-domain reviewer. It does not
accept a relation, assign a coordinate, or change the public map.

The packet has 3,213 rows. It contains 3,104 hierarchy review rows for 492
unplaced seeds and 109 co-listen context rows for 43 unplaced seeds. The
co-listen rows remain non-structural context. They are not factual relation or
placement evidence.

The packet verifies these retained inputs before it writes:

| Input | File SHA-256 | Logical SHA-256 |
| --- | --- | --- |
| Hierarchy candidates | `b702d6e78d5f94c04dd4adfef4314ed02538b92a6042140ee8a35768ae712a8a` | `fc224da42842cdd0a4a9b5628d015cf83d60266b609857dcdff96abe01f7f02a` |
| Co-listen report | `7261dbfdcfce25c596eca2af3137e4649318dbe6ee9ca92b99b41345c24d8431` | `284e1e43d224a24934b92ba3a4f44f39d463dc1041a4093e082f4d3ff6f9cc24` |
| Layout | `e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972` | `469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38` |

The co-listen report must also bind the listed layout bytes. The packet reads
only layout seed IDs, names, and placed or unplaced state. It does not read
numeric coordinate values. It reads no historical input.

The packet output is
`.cache/unplaced-structural-relation-review-v1/packet.json`. Its logical
SHA-256 is `502105e02bef743e28b0b3fb5d907d372df420ae52a14873183c6c048b577492`.
The writer creates a new file only below this repository's `.cache` directory,
and it rejects existing targets and paths that resolve through a symlink outside
that directory.

Run the local review packet with:

```sh
./.venv/bin/python scripts/build_unplaced_structural_relation_review.py \
  --hierarchy .cache/musicbrainz-full-seed-targets/pipeline/genre-hierarchy-candidates.json \
  --colisten .cache/musicbrainz-unplaced-colisten-review-edges-v1/report.json \
  --layout .cache/semantic-map-layout-v3/artifact.json \
  --output .cache/unplaced-structural-relation-review-v1/packet.json
```

The packet sets serving, export, model input, and placement assertions to
false. A separate reviewed source-backed relation process is still required
before a seed can receive a structural edge or map position.
