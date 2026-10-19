# Optional AB178 candidate-component comparison

This fixed structural comparison consumes an externally pinned, verified
crossfit artifact. It reconstructs every eligible frozen-candidate Euclidean
distance for each already emitted own-fold query and proves the existing
nearest-five recording IDs/distances exactly before selecting representatives.
The optional policy keeps the nearest recording per known candidate credit
component before the same top-five truncation, using raw distance then native
recording MBID ties. It never pads results or changes the frame, fit, support
gate, query component exclusion, contract or fold.

Existing router, crossfit and engine code are unchanged. The original baseline
neighbors remain the top-level `neighbors` and default policy;
`component_neighbors` is the explicit alternative. All 100 nomination outcomes
and all 18 contract/fold cells remain present. Only each selected recording's
exact native credits supply artist observations. Credits from other recordings
in the same component are never inherited. Every recording/artist observation
retains its contract/fold/bundle/frame proof.

The checked protocol was frozen before this comparison. SHA256:
`cfd44c8d03ef4222cc5dc0119cc3c64732e84d6a3b65be0f9625b3a6976941c8`.
The input is the prior historical CC0 AcousticBrainz/MusicBrainz-core crossfit
artifact, not raw audio, a new source capture or independent musical judgments.
Its manifest SHA256 is
`f24b2306e0ab997db68e79483ccae993357bb3b4dc3c66d2b04cd3d5f3b8c6e7`.
Build that input using the [crossfit recipe](../ab178-crossfit/README.md), or
relocate the complete already pinned input directory.

From the repository root, using a fresh comparison output path:

```sh
.venv/bin/poe sync
.venv/bin/python scripts/run_ab178_component_neighbors.py build \
  --crossfit /absolute/path/to/ab178-crossfit-20261019 \
  --crossfit-pin f24b2306e0ab997db68e79483ccae993357bb3b4dc3c66d2b04cd3d5f3b8c6e7 \
  --protocol data/recipes/ab178-component-neighbors/protocol.json \
  --protocol-pin cfd44c8d03ef4222cc5dc0119cc3c64732e84d6a3b65be0f9625b3a6976941c8 \
  --output .cache/ab178-component-neighbors-reproduction
```

The command prints the new external manifest pin. Keep it separately. Copy the
three comparison files and the existing frozen crossfit input to new locations,
then verify/reproduce without raw sources, fitting or networking:

```sh
.venv/bin/python scripts/run_ab178_component_neighbors.py verify \
  --crossfit /relocated/path/to/ab178-crossfit-20261019 \
  --crossfit-pin f24b2306e0ab997db68e79483ccae993357bb3b4dc3c66d2b04cd3d5f3b8c6e7 \
  --registry .cache/ab178-component-neighbors-reproduction \
  --manifest-pin PRINTED_COMPARISON_MANIFEST_SHA256
```

The small output contains only protocol, comparison and manifest JSON, with
external input/protocol/output pins and targeted runtime/code hashes. Verify
checks its closed inventory and reconstructs both policies from the pinned
crossfit evidence. Publication is staged and atomic. The CLI enforces one
numerical thread, 120-second wall/CPU bounds, 1 GB address space, a 4 MB total
output cap and 2 MB per file. Underlying crossfit validation retains all prior
source, identity, frame, query and resource checks.

The retained 2026-10-19 comparison reproduced the baseline exactly and preserved
all 11 emitted queries plus 12 outside-support, 11 insufficient-support, 21 dirty
and 45 missing source outcomes. No abstained query is retrieved again. Its
`retrieval_attempted` is false and eligible-pool counts are zero because ranking
is not attempted; these zeros do not measure potential unsupported coverage.

| Structural count | Existing nearest recording | Optional nearest component |
| --- | ---: | ---: |
| Recording edges | 55 | 38 |
| Sum of per-query distinct returned components | 32 | 38 |
| Global native component union | 7 | 9 |
| Sum of per-query distinct exact candidate artists | 42 | 42 |
| Global exact candidate-artist union | 9 | 11 |

Six queries gain returned components and none lose components. Six queries gain
at least one exact credited artist, while **four queries lose at least one
artist**; gain/loss groups may overlap. Each query retains explicit gained/lost
native IDs in the machine-readable comparison. Fewer recording edges and more
component representatives do not establish musical relevance or a general
artist-coverage improvement. This is an optional structural tradeoff against
already inspected historical outputs, not calibration, genre accuracy, listener
quality or EveryNoise parity. The baseline remains unchanged.

Local output `.cache/ab178-component-neighbors-20261019` has 320,585 bytes.
Manifest SHA256:
`a70ca5f024e862cf6e1577d796645f61bd89979be7ff75edb51d64412ae78985`.
Comparison SHA256:
`742b297c9223fed51f865252a4351ffafe2ea241b458802d8ae71447cb040546`.
Six focused tests passed: retained-source baseline/outcome equivalence and
coverage losses, exact selected-recording credit/frame proof, ties/component
exclusions/no inherited credits, baseline-disagreement rejection before policy
selection, relocated no-source/no-refit replay, tamper/pin/protocol/fresh-output
failures. Test fixtures construct the frozen crossfit input once; comparison
execution is tested with fitting disabled. No acquisition attempt; external cost
$0.

The independent parent audit confirmed all 100 baseline rows unchanged, all 18
cells retained, all 11 emitted comparisons and all 38 selected edges matching
the frozen arithmetic oracle exactly. Maximum distance error was zero. Both
policies' 105 exact-credit artist observations and their provenance were checked
(63 baseline, 42 component-policy observations). An actual relocated CLI replay
passed under independently pretested source/fitting/network denial hooks, with
zero forbidden opens or refits. Local reports are in the root checkout's ignored
`.cache/ab178-component-neighbors-audit-20261019.json` and
`.cache/ab178-component-neighbors-relocated-audit-20261019.json`, bound to the
manifest above. Independent Luna static review found no material issue.

Final `poe check` passed: format/lint/type checks; 166 Node tests (122 passed,
44 skipped, zero failures); 2,212 Python tests in 157.542 seconds (36 skipped).
All six focused comparison tests passed. Existing router, crossfit and engine
implementations and their runtime pins remain unchanged.
