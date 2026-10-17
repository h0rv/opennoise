# Jamendo human happiness annotation diagnostic

This local noncommercial study asks whether uploader genre and instrument tags
predict separately collected human happy/not-happy judgments. It does not test
audio descriptors, pairwise musical similarity, recommendation usefulness or
EveryNoise parity. No source data, model or prediction enters serving.

## Source and rights boundary

The official [MTG-Jamendo repository](https://github.com/MTG/mtg-jamendo-dataset/tree/cafd8e20c265ed84f1e61f1c875327971f43a62f)
provides the uploader split-0 test metadata and raw Music Classification
Annotations. Only these two metadata files were acquired, totaling 9,080,731
bytes. Their exact published sizes and Git blob hashes matched before parsing;
local SHA-256 hashes also bind the retained bytes.

The metadata is CC BY-NC-SA 4.0, copyright Music Technology Group, and the
upstream repository restricts use to noncommercial research and academic use.
Data-derived research outputs retain those terms and attribution separately
from the project's MIT code. This study grants no product integration or
deployment rights. Cite Bogdanov, Won, Tovstogan, Porter and Serra (2019),
*The MTG-Jamendo Dataset for Automatic Music Tagging*, and the upstream Music
Classification Annotations documentation.

An earlier AcousticBrainz annotation inventory request to the official Zenodo
API and a separate HEAD request to the Jamendo descriptor host each failed with
proxy tunnel HTTP 403. Neither was retried or accessed through a mirror. The
GitHub annotation files are different artifacts, not a substitute transport
for either denied feature/archive request. No audio, descriptors, credentials,
paid services or deployment were used.

## Frozen design

The protocol hash is
`8832fc5c34298073394ef5a6470f909a607575843211005febf3c202f63d12c0`.
Its manually rounded timestamp is corrected in the preserved timing note;
the acquisition receipt binds the protocol bytes before source capture.
The independent identity-only cohort hash is
`c5f3ce5d9d588c632782b3b93ee71f3d83f8fe197ea3deb76dd58cd8acc62a72`.
All 11,565 recording identities agree across the two files and form 713
artist/album-connected components. Five folds are assigned by the fixed
component hash before human votes or model outcomes are inspected.

Exactly three recognized happy/not-happy votes make a row eligible; 2:1
disagreements remain fractional targets. No consensus-only filtering is used.
Only training components determine the genre/instrument vocabulary, weighted
human prior and fractional Bernoulli naive Bayes model. Each training component
has unit total weight. The model includes both present and absent tag terms,
with fixed add-one smoothing. The literal uploader happy-tag rule has extra
mood information and is reported separately from the matched primary comparison.

The primary metric averages individual-vote Brier loss within each eligible
component, then equally across components. The paired 2,000-draw component
bootstrap conditions on fixed out-of-fold predictions; it does not establish
population significance. No hyperparameter, taxonomy or cohort search is made.

## First frozen result

Of 11,565 nominated tracks, 10,614 have exactly three recognized votes and all
receive held-out predictions: 91.78% nominated coverage and 100% eligible
coverage. The 951 remaining rows have fewer than three votes. The scored set
contains 699 components; 4,933 eligible tracks have disagreement. No missing
judgment is treated as a negative label. The largest nominated component has
548 tracks.

| Fixed method | Component-equal individual-vote Brier | Track-weighted Brier |
| --- | ---: | ---: |
| Training human prior | 0.230675 | 0.230394 |
| Genre/instrument Bernoulli NB | 0.222971 | 0.221803 |
| Privileged uploader happy-tag rule | 0.230190 | 0.228986 |

Lower Brier loss is better. The primary NB-minus-prior difference is
-0.007704, with a conditional component-bootstrap interval of
[-0.013790, -0.001880]. The track-weighted difference is -0.008591 with
interval [-0.019173, 0.000884], which includes zero. These are fixed-cohort,
fixed-prediction intervals, not population significance or retraining estimates.
The result supports modest metadata predictiveness for this human annotation
task and does not select a serving model or justify a musical-usefulness claim.

See `results.json` for all frozen outcomes and denominator details.

## Verification and replay

The independent core implementation, including the primary metric and bootstrap,
was frozen before seeing producer outcomes and remained unchanged. A separate
comparison adapter, including auxiliary bootstrap checks, was added after
outputs existed. Together they reproduced all 11,565 identities and folds,
10,614 scored queries, 31,842
probabilities, five fold models and all metric/bootstrap results. Maximum
probability difference was 6.66e-16; Bernoulli parameter differences were zero.
The production implementation's own sealed numerical replay also passed.
The independent review receipt SHA-256 is
`33b55757e5dbc0a9e09838c405d6a66fdc60663752bd6a80d983bd4dac06c0ff`.

The offline CLI has separate `prepare`, `evaluate` and `replay` stages:

```sh
PYTHONPATH=src .venv/bin/python scripts/run_jamendo_human_mood.py prepare \
  --protocol /workspace/opennoise-fresh-signal-20261017/protocol.json \
  --receipt /workspace/opennoise-fresh-signal-20261017/acquisition-receipt.json \
  --receipt-sha256 5e62cf2b4b4a2a163071e016f8420fff38611630a1175edf141484997c3ece88 \
  --output /tmp/jamendo-prepared
sha256sum /tmp/jamendo-prepared/seal.json
PYTHONPATH=src .venv/bin/python scripts/run_jamendo_human_mood.py evaluate \
  --prepared /tmp/jamendo-prepared --seal-sha256 HASH_FROM_PREVIOUS_STEP \
  --output /tmp/jamendo-results
PYTHONPATH=src .venv/bin/python scripts/run_jamendo_human_mood.py replay \
  --prepared /tmp/jamendo-prepared --seal-sha256 HASH_FROM_PREVIOUS_STEP \
  --output /tmp/jamendo-results
```

The receipt points to retained local source paths. Moving inputs requires a
separately pinned location receipt and fresh preparation, preserving the
published source sizes and blob hashes; never silently edit a sealed run.
The CLI enforces 120-second CPU/wall, 1 GiB address-space and 20 MB output
bounds. Acquisition used 20-second socket timeouts with a 30-second wall alarm.

## Limits

Upstream tag-frequency preprocessing used the source corpus; only this study's
fit is fold-local. Annotator identities, cross-record listener independence and
annotation blinding are not established. Artist/album grouping and duplicate
track/path rejection do not detect recordings reissued under different native
identities. No audio fingerprint or cross-catalog alias audit is available.
FMA and previous MusicBrainz/AcousticBrainz models are excluded from all inputs;
this does not prove that every artist is new across catalogs. The original
Jamendo test partition is used as a new internal cross-validation cohort, not
claimed as an untouched external test of an existing model.
