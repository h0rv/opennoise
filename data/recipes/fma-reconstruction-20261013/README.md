# Fresh native FMA reconstruction, 13 October 2026

This recipe preserves source identities, licenses and hashes without storing audio
in Git. It records a new official capture, not the historical October 4 receipts.
The initial metadata/model stage used main `e9a505b99bf6eeed4d2ee3e8d853b29f4ce4fdb3`.
Its ten requests transferred 304,921,396 bytes. All selected native CSV members
passed full-stream CRC and observed SHA-256 checks. The full ZIP hash was not
verified because only bounded member ranges were fetched.

`small-audio-roster.json` and `large-audio-roster.json` retain every selected
native recording/artist ID, exact archive member and offset, audio SHA-256,
source-declared license URL, credits and byte limits. Audio licenses are separate
from the metadata CC-BY-4.0 license. Only the existing CC0/BY/BY-SA allowlist is
accepted. These are source claims from the FMA snapshot; no new rights inference
or public hosting is authorized. Original and expanded exports contain 60 and 64
clips, respectively; their union is 92 recordings. The expanded view includes 32
new clips and 32 from the original selection. Matching counts alone do not prove
identity with an unavailable historical bundle.

## Offline reconstruction from the retained capture

Use Python 3.13, `poe sync`, and the scripts in this checkout. Set `ROOT` to the
extracted capture directory. Every output below must be a fresh path. The
metadata and feature source receipts in this folder document the original range
bytes; they must not be copied onto a different acquisition without exact byte
verification and an explicit reconstruction record.

```sh
ROOT=/workspace/opennoise-rebuild-20261013
.venv/bin/python scripts/acquire_fma_native_metadata.py --source "$ROOT/metadata-source" --output "$ROOT/replay-metadata"
.venv/bin/python scripts/capture_fma_acoustic_features.py project --source "$ROOT/feature-source" --output "$ROOT/replay-features"
.venv/bin/python -m scripts.audit_fma_native_source --source "$ROOT/metadata-source" --projection "$ROOT/metadata" --output "$ROOT/replay-metadata-audit.json"
.venv/bin/python -m scripts.audit_fma_acoustic_source --source "$ROOT/feature-source" --features "$ROOT/feature-source/projection" --metadata-tracks "$ROOT/metadata/tracks.jsonl.zst" --output "$ROOT/replay-feature-audit.json"
.venv/bin/python -m scripts.audit_fma_acoustic_model --metadata "$ROOT/metadata" --features "$ROOT/feature-source/projection" --model "$ROOT/baseline44" --output "$ROOT/replay-model-audit.json"
.venv/bin/python scripts/capture_fma_listening64.py verify --source "$ROOT/metadata-source" --output "$ROOT/listening60"
.venv/bin/python scripts/capture_fma_large32.py verify --source "$ROOT/metadata-source" --baseline "$ROOT/listening60" --output "$ROOT/listening32"
.venv/bin/python scripts/export_fma_playback.py --pack "$ROOT/listening60" --metadata-source "$ROOT/metadata-source" --output "$ROOT/new-site/original/audio"
.venv/bin/python scripts/build_fma_listening_collection.py --new-pack "$ROOT/listening32" --metadata-source "$ROOT/metadata-source" --baseline "$ROOT/listening60" --original-audio "$ROOT/new-site/original/audio" --output "$ROOT/new-site/expanded/audio"
```

All MP3s undergo a bounded full offline decode. For each collection (`original`
and `expanded`), run `scripts/build_fma_reconstructed_neighbors.py` stages
`freeze`, `build`, and `verify`, supplying `--audio`, `--pack "$ROOT/baseline44"`,
`--features "$ROOT/feature-source/projection"`, `--metadata "$ROOT/metadata"`,
`--native-declaration "$ROOT/native-declaration.json"`, plus a fresh declaration
and output for that collection. This v3 protocol pins the exact reconstructed
original-training model and declaration. It does not accept arbitrary newly
fitted models, or relabel historical inner-fit inference.

