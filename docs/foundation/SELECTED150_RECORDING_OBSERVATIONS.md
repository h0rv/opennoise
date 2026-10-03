# Reusable native recording observations

The normalized producer is a data-only consumer of the independently replayed
selected-150 MusicBrainz catalog. An actual export and fresh native/table replay
both passed on 2026-10-03. The local artifact is
`/dev/shm/opennoise-selected150-recording-observations-20261003-v1`, with receipt
SHA256 `0a21e9de4bea8b96d07fcbc12734242daf13acb5636c506bd6bd57129efb13d2`.
The derivative and calibration artifacts are preserved in a single Library ZIP,
8,238,577 bytes, SHA256
`55ed4bc7769f7f33e5c8c5e5e6ccce5de3a90425a46db40c605b72e9ef659626`.
Its exact reference is
`library-file:fde1_bGliZmlsZV91aVRLd3Zsa0Y3OWZqNkF5TUZRZ0Jn_FileDrive_ffc1ab065d648191ad96bed02037d5b3`.
The transfer manifest is
`library-file:fde1_bGliZmlsZV9lX1pmVkRuT0FhcVZwSG10NkI1aDVR_FileDrive_ffc1ab065d648191ad96bed02037d5b3`,
2,038 bytes, SHA256
`5b017c5b261ebbb691a03e104848f532edcc1e435b1415341dbec886ba65aa47`.
The service confirmed outside-executor access and matching size/hash; a full
UTF-8 manifest readback matched. No independent binary redownload is claimed.
These checks do not establish full-input acceptance, musical relevance, or
Every Noise parity.

The input is the separately named `opennoise-selected150-recording-catalog-20261003-v3`
pack, whose closed receipt SHA256 is
`682e0e963a63c574f9f8729b4c74f8b42aa5bfcd35e41b1a21eeb1bd11b68f9d`.
See [the native catalog report](SELECTED150_RECORDING_CATALOG_V3.md).
Its 161,339 observations cover exact credits for 150 selected artist UUIDs.
147 artists have observed-window completion; three retain count-drift states and
nine have independently probed zero counts. These are live API observations,
not a transactional snapshot or a globally unique recording/song denominator.

## Tables and joins

`observations.jsonl.gz` contains one row per admitted artist/source-page/row:

| Field | Meaning |
| --- | --- |
| `artist_mbid` | Exact selected MusicBrainz artist UUID. |
| `recording_mbid` | Exact native recording UUID; eligible for identifier joins. |
| `title` | Native recording title; not an identity join key. |
| `length_ms` | Native length in milliseconds, or null. |
| `credited_artist_mbids` | Literal UUIDs in the native artist credits. |
| `source.capture_sequence` | Foreign key into the capture table. |
| `source.row_index` | Zero-based row position in the native page. |

The observation key is the artist UUID plus capture sequence and row index.
Joint recordings can occur under multiple selected artists. The exporter keeps
those observations separately and does not resolve conflicting titles/lengths or
equate a recording UUID with a unique musical work. A training pipeline must
consider shared recording UUIDs when grouping observations across folds.

`captures.jsonl.gz` retains every outcome, including closing probes. It contains
the exact request, capture sequence, fetched UTC time, HTTP status, declared
outcome, decoded native SHA256/byte count, and body completeness. Join observations
on `capture_sequence`; do not join display names. Closing probes do not generate
recording observations.

`dataset.json` retains all artist coverage states and the exact per-artist count
denominators. `global_unique_recordings` remains null. The metadata is CC0 within
the approved MusicBrainz core-field scope. It grants no audio permission and
contains no listening, representativeness, genre prediction, or musical judgments.

## Production and verification

The producing run lasted 09:51:02–09:51:21 UTC and reported actual process
high-water memory of 38,666,240 bytes. A separate native/table replay lasted
09:52:20–09:52:35 UTC and reported 38,940,672 bytes; both exited zero. The
closed 21-file artifact occupies 6,847,914 logical bytes and 6,889,472 allocated
bytes. Its observations contain 161,339 rows and decode to 45,724,129 bytes;
its captures contain 1,864 rows and decode to 951,082 bytes. Before/after full
native-file inventory fingerprints matched in both stages.

The [public evidence](../reports/SELECTED150_RECORDING_OBSERVATIONS_20261003.json)
binds the actual output, source, producing implementation, and process proofs.
The [closed receipt](../reports/SELECTED150_RECORDING_OBSERVATIONS_V1_RECEIPT_20261003.json)
retains every output member and both encoded/decoded table hashes. No audio, UI,
HTTP acquisition, or base-v8 reconstruction occurred in these two stages.

Run the data producer against a restored native source pack and its exact producing
source dependencies. Use a new destination outside native custody:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python scripts/export_normalized_recording_dataset.py export --source /path/to/native-v3 --output /path/to/new-dataset --root /path/to/opennoise
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python scripts/export_normalized_recording_dataset.py verify --source /path/to/native-v3 --output /path/to/new-dataset --root /path/to/opennoise
```

Each gzip table has one member, no filename, and timestamp zero. The receipt binds
encoded and decoded SHA256 values, byte counts, and row counts. Verification
rejects trailing empty members/padding and compares every table row with freshly
replayed native input. The whole closed dataset has a 10,000,000-byte encoded cap;
the process guard measures actual `/proc/self/status` high-water memory below
40,000,000 bytes. Failed or interrupted candidates remain unpromoted.

`construction.json` binds an executable callable/CLI recipe and snapshots of all
11 frozen source dependencies plus the normalized producer, native fact projector,
and CLI. API callers explicitly record no historical CLI argv. Actual execution
timing/argv/resource evidence is retained separately. Source snapshots and a
self-consistent receipt do not replace original native custody and its replay.

Once an artifact passes native verification, stream its rows without loading the
whole dataset:

```python
import gzip
import json

with gzip.open("observations.jsonl.gz", "rt", encoding="utf-8") as stream:
    for line in stream:
        observation = json.loads(line)
        # Join exact IDs and preserve missingness and source grain.
```
