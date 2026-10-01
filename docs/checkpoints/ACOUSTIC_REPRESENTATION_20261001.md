# Acoustic metadata representation checkpoint — 2026-10-01

Implemented a reusable metadata-only acoustic representation in
`opennoise.analysis.acoustic_representation`. Recording descriptors aggregate to
artist medians with unique recording counts, feature-specific observed counts,
and explicit missing values. Missing features are never filled with zero.
Conflicting duplicate recordings, boolean descriptors and nonfinite numbers are
rejected. Sonic neighbors use standardized RMS descriptor distance and report
shared feature coverage. Cultural neighbors independently compare inferred micro
community IDs with Jaccard overlap; they are not acoustic facts or artist genre
assignments.

The original exact-credit AcousticBrainz pilot was verified offline before use.
Its immutable feasibility declaration (`model_input_allowed=false`) remains
unchanged. A separate derived research wrapper records the user's instruction to
implement open metadata models. Only CC0 numeric acoustic projections and exact
recording identities enter sonic calculations. Incidental raw tags and high-level
classifiers do not enter the representation. No audio was requested. Every Noise
coordinates or proprietary sonic axes are neither inputs nor claimed outputs.

A real expansion selected the first ten UUID-sorted exact-credit recordings from
each artist's existing 25-row MusicBrainz search response. This is a bounded
search sample, not a full-discography or representative sample. Thirty recording
responses were reused; seventy additional low-level AcousticBrainz requests were
made serially with 1.1 seconds between requests, no redirects and no retries.
New response bytes totaled **2,057,439**, below the explicit 10,000,000-byte cap.
Responses are streamed with a 300,000-byte per-response retention bound. Of 100
selected recording IDs, **55** supplied identity-matched descriptors and **45**
returned HTTP 404. The initial pilot had 18 descriptor-bearing recordings.

| Artist | Descriptor-bearing recordings / 10 selected |
| --- | ---: |
| Jon Hopkins | 4 |
| Four Tet | 4 |
| Autechre | 8 |
| Squarepusher | 10 |
| Boards of Canada | 6 |
| Floating Points | 4 |
| Caribou | 4 |
| Burial (UK dubstep) | 4 |
| Aphex Twin | 6 |
| Brian Eno | 5 |

Local evidence artifacts:

- `.cache/acoustic-expanded-metadata-20261001-v1/`: pre-request declaration,
  retained raw metadata, projected descriptors, captured executed script and
  SHA-256 file inventory receipt.
- `.cache/acoustic-representation-research-pilot-20261001-v1/pilot.json`:
  initial 18-recording representation and independent neighbor views.
- `.cache/acoustic-representation-expanded-20261001-v1/pilot.json`:
  expanded 55-recording representation, missingness counts, per-query scales,
  independent cultural/sonic neighbor lists and source receipt hashes.

The builder verifies the original offline reprojection and each declared
expansion file hash before aggregation. For each query artist it fits descriptor
scales on the other nine artists only. No recording-level random split, cultural
target fitting, model tuning, or retrieval quality claim occurs. This prevents
query artist leakage into normalization; it does not establish useful retrieval
quality. The ten selected electronic-focused artists are insufficient for
calibration or generalization. Artist medians hide catalog variation, and
rankings with different shared feature sets require caution. The artifacts remain
local research with product promotion disabled.

Reproduce using existing receipt-bound caches:

```sh
.venv/bin/python scripts/build_acoustic_representation_pilot.py \
  --source .cache/acousticbrainz-benchmark-metadata-20260930-v1-offline-projection-v2 \
  --expanded .cache/acoustic-expanded-metadata-20261001-v1 \
  --output .cache/acoustic-representation-expanded-review-v1
```

A new network expansion requires a fresh local cache destination:

```sh
.venv/bin/python scripts/expand_acoustic_metadata_pilot.py \
  --source .cache/acousticbrainz-benchmark-metadata-20260930-v1 \
  --output .cache/acoustic-expanded-metadata-review-v1
```

Validation: four focused unit tests cover duplicate/missing observation handling,
nonfinite rejection, held-out scale fitting/constant features, insufficient shared
feature abstention and independent cultural overlap. Focused Ruff and ty checks
pass. The real capture and both representation builds completed successfully.

## Independent offline expansion replay

A reusable verifier now lives in
`opennoise.analysis.acoustic_expansion_verification.verify_expansion`. It follows
the corrected pilot's verified lineage to the original source receipt, reconstructs
ten UUID-sorted exact-credit selections from bound search bytes, and requires
exact ordered outcomes. It rejects symlinks, unsafe inventory paths, omitted raw
files, unbound extra files and mismatched hashes. It compares reused responses
with original capture bytes/status, replays embedded identity and numeric
projection from every retained raw response, checks request/byte/state counters,
and enforces both byte limits. The representation builder invokes this verifier
before consuming expanded descriptors.

Actual source bytes replayed successfully with zero network requests; source
receipts were unchanged. The independent replay artifact is
`.cache/acoustic-expanded-metadata-replay-audit-20261001-v1.json`; a newly built
representation carrying replay evidence is
`.cache/acoustic-representation-expanded-verified-20261001-v1/pilot.json`.
Seven additional tests exercise valid replay and rehashed descriptor, source,
selection and counter spoofing, missing raw inventory and symlink rejection.
Source-verification calls are stubbed only in these small synthetic unit fixtures;
the real offline audit verifies the complete original lineage.

Replay establishes consistency of retained bytes and derivation. It cannot
independently authenticate HTTP status observations or prove request timing.
