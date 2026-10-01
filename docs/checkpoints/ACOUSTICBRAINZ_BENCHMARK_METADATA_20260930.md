# Exact-recording AcousticBrainz metadata pilot, 2026-09-30

The bounded pilot captured usable recording-level acoustic metadata for
18 of 30 selected recordings across all ten benchmark artists. Both high- and
low-level endpoints return explicit HTTP 404 for the other twelve. Corrected
offline extraction exposes fourteen numeric descriptors for every available
recording. This is a metadata availability and provenance result, not an artist
similarity benchmark, genre validation, model improvement, or product promotion.

One live capture made 70 API requests and one official rights-page request.
It retained 2,501,062 response bytes, below the declared 3,145,728-byte total
bound. No audio was requested or read. AcousticBrainz features are preexisting
audio-derived metadata; the pilot does not claim to have performed new audio
analysis. There were no retries, redirects, archive downloads, name joins,
source-pipeline edits, or model changes.

## Exact identity and frozen sampling

The cohort comes from the already bound
`.cache/emergent-topics/bulk-adaptive-postfit-audit-20260930-v1.json`.
It contains Aphex Twin, Four Tet, Boards of Canada, Autechre, Burial,
Squarepusher, Floating Points, Caribou, Brian Eno and Jon Hopkins. Display names
do not affect identity or selection.

The pilot queried one official MusicBrainz recording search per exact artist
UUID, using `query=arid:UUID`, `limit=25` and JSON format. All ten searches
returned 25 recordings, and all 250 returned rows included the queried exact
artist UUID in their artist-credit objects. The adapter also accepts join-phrase
strings in multi-artist credits while extracting only actual artist objects.
Matching display names cannot establish an eligible credit.

Within each returned page, selection takes the first three distinct recording
UUIDs in canonical UUID order among exact credited rows. The complete
`query-manifest.json` and its search source bindings were frozen before any
AcousticBrainz feature request. The resulting 30 recording UUIDs are distinct.
This is an arbitrary bounded sample of the first search page, not a popularity
sample, representative discography sample, or an artist-wide coverage estimate.
Recordings can be alternate versions; UUID ordering does not establish sonic
independence or exclusivity to one credited artist.

Only `/api/v1/{recording_mbid}/high-level` and `/low-level` were requested,
once each for these same 30 recordings. All 36 successful feature responses
have an embedded recording ID matching the exact requested recording UUID.
The adapter checks every present supported recording-ID field, rejects any
conflicting alias, and never merges aliases. A response without an embedded
recording ID is explicitly `not_present`; it can retain endpoint-level
provenance without inventing a response identity. The twelve missing records
are `missing_http_404`, not zero-valued numeric descriptors or negative musical
observations.

## Captured availability

| Exact cohort artist | Selected recordings | High-level available / 404 | Low-level available / 404 |
| --- | ---: | ---: | ---: |
| Aphex Twin | 3 | 2 / 1 | 2 / 1 |
| Four Tet | 3 | 1 / 2 | 1 / 2 |
| Boards of Canada | 3 | 2 / 1 | 2 / 1 |
| Autechre | 3 | 3 / 0 | 3 / 0 |
| Burial | 3 | 1 / 2 | 1 / 2 |
| Squarepusher | 3 | 3 / 0 | 3 / 0 |
| Floating Points | 3 | 1 / 2 | 1 / 2 |
| Caribou | 3 | 1 / 2 | 1 / 2 |
| Brian Eno | 3 | 2 / 1 | 2 / 1 |
| Jon Hopkins | 3 | 2 / 1 | 2 / 1 |
| Total | 30 | 18 / 12 | 18 / 12 |

The numeric projection keeps BPM, mean first and second BPM-histogram peaks,
beat count, mean beat loudness, onset rate, danceability, average loudness,
dynamic complexity, mean spectral centroid/flux/zero-crossing rate, tuning
frequency, and mean HPCP entropy. Each is available in all eighteen successful
low-level records. EBU integrated loudness, EBU loudness range and RMS mean are
absent and remain `null`. Valid zero values remain zero. Only type and finite
numeric constraints apply; there are no invented descriptor ranges, inferred
calibration, arbitrary threshold labels, or aggregation into artist facts.

As descriptive sample ranges, raw BPM spans 71.43–163.79 and onset rate
0.479–7.113. Source danceability spans 0.891–1.910, which demonstrates why it
must not be treated as a probability constrained to zero through one. These
are source descriptors, not listening judgments or validated energy scores.

