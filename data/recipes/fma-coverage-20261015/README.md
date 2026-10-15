# Reviewed disjoint coverage collection — 2026-10-15

The fixed optional `coverage` collection contains twelve additional licensed native
recordings. Both prior collections remain byte-identical: original 60 and expanded
64, with eight shared recordings. The union is exactly 128 distinct recordings.
This is the existing root limit, not authorization to increase it or add a fourth
collection. Coverage has its own twelve-clip ceiling; the existing per-collection
64-clip, 64 MB, 2 MB per MP3 and 200 KB manifest ceilings remain unchanged.
The portable bundle still permits at most 250 MB and 10,000 files.

The canonical reviewed recipe SHA-256 is
`a3a15f7134fbaea3c1a19b0ac10fd1e00179dc7421bc2aab34dad8b89cb4d950`.
It binds both prior manifests, the frozen proposal, the completed capture and every
new playback/native source record. The complete prior roster is retained as IDs,
not nested historical manifests. Only this individually approved recipe is
registered. Producing a different recipe does not approve it.

The capture used 24 serial official-source range requests: 11,544,903 response
bytes yielded 12,383,742 MP3 bytes. Independent custody checks replayed the native
metadata, retained ZIP ranges, CRCs, SHA-256 hashes and twelve full decodes. A
separate standard-library reconstruction matched the manifest core and recipe.
No full-archive hash, musical-quality validation or public deployment is claimed.
Audio and external capture payloads are not included in the repository.

The frozen source selection explicitly permits one eight-tag Radio Art example;
this is a metadata selection exception, not evidence of musical representativeness.
All twelve selections and source hashes remain bound by the exact proposal.

To reproduce offline, run `scripts/build_fma_coverage.py build` with the retained
`--original-audio`, `--parent-audio`, `--capture` and `--proposal` inputs; use this
file's sibling `coverage-recipe.json` as `--recipe` and a fresh `--output` path.
The capture directory must include its exact `listening.json` and MP3s. The CLI
enforces 120 seconds and a 1 GB address-space limit before source imports. Full
decoding preserves the existing subprocess limits. No acquisition is performed.
