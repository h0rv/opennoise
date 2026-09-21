# Layout navigation separation sweep

This offline sweep tests only the deterministic display-coordinate separation
after the sealed open-graph layout has been built. It does not read historical
coordinates, alter the published atlas or `dist`, or select a deployment.
Every run is isolated below `.cache/layout-navigation-separation-sweep-v1/`.

| separation / iterations | labels above `1e6` | maximum reveal scale | peer KNN preservation | logical artifact SHA-256 | logical report SHA-256 |
| --- | ---: | ---: | ---: | --- | --- |
| `0.00030` / 128 | 1 | `1.044e6` | `0.1823307213` | `07c08d0d74177f5abe788f9fa4f66eaa3112b11a0cc4da40406a65663d167aaa` | `bb0a433db074145afdd0e2328fb45464477d4d2b4b65b3900e6c05568d5970f0` |
| `0.00032` / 128 | 0 | `835120.0274` | `0.1818243922` | `469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38` | `fb347299a3658c0ecdf07ca10dc7703875402bacb7fe9e68ca1dd5bc49b2f725` |
| `0.00035` / 128 | 0 | `835120.0274` | `0.1817048423` | `004895fbec3738140a20905d79b4c57ca3492ed5bca2bca66566f9aa6273caf8` | `e19e552067914cf0e44178b9d7730ae378a133471d7e07adfa43226d8179b7eb` |

The smallest successful setting is `0.00032` / 128. Its peer KNN change from
the v2 baseline (`0.1824583082`) is `-0.0006339160`, inside the `0.001`
budget; it has no exact coordinate collisions, zero near groups at `1e-4`, 24
overview-visible communities, and full overview-root coverage.

The winning artifact was statically exported and browser-certified only at
`.cache/layout-navigation-separation-sweep-v1/d0320-i128/`. The export logical
layout hash is `469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38`,
the static-export output hash is
`c339321b4853ddb5f5a1c8941a9b796d05a34274ad6f2f115d4356c222d3ccd0`, and
the browser report hash is
`b31690c1e6921ff704203a2486af881240c377c3b4bd7a0f9e87b3e8ce4ceb4d`.
The winning artifact and report byte hashes are respectively
`e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972` and
`55b7d4f88d2893f3686914bc0582e22f9dc45349623c5eff12c9be12cd17c066`.
Its browser QA retained the 23-point/23-label/no-edge overview, readable
deepest label at `835120.0274`, equivalent zoom paths, focus and artist
routes, dark mode, mobile pinch behavior, and a `3.3 ms` renderer p95.

This establishes reachability of zero labels above `1e6` under the stated
geometry and neighborhood constraints. It is not publication approval; any
selection still requires the existing provenance and promotion gates.

## Strict label-point exit QA

The corrected `--require-label-point-exit` browser gate also passed against the
same isolated export. Its report is
`.cache/layout-navigation-separation-sweep-v1/d0320-i128/browser-strict.json`
with byte SHA-256
`af488aab732ad67ee87eaf9176a4eedee678356fd012d7f2ed76d9b5996d1135`.
All boolean acceptance gates are true: deep-label readability; artist
discovery/search/deep-link/back; modern-rock connection; rock landmark and
camera; pan/back; dark mode; mobile readiness and pinch zoom. The geometry
checks also retain a 23-point/23-label/no-edge overview, monotonic fixed-center
trajectory with visible points, equivalent zoom path, and zero browser errors.

There are no unclassified interior label exits. The nine exited labels with a
still-visible point are all permitted: six `label_box_viewport_clipping`, two
`point_edge_tolerance_visible`, and one `overlay_occlusion`. The strict run
wrote 17 screenshots to `captures-strict`; their names and SHA-256 receipts are
embedded in the strict browser report. The static manifest remains byte hash
`e9b42547987d8a598bcf1a8a4d6d610930897a0345aeabe85b132f5e198c213c`.

## Selected v3 build

`scripts/rebuild_semantic_map_layout.py` now selects the certified settings
explicitly (`minimum_coordinate_separation=0.00032`,
`maximum_separation_iterations=128`) and writes only
`.cache/semantic-map-layout-v3/artifact.json`; v2 remains intact. The v3
artifact logical hash is
`469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38`, its
settings hash is
`17bcc83100219b10fbb41adb08847eaa1ed3dafbaa396738e2daae9e760a76a9`, and
its artifact byte hash is
`e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972`.

The normal certification default now selects that v3 path and passes
`--require-label-point-exit`. A fresh pre-spacing-follow-up staged
certification, including the shared-tree artist-links exporter changes but no
`dist` write, is at
`.cache/semantic-map-layout-v3-certification/`. Its site logical output hash
is `969853b09ccb85c8454d953200c530e6ffbdaa39f16e243548dd87f2ab447fe2`,
its manifest byte hash is
`0609da3fb67206468902b21b2448b93ac41db742da019efcdd8c8bae3f795ab4`, and
its strict browser report byte hash is
`98f6e31175749baceceeade8444d549c2c5e233d65a8bd8232a427b974001340`.
The 17-screen capture set passed the overview, focus/artist, dark/mobile, and
conditional interior-label-exit gates.
