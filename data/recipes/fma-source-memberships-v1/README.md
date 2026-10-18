# FMA source membership text recipe

This package carries exact text representations of the nine files in
`data/examples/fma-source-memberships`. The three `.jsonl.zst` files are stored
as strict ASCII Base64; JSON, README, and the immutable Python snapshot are
stored losslessly as UTF-8. The Python snapshot uses `.py.source` so linters do
not treat this recipe directory as an implicit Python namespace.

The source data and derived source memberships are licensed CC-BY-4.0. Attribute
Michaël Defferrard, Kirell Benzi, Pierre Vandergheynst and Xavier Bresson,
*FMA: A Dataset for Music Analysis*, ISMIR 2017,
<https://github.com/mdeff/fma>. The preserved artifact reports native FMA track
source-recovery suggestions. They are not musical truth, artist genres,
probabilities, or independently validated relevance. This encoding changes no
model, threshold, split, membership, or source file.

From a fresh checkout, materialize into a new directory, then replay against the
existing public acoustic baseline pack:

```sh
.venv/bin/python scripts/materialize_fma_membership_example.py \
  --output /tmp/fma-source-memberships-v1
PYTHONPATH=src .venv/bin/python scripts/replay_fma_memberships.py \
  --saved-pack data/examples/fma-acoustic-baseline \
  --memberships /tmp/fma-source-memberships-v1
```

The output directory must not already exist. The materializer checks the full
known nine-file inventory, encoding, exact decoded byte count, and SHA-256
before it creates that directory. It never modifies the native example pack.
The source-membership replay pack is not a substitute for raw native source
custody; raw files are not bundled here.

## Artist and genre evidence export from retained predictions

The existing membership replay command can now export saved track-membership
observations grouped by **actual FMA native artist IDs**. This independent path
uses the checked-in historical 44-channel baseline and its frozen membership
recipe. It does not need the unavailable FMA518 bundle, raw feature corpus,
Library transfer, new audio, model fitting or a new calibration experiment.

On a fresh checkout after `poe sync`:

```sh
.venv/bin/python scripts/materialize_fma_membership_example.py \
  --output .cache/fma-saved-memberships
.venv/bin/python scripts/replay_fma_memberships.py \
  --saved-pack data/examples/fma-acoustic-baseline \
  --memberships .cache/fma-saved-memberships \
  --saved-pack-receipt-sha256 3e1651c136f5ae0c588e6dd6930a7a8f68fc7b332d1e423d29d1657e20cd0106 \
  --membership-receipt-sha256 ad54dc99a09e0c0f492dd97ac21e216a4a70bfd39a7749932a6f1a1a45646c1d \
  --export-artists .cache/fma44-artist-evidence.json
```

The first command reconstructs the exact existing text recipe; it does not
recalibrate. The second verifies both externally pinned receipts and replays all
existing thresholds, memberships and metrics before joining native identities.
Verification recomputes the frozen calibration for equality; no parameters,
model, thresholds, source predictions or selected labels are changed. Omitting
`--export-artists` preserves the existing replay behavior.

The canonical JSON contains separate `calibration`, `confirmation` and
`test_diagnostic` partitions. Each provides an artist index with nominated track
IDs, abstention counts and genre evidence, plus a genre index pointing back to
artist IDs and contributing track counts. Every genre observation retains its
contributing track IDs. Its `nominated_track_fraction` uses all nominated tracks
for that artist/partition, including abstentions. This is a descriptive fraction
of saved model outputs, never a musical probability or an artist–genre fact.
Observed target labels do not supply aggregation evidence.

The receipt-bound `native-folds.jsonl.zst` supplies `artist_id`; `component_id`
remains a leakage boundary and is never substituted for an artist identity.
Prediction folds/components must match the ledger. Unknown artist rows remain
unassigned. Duplicate/missing query identities, conflicting artist components,
artist/component overlap across partitions, incorrect pins and out-of-custody
outputs fail rather than silently dropping rows or combining partitions.

A retained-data run on 2026-10-18 exported 13,800 historical predictions for
1,714 disjoint native artist IDs:

| Partition | Tracks | Artists | Track abstentions | Artist–genre evidence rows |
| --- | ---: | ---: | ---: | ---: |
| Calibration | 4,096 | 472 | 95 | 4,740 |
| Confirmation | 3,236 | 410 | 78 | 4,104 |
| Previously observed diagnostic test | 6,468 | 832 | 183 | 8,267 |

These rows derive from eleven already calibrated labels and can be broad; their
count is not a quality or coverage improvement. The useful change is a directly
consumable artist/genre evidence index over real retained predictions, preserving
all 356 track abstentions. Independent reconstruction matched every artist's
track set and contributing genre track IDs, and repeat exports were identical.
The original FMA44 validation/test roles remain historical. This is **not** an
evaluation of the FMA518 five-fold protocol, a new heldout result, an artist genre
classifier, EveryNoise parity, or evidence for model/product promotion. Native
raw source replay remains unavailable from this saved pack alone.

Outputs retain CC-BY-4.0 attribution and the original no-promotion boundary.
Each input root and the JSON output are capped at 24 MB, with at most 110,000
native identity rows. The CLI enforces 120 CPU/wall seconds, 1 GB address space
and single-threaded numerical libraries. The output must be fresh and outside
both source packs; all computation and verification precede publication. No
website, acquisition, transfer or deployment occurs.

The checked export is 3,233,788 bytes with SHA256
`30a3f973432c66f6b7234f30371334d043a05861086ed18761eda88e8f53c72d`.
The byte identity includes its producer hash and both external receipt pins.
