# Reproducible foundation

The checkout contains source code and some small checked-in model artifacts.
It does not contain every source snapshot, research cache, sealed release input,
or a complete Every Noise replacement. Run the direct inventory command to see
what this checkout can run now:

```sh
.venv/bin/python scripts/foundation_manifest.py plan
.venv/bin/python scripts/foundation_manifest.py validate --json
.venv/bin/python scripts/foundation_manifest.py validate --stage portable-examples
```

Pass `--root /path/to/checkout` to inspect another checkout. `plan` shows the
declared stages and missing inputs; `validate` exits 1 when one or more selected
stage dependencies are missing. Use `--stage` to check portable examples without
requiring absent full-corpus or canonical-release inputs. Both commands validate the manifest schema and
refuse symlinked paths. Output hashes bind each declared input file's bytes and
each stage's declaration plus those file hashes. Inputs must be files; a directory
cannot stand in for a missing receipt. Hashing a receipt does not verify every
underlying dataset member: use its source-specific offline replay for that check.
The versioned inventory lives in
`src/opennoise/pipeline/foundation.py` and is intentionally not a general task
runner.

`poe sync && poe check` is the clean-checkout baseline. `poe build` also needs
`data/public.sqlite` and `.cache/semantic-map-layout-v3/artifact.json`; the
ignored files must be supplied locally. The parity comparison additionally
uses a pinned historical Every Noise snapshot through `poe bootstrap`. That
snapshot is a dated evaluation reference, never a model or serving input.

Research recipes and their measured limits are recorded in
[`EVERYNOISE_PARITY.md`](../EVERYNOISE_PARITY.md) and the linked checkpoints.
For example, the source-only explorer recipe is in
[`SOURCE_MODEL_UI_BATCH_20260930.md`](../checkpoints/SOURCE_MODEL_UI_BATCH_20260930.md).
Those commands require source snapshots and caches that a fresh clone does not
have. Run builders with new `.cache` output paths; completed candidates are not
overwritten.

Two smaller, self-contained projections make source-role examples runnable in
a fresh checkout. The numeric-only acoustic sample contains artist-level
descriptor summaries and source hashes, with no raw tags, audio, or cultural
neighborhoods:

```sh
.venv/bin/python scripts/demo_acoustic_descriptors.py
```

The credited-work sample contains exact artist credits, bounded recording and
release-group examples, and a receipt that hashes the projection. Replay its
transparent ranking into a local output file with:

```sh
.venv/bin/python scripts/rerank_projected_artist_work_examples.py \
  data/examples/representative-music/credited-examples.json \
  --receipt data/examples/representative-music/receipt.json \
  --output .cache/foundation-demo/representative-music.json
```

Both are examples of metadata provenance and local replay. They do not claim
musical similarity or complete Every Noise parity.

License classes remain explicit. MusicBrainz identity, names, and core
metadata are CC0. MusicBrainz tag and genre-association packs carry
CC-BY-NC-SA-3.0 obligations and are optional, noncommercial research inputs;
they are not needed for the clean-checkout checks or canonical static release.
Treat noncommercial-derived results as a separate rights class from the CC0
core, and preserve applicable attribution and share-alike obligations when
sharing them. Every optional pack must retain its source license capture,
attribution, and receipt alongside derived artifacts. Other providers retain
their own source-specific terms. The repository's static publication gates
remain independently applicable to any proposed release.