Then run `scripts/build_fma_static_catalog.py` twice with `--source`,
`--projected`, the collection's `--playback` and `--playable-neighbors`, and
`--output "$ROOT/new-site/COLLECTION/explorer"`. Optional source taxonomy uses
`--source-genres data/examples/open-genre-taxonomy`; retained artist context uses
`--artist-context-root .`. Run `scripts/build_fma_listening_home.py --root
"$ROOT/new-site"`, then `scripts/build_fma_genre_discovery.py --root
"$ROOT/new-site"`. No descriptor-map or full-catalog related-track inference is
included in this reconstruction.

Create the new, separately versioned listening pilot with:

```sh
.venv/bin/python scripts/build_fma_audition.py --site "$ROOT/new-site" --metadata-source "$ROOT/metadata-source" --output "$ROOT/new-audition"
OPENNOISE_FMA_DISCOVERY_SITE="$ROOT/new-site" node --test tests/static/fma_genre_discovery_contract.mjs
OPENNOISE_FMA_GENUINE_SITE="$ROOT/new-site/original" node --test tests/static/fma_genuine_playback_contract.mjs
OPENNOISE_FMA_GENUINE_SITE="$ROOT/new-site/expanded" node --test tests/static/fma_genuine_playback_contract.mjs
```

Keep each listener folder separate from the coordinator folder and the other
listener. The two 24-item forms are blank. No musical judgments have been made.
The pilot is conditioned on available licensed excerpts, not a global genre,
region, era or artist-quality acceptance sample.

## New network acquisition

Only after explicit source/audio authorization, the existing capture CLIs may
run their `probe`, offline `freeze`, and `capture` stages with new destinations.
Small archive caps: 130 requests, 64 MB response/audio, 64 clips, 2 MB per range.
Large archive caps: 72 requests, 48 MB responses (16 MB directory + 32 MB audio), 32
clips, 2 MB per range. Preserve no-redirect, exact 206, strong ETag, ZIP member,
CRC, size and hash checks. Stop on a source or license mismatch; no retries,
alternate hosts, transport changes, silent roster replacements or cap increases.

Fresh metadata receipts have new timestamps. Generate a new baseline declaration
from the retained template with the actual metadata receipt binding before
feature capture; retain its distinct identity. Historical and this v3 inference
pin must not be silently updated to accept it. A source-equivalent new protocol
needs explicit code/declaration review and numerical replay.

## Variability experiment

`run_fma_temporal_experiment.py` supplies `freeze`, `project`, and `run` stages.
The separately frozen 88-column candidate adds the corresponding native standard
deviations to the 44 means. It fits the same original-training components and
uses unchanged Gaussian/support rules. Standard deviations represent within-
track variability, not temporal ordering. Projection is bounded streaming from
the already retained native member; the model retains 120 seconds, 1 GB memory and
100 MB new outputs. The original 44-column projector's 20 MB guard is unchanged.

The initial new declaration accidentally assigned the model's 120-second limit
to projection as well. A separately preserved superseding declaration corrected
that scope before any projection or candidate fit. Both declarations and the
supersession record are retained with the experiment artifacts. Previously
inspected outer folds are diagnostic. Annotation recall is not musical quality
or Every Noise parity, and no product replacement follows from these results.

## Recorded result and review gate

The 88-column candidate worsened primary micro Recall@10: validation 37.05% to
30.51%, test 39.59% to 33.23%. Macro Recall@10 improved, but MRR declined.
Independent computations reproduced all 13,800 heldout rankings and metrics;
source sampling also checked native standard deviations. Mean44 remains the
listening baseline. No tuning or replacement was made using those diagnostics.

The new audition has 12 genre items and 12 neighbor comparisons per listener,
30 unique clips per slot, and zero judgments. Both actual browser tests passed
local playback, exclusive audio, mobile layout and download of 24 blank answers.
One identical candidate pair remains in the denominator. The coordinator key
must not accompany listener distribution. Actual independent listener responses
are still required to assess musical usefulness; no 70% product-quality claim is
supported. The local Library save failed before transfer; it was not retried.
