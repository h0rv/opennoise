# Reviewed bounded listening extension — 2026-10-15

This offline recipe adds 12 licensed native recordings to the expanded collection.
It keeps all 44 earlier additions and eight original recordings, including every
protected paired example. The separate original collection remains unchanged at
60 recordings: the two collections contain 116 distinct recordings in total.
Each collection retains the existing 64-recording, 64,000,000-byte ceiling;
each MP3 stays below 2,000,000 bytes and each manifest below 200,000 bytes.

The exact recipe's canonical SHA-256 is
`9ebbe4940e3e806bfcfdd7724fdd4b37dbc1a51978d788d8a40b908b863e3d24`.
Its source bindings pin the original and parent playback manifests, frozen
proposal and completed capture receipt. Its manifest-core hash binds every
output record and flat native source inventory. Generating a different recipe
does not authorize export; only individually reviewed recipe hashes are accepted.
Historical collection validators and pins remain unchanged.

The approved official-source capture used 24 serial range requests and transferred
11,766,713 response bytes, yielding 12,115,189 MP3 bytes. Independent custody
verification replayed retained ranges, ZIP records, CRCs, native identities,
licenses and full decodes. A separate standard-library reconstruction matched the
recipe and manifest-core hash. No complete archive hash was verified. Neither
musical quality nor representativeness has been validated; no public deployment
is authorized by this recipe. Audio and external capture payloads are not checked
into the repository.

| Native track ID | MP3 bytes | MP3 SHA-256 |
| --- | ---: | --- |
| 129260 | 1,202,210 | `4387d3c13a8e56e343d12ff1f67eee2f2b333ccaba6222203106a20c2e7a236f` |
| 105841 | 1,201,309 | `7ed77d09f40d6bbb2b623d9e453d29de0d53dfe3e06cdeb3d5117a8770d67258` |
| 127935 | 1,201,275 | `0036a5c1d0429f8c85a7c797768fd64150a66e0c1a11874644b51241145a7be4` |
| 65233 | 961,133 | `4d46835e9e24396dfdf8aaf6f2c1682ec287999afada83865b0874323b92ef18` |
| 125714 | 994,376 | `a61da7bea9b83c8fdec7970f26cffccf449d79aac9a7b716489877c5f8b927cf` |
| 86657 | 733,453 | `5e29a7714672d371723f8aea30b4a616f63b05fde75c9483e9e65a7f45a14e20` |
| 62338 | 961,116 | `9204e00b777fc2ff999a5f1cc761967dba51ecfc13a086658298877de8a5f2e8` |
| 128711 | 1,051,791 | `f1e0551c6fb71a9a858af012e68bc074b430bab2d027f3e3d6302dcde657c2d4` |
| 63081 | 1,200,195 | `2cb0dae6506d2650f86934544cadce68d4cb59dd5d5edfc0defa95398a7a5124` |
| 124100 | 1,201,147 | `d0e3dbe579593343791b386c5b0bf5b74b7c74c31b39d9079373dbad2828534c` |
| 134265 | 446,198 | `f72205ff65c13c3852dc228c15d615688a620228bdbdd59bfb44dccc554c1b56` |
| 138650 | 960,986 | `18dbd71213093c07b7beb78081a7d4087a3f900a8f65de26d47b9af4335452bb` |

## Offline reproduction

Supply the retained, hash-matching original and parent audio directories, the
verified capture directory (including `listening.json` and twelve MP3s), and the
frozen proposal to `scripts/build_fma_bounded_extension.py build`. Pass this
`extension-recipe.json` with `--recipe` and a fresh output directory with
`--output`. The other required flags are `--original-audio`, `--parent-audio`,
`--capture` and `--proposal`. The CLI enforces 120 seconds and a 1 GB address-space
limit; full MP3 decodes retain the existing subprocess limits.

The original and parent manifest bytes are already retained in
`data/recipes/fma-reconstruction-20261013/original-playback-manifest.json` and
`data/recipes/fma-four-artists-20261013/playback-manifest.json`. The new proposal
and capture receipt hashes are recorded in the recipe; they are not replaced
by synthetic examples. This file does not authorize reacquisition or retries.