High-level outputs preserve every classifier family independently, including
its predicted label, raw `all` scores, source `probability` value, and version
metadata. Reported probabilities and opaque scores are finite raw source
values, explicitly uncalibrated. Families are not collapsed into one factual
genre or artist membership. For example, one Jon Hopkins recording has
electronic, trance, pop and jaz outputs across different model families. Such
disagreement requires model-family context rather than an assumed gold label.

## Preserved first projection and offline correction

The first captured implementation mistakenly expected the two BPM-histogram
peak fields to be scalars. The actual source schema represents each as a
statistics object. Its fail-closed projection therefore marked all eighteen
HTTP-200 low-level responses `review_invalid_schema`. This was a projection
defect, not missing source metadata or a recording identity failure.

The complete original capture, its original summary, receipt and frozen code
remain unchanged at `.cache/acousticbrainz-benchmark-metadata-20260930-v1`.
The corrected calculation is separately frozen at
`.cache/acousticbrainz-benchmark-metadata-20260930-v1-offline-projection-v2`.
It reads the already captured bytes, selects the two explicit `.mean`
subfields, preserves the original recording selection and every source response,
and makes **zero new upstream requests**. It binds the source capture receipt
and manifest, declares the corrected numeric paths, and freezes its own code.
Both the original v1 result and corrected v2 result replay offline. Future
captures declare the corrected numeric projection revision; the verifier keeps
explicit compatibility with the original v1 calculation.

## Rights, bounds and reproducibility

The official AcousticBrainz home page was retained completely: HTTP 200,
8,728 bytes, project identity and CC0 declaration present. Page SHA-256:
`dad99100be34964459ec9c936efdeacb779a403a73a1c744e27c113e7618a472`.
AcousticBrainz describes its submitted feature data as CC0. MusicBrainz core
recording and artist-credit metadata is also CC0 and supplies the exact identity
bridge. The complete MusicBrainz search bodies include incidental `tags` fields;
the selector ignores those fields. These raw tag associations retain the
repository's existing CC-BY-NC-SA-3.0 obligations. The capture receipt's
`source_license: CC0-1.0` denotes the AcousticBrainz feature source, not a
blanket relicensing of incidental MusicBrainz tags. Complete raw search bodies
remain local, noncommercial research with attribution/share-alike obligations.
This pilot authorizes no model input or product promotion.

| Request kind | Requests | Retained response bytes |
| --- | ---: | ---: |
| Official rights page | 1 | 8,728 |
| MusicBrainz recording search | 10 | 1,314,386 |
| AcousticBrainz high-level | 30 | 183,891 |
| AcousticBrainz low-level | 30 | 994,057 |

Requests use an identified OpenNoise application/version/contact User-Agent,
inherited proxy and TLS trust, and at least 1.1 seconds between request starts.
Each response is capped at 262,144 decoded entity-body bytes; partial bodies,
transport failures, unexpected media types and total-byte exhaustion remain
explicit. Response URLs, statuses, UTC fetch times, selected metadata headers,
byte counts and SHA-256 identities are retained. A header declaration identifies
which response headers are stored. Audio content types are rejected before
reading their bodies.

Ten focused tests pass, covering exact credits and homonyms, multi-artist
join phrases, conflicting embedded recording IDs, zero versus missing values,
finite/schema/duplicate-key boundaries, model-family separation, HTTP failures,
response/request bounds, audio media rejection, manifest freeze before features,
tampered raw bytes and re-signed inexact credits, offline replay, and the
histogram-statistic correction with original-version compatibility. Targeted
Ruff formatting, lint and type checks pass. The live capture and both offline
verification modes completed successfully.

- Original capture output identity:
  `98a2677f4d6f5b7af7bca87d77e942b7adbf69e432bc26695b8ebf5ec514fbf6`
- Frozen recording manifest SHA-256:
  `c7cc60c88e80536c1395be81e2c397e2c00e93b3accdd835687b8f487d4d076c`
- Corrected offline projection output identity:
  `dd800a0f859362dd4c837f29de02e5da3f13a3e9bdb5ecb4237d10b83b6796ce`

Reverify the existing evidence without network access:

```sh
.venv/bin/python -m scripts.capture_acousticbrainz_benchmarks \
  --output .cache/acousticbrainz-benchmark-metadata-20260930-v1 --verify-only
.venv/bin/python -m scripts.capture_acousticbrainz_benchmarks \
  --output .cache/acousticbrainz-benchmark-metadata-20260930-v1-offline-projection-v2 \
  --verify-projection
```

Capture and reprojection builders refuse to overwrite an existing destination.
Independent source or listener judgments remain necessary before using these
recording signals to assess artist-level musical relevance.
