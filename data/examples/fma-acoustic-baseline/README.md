# Native FMA acoustic baseline: saved replay pack

This small CC-BY-4.0 pack preserves one prespecified acoustic experiment on the
FMA 2017 native metadata snapshot. Attribution: Michaël Defferrard, Kirell Benzi,
Pierre Vandergheynst and Xavier Bresson, *FMA: A Dataset For Music Analysis*,
ISMIR 2017, <https://github.com/mdeff/fma>. The retained official README describes
computed Librosa features and licenses metadata under CC-BY-4.0. Audio has
separate source declarations; no audio, proprietary EchoNest data, pickle,
EveryNoise labels or MusicBrainz supplementary data was acquired or used here.

`model.npz` contains the trained 44-channel positive-only Gaussian weights and
native genre IDs. `evaluation.json` binds the source receipts, frozen declaration
and implementation hashes, fold ledger and full held-out acoustic rankings.
`held-out-native-targets.jsonl.zst` is a small projection of the separately
hash-bound native track metadata, enabling exact saved-metric replay:

```sh
PYTHONPATH=src .venv/bin/python scripts/replay_fma_saved_ranks.py \
  data/examples/fma-acoustic-baseline
```

This verifies saved byte bindings and source-positive metrics without model
refitting. It does **not** replay absent native source bytes. The retained native
feature member is a separate 293 MB local capture; neither that member, the
19 MB numeric corpus, nor native metadata compressed members are shipped in this
pack. Acquire them through the bounded capture adapters and replay their entire
native CSV streams to establish raw custody. The full ZIP archive hash was not
verified; the entire feature member's CRC and observed SHA256 were verified.

For fitting and scoring, use `fit_positive_gaussian` and
`score_positive_gaussian` in `opennoise.ml.fma_acoustic_baseline`. Queries require
the identical ordered 44 mean channels in `SELECTED_COLUMNS` in
`opennoise.ingest.fma_features`; the conceptual zero-crossing-rate channel is
explicitly mapped to native `zcr`, statistic `mean`. These APIs accept numeric
features without artist names, cultural labels, MusicBrainz IDs or reference-map
construction. Weights are stored as numeric NumPy arrays; load with
`allow_pickle=False`. Preserve missingness and abstention semantics when using
the model.

Observed native **track** genres are incomplete targets. Rankings and density
scores are uncalibrated source-label recovery, with no precision, independent
musical-relevance or artist-genre claim. Native artist/album/full-cell-duplicate
isolation leaves unknown albums and nonexact recording/performer aliases
unresolved. The model is an independently licensed research foundation and
has no authorization flag for public product promotion. No MBID bridge or
known-benchmark coverage is established.
