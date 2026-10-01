# AcousticBrainz benchmark metadata review, 2026-09-30

This is an independent, read-only review of the bounded exact-recording
AcousticBrainz pilot. It uses the retained capture only; this review made no
network requests, fetched no audio, and changed no capture or pipeline files.
The pilot is local descriptive research. Its `model_input_allowed=false` and
`product_promotion_allowed=false` flags describe this pilot's scope, not a
permanent restriction implied by CC0. Any later model input needs its own
authorized, receipt-bound provenance and evaluation.

## Result

The exact MusicBrainz recording bridge and live AcousticBrainz endpoint are
promising for this deliberately small, well-known artist cohort. High-level
metadata was returned for 18 of 30 selected recordings (60%); the other 12
were explicit HTTP 404 missing records. Every available high-level response
preserved 18 classifier families, including four distinct genre model
families. The initial v1 low-level projection rejected all 18 HTTP-200
responses because two configured fields are statistics objects, not scalar
numbers. That projection defect was corrected in a separately receipted,
offline-only v2 projection from the unchanged v1 raw responses. V2 reports 18
available low-level recordings, 12 HTTP 404 missing records, and 14 of 17
declared numeric descriptors present on each of the 18 available recordings.

These are acoustic model outputs and recording features, not artist genre
truth or membership. Source age, API missingness, and variable model versions
limit conclusions. The ten artists were selected from an established named
benchmark; this says nothing about coverage for cold or absent artists.

## Rights and custody

The run retained one 8,728-byte GET response from the official
[AcousticBrainz project page](https://acousticbrainz.org/), HTTP 200, SHA-256
`dad99100be34964459ec9c936efdeacb779a403a73a1c744e27c113e7618a472`. The
captured page states that AcousticBrainz collected acoustic information
between 2015 and 2022 and that all AcousticBrainz data is under CC0. The
repository's earlier source research documents that the complete archive is
29,460,584 submissions split among 30 Zstandard archives; this pilot used
bounded API lookups instead of the large archive. No other rights requests
were made.

The exact recording API routes were
`https://acousticbrainz.org/api/v1/{recording_mbid}/high-level` and
`https://acousticbrainz.org/api/v1/{recording_mbid}/low-level`. MusicBrainz
recording search used `arid:{artist_mbid}` and `limit=25`. Selection identity
uses UUIDs and exact artist-credit IDs; display names are not identity keys.

The pilot retained 71 response bodies (1 rights + 10 search + 30 high-level +
30 low-level), totaling 2,501,062 bytes. Each body is hashed in the receipt,
with the raw files, implementation snapshots, query manifest, and projected
summary. Offline `--verify-only` replay passed and returned receipt output
SHA-256 `98a2677f4d6f5b7af7bca87d77e942b7adbf69e432bc26695b8ebf5ec514fbf6`.
The frozen query-manifest SHA-256 is
`c7cc60c88e80536c1395be81e2c397e2c00e93b3accdd835687b8f487d4d076c`.

## Cohort identity and selection limits

All ten searches returned HTTP 200 and 25 records. Each of the 25 records in
each result carried the searched artist's exact MBID in its artist credit
(250 exact-credit search rows total). The pilot selected exactly three unique
recording UUIDs per artist, sorted by UUID within the first result page, and
froze all 30 selections in the query manifest before requesting any acoustic
features. The selected recordings' embedded AcousticBrainz
`metadata.tags.musicbrainz_recordingid` matched the requested recording UUID
on every available high- and low-level response; no alias was used to repair
an identity mismatch.

This is a deterministic sample from only the first 25 API-ranked recordings
for each artist. Sorting the exact IDs makes the selection reproducible from
the frozen response, but it does not make the selected tracks representative
of the artist's discography. All ten artists are established benchmark
artists; there is no cold-start or absent-artist comparison. In this cohort,
every artist has at least one selected recording with both feature endpoints
available, ranging from one to three recordings per artist.

## Availability and the low-level projection defect

| Feature endpoint | HTTP 200 | HTTP 404 | Frozen projected state |
| --- | ---: | ---: | --- |
| High-level | 18 / 30 | 12 / 30 | 18 available; 12 `missing_http_404` |
| Low-level, original v1 | 18 / 30 | 12 / 30 | 18 `review_invalid_schema`; 12 `missing_http_404` |
| Low-level, corrected v2 | 18 / 30 | 12 / 30 | 18 available; 12 `missing_http_404` |

The 404s are missing metadata, not zero-valued features and not negative genre
examples. The source responses were all retained. The 18 available
high-level responses each include danceability, gender, four genre families
(`genre_dortmund`, `genre_electronic`, `genre_rosamerica`,
`genre_tzanetakis`), rhythm, mood, timbre, tonal/atonal, and voice/instrumental
families. The four genre models give different label sets; on this sample
their implementation metadata also varies (five distinct metadata variants
per family). Preserve family, version, and raw output separately. The JSON
`all` map is stored as a raw reported score; the API's own `probability` field
is retained only as a model-reported, uncalibrated value. Neither is factual
confidence or artist genre evidence.

The frozen v1 low-level code treated
`rhythm.bpm_histogram_first_peak_bpm` and
`rhythm.bpm_histogram_second_peak_bpm` as numeric scalars. In all 18 HTTP-200
responses they are objects containing descriptive statistics, so scalar
validation rejects the entire low-level document. This is why the verified
v1 summary reports zero available numeric descriptors despite successful
low-level HTTP responses and matching embedded recording IDs.

The corrected v2 maps each histogram object to its `mean` statistic and
retains the other fixed numeric scalar paths. Fourteen of the 17 declared
numeric descriptors have values in all 18 available responses;
`lowlevel.loudness_ebu128.integrated`,
`lowlevel.loudness_ebu128.loudness_range`, and `lowlevel.rms.mean` are absent
in all 18. Missing values remain null; no zero imputation is used.

V2 is a separate offline projection receipt, not an overwrite of v1. It binds
the unchanged v1 source capture output SHA-256
`98a2677f4d6f5b7af7bca87d77e942b7adbf69e432bc26695b8ebf5ec514fbf6`, the same
query manifest, and a new frozen code snapshot. The v2 receipt output SHA-256
is `dd800a0f859362dd4c837f29de02e5da3f13a3e9bdb5ecb4237d10b83b6796ce`.
The reprojection declaration specifies `new_upstream_requests=0`. I
independently ran both offline verifiers: v1 reproduced its original invalid
low-level states and receipt; v2 reproduced corrected states and descriptor
counts. The high-level outcomes, exact recording manifest, and all 71 raw
response bodies are unchanged.

## Next bounded step

Before any broader sample, review the 14 numeric field units and
implementation-version differences, then test coverage on predeclared cold
or absent artists. Keep high-level labels and numeric descriptors as separate,
uncalibrated, recording-level review signals; do not infer artist membership,
negative labels, source accuracy, or 100% genre parity from this benchmark.

An earlier Last.fm 360K checkpoint documents a verified archive and local
aggregate, but current cache availability was not checked in this review.
