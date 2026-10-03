# Native sonic custody, October 3, 2026

The [native-sonic pack](../../data/examples/native-sonic/README.md) independently
reconstructs a per-recording numeric source projection from retained CC0
AcousticBrainz endpoint bodies and separately verified MusicBrainz core credits.
It closes a portable native-custody gap left by the ten-artist summary example.
It does not promote the original research wrapper, fit a new model, or establish
full acoustic coverage or retrieval quality.

Before copying public raw data, `independent_gap_review` checked the retained
official provider page. Its 8,728 bytes have SHA-256
`dad99100be34964459ec9c936efdeacb779a403a73a1c744e27c113e7618a472`.
It explicitly dedicates all AcousticBrainz data to CC0. That covers native API
payloads, including uploader descriptive tags, independently of the older mixed
benchmark wrapper. It covers neither audio nor unrelated MusicBrainz search
responses. Uploader artist/genre descriptions cannot supply authoritative
credits, genre facts, or identity bridges. The new projection reads recording
identity aliases only, plus declared scalar acoustic paths.

All 103 files in the old expanded-source receipt were byte-verified before
import, including its 100 response bodies. Original files and wrapper promotion
flags remain unchanged. The new pack omits old artist vectors, search responses,
NC source associations, release context and historical evaluation targets.

| Measured custody result | Retained output |
| --- | --- |
| Frozen selection | 100 exact recording IDs across ten benchmark selection associations |
| Native AcousticBrainz response bytes | 3,051,496, unchanged |
| Available / missing HTTP 404 outcomes | 55 / 45 |
| Native recording identity on available source | 55 matched; no identity repairs |
| Scalar paths on each available recording | 14 finite values, three explicit missing fields of 17 |
| Retained / unknown AB capture dates | 30 / 70; unknown dates are null |
| Native core credit facts | 55 verified, zero missing |
| Reused / fresh native core lookups | 24 / 31 |
| Core source bytes | 25,453 total |
| Audio / new AB / Spotify requests | 0 / 0 / 0 |

The 31 new core requests use exact `recording/{UUID}?inc=artist-credits&fmt=json`
lookups, at intervals of at least 1.1 seconds, under 60-request and 1 MB combined
core-byte caps. Approved bodies must contain only core recording, credit and
artist fields, pass duplicate-key/finite-number checks, match the exact recording
UUID, and explicitly credit the cohort artist. Mixed or unapproved responses
contribute missingness and cannot enter public raw custody. Non-JSON media,
including audio, are rejected before body consumption.

Sonic values remain provider observations for exact recording identities. The
cohort selection association does not become a credit. `artist_join_allowed`
requires both an identity-verified scalar recording and an independent exact
core credit fact. No artist medians, inferred genres, memberships, relevance
judgments or fit artifacts are generated. The bounded established-artist cohort
does not evaluate cold artists, missing recordings or diverse sonic retrieval.

The previous ledger omitted source observation times and transport-complete
flags for 70 newly fetched AB responses. These remain explicitly unknown; the
October 3 import time is separate. Feature creation dates remain unknown too.
AcousticBrainz's 2015–2022 collection period limits source freshness.

```sh
.venv/bin/python scripts/build_native_sonic_pack.py \
  --output data/examples/native-sonic --verify-only
```

The verifier checks the exact closed raw-file sets, every size/hash, the complete
100-record outcome denominator, source-specific URLs, recording identities,
finite scalar schema, source dates/missingness, budget counters, strict core
credits and the complete reconstructed projection. Tests cover mismatched or
absent IDs, nonfinite/duplicate/nonscalar JSON, uploader tags, credit failure,
mixed core payloads, extra raw files, symlinks, fabricated dates, dropped missing
outcomes, byte caps, audio-body rejection and projection tampering after rehash.
No network is needed for replay. Full-foundation acceptance remains unmet.
