# Exact recording feature companion

The companion builder joins verified native recording observations to the
separately verified AcousticBrainz sonic pack. It emits one row per original
artist/recording observation, retaining the original capture reference. It does
not deduplicate songs, infer artist identity from names or uploader tags, or use
cohort selection as a credit. Both complete native artist-credit sets must agree;
conflicts retain both facts but quarantine the entire numeric vector.

Build and replay the checked-in bounded source packs without network access:

```sh
.venv/bin/python scripts/build_recording_feature_companion.py build \
  --observations data/examples/recording-facts \
  --sonic data/examples/native-sonic --output .cache/recording-features-v1
.venv/bin/python scripts/build_recording_feature_companion.py replay \
  --observations data/examples/recording-facts \
  --sonic data/examples/native-sonic --output .cache/recording-features-v1
```

For a normalized catalog, pass its directory as `--observations`, the original
native catalog as `--native-source`, and the repository as `--root`. This route
first invokes the existing full native normalized-dataset replay. It cannot run
from a self-consistent normalized receipt alone. The large selected-150 inputs
remain blocked by recovery access; only synthetic integration fixtures exercise
that adapter in this change.

`features.jsonl.gz` is a streaming JSONL table. `report.json` supplies the fixed
ordered `numeric_paths`; each row has aligned `values` and `observed` arrays.
Missing descriptors are JSON null, never zero. Failed observation credits,
missing companion records, unavailable sonic evidence, absent companion credits,
and conflicting credits remain explicit join states. Zero-observation artists
remain in the report, alongside the original source coverage declarations.
Counts describe artist/recording observations, not globally unique recordings.

On the authentic checked-in packs, all 36 observations survive: 24 join, five
have no companion recording, and seven have unavailable sonic evidence. The
24 joined rows each have 14 of 17 fields, so **zero rows have a complete declared
feature vector**. These are data preparation results on previously captured,
selected sources; they are not new captures, model scores, or musical validity.
Unknown original source dates and transport completeness remain unknown.

Replay re-verifies both native sources, rebuilds the complete output, and
compares exact artifact hashes. Resealing a modified feature table does not make
it pass. Output is fresh-only, outside source custody, capped at 250,000 rows
and 20 MB, and streamed without holding the observation corpus in memory. A
budget failure retains the partial attempt without a successful report.

Future models must group shared recordings and connected credited artists,
albums and duplicate recordings before splitting. Any column selection,
imputation or normalization must be fitted on training rows only. This artifact
provides no split, fitted transform, annotation targets, calibrated probability,
audio permission, independent listening judgment, or production promotion.
